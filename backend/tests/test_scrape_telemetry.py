"""Tests del módulo scrape_telemetry — almacén SQLite + agregaciones."""

from __future__ import annotations

import os

import pytest

from app.services.scrape_telemetry import (
    aggregate_stats,
    get_attempts,
    record_attempt,
)


@pytest.fixture(autouse=True)
def isolated_telemetry_db(tmp_path, monkeypatch):
    """Cada test usa una DB SQLite efímera bajo tmp_path → no leak entre tests."""
    db = tmp_path / "telemetry.db"
    monkeypatch.setenv("SCRAPE_TELEMETRY_DB", str(db))
    yield


# ---------------------------------------------------------------------------
# record_attempt + get_attempts


def test_record_and_retrieve_single_attempt() -> None:
    record_attempt(
        config_label="default",
        plate="ABC123",
        vin=None,
        techniques={"headless": True, "stealth_flags": ["AC"]},
        outcome={"queried": False, "raw_status": "captcha_required",
                 "duration_ms": 12000},
    )
    rows = get_attempts(limit=10)
    assert len(rows) == 1
    assert rows[0]["plate"] == "ABC123"
    assert rows[0]["queried"] is False
    assert rows[0]["raw_status"] == "captcha_required"
    assert rows[0]["techniques"]["headless"] is True
    assert rows[0]["duration_ms"] == 12000


def test_record_attempt_marks_queried_true_correctly() -> None:
    record_attempt(
        config_label="default", plate="XYZ789", vin=None,
        techniques={"headless": True},
        outcome={"queried": True, "raw_status": "sin_reportes",
                 "duration_ms": 8000, "is_stolen": False},
    )
    rows = get_attempts(limit=10)
    assert rows[0]["queried"] is True
    assert rows[0]["raw_status"] == "sin_reportes"


def test_get_attempts_returns_descending_order() -> None:
    for i in range(5):
        record_attempt(
            config_label="default", plate=f"PLT{i}", vin=None,
            techniques={}, outcome={"queried": False},
        )
    rows = get_attempts(limit=10)
    assert len(rows) == 5
    # Más reciente primero
    assert rows[0]["plate"] == "PLT4"
    assert rows[-1]["plate"] == "PLT0"


def test_get_attempts_filters_by_config_label() -> None:
    record_attempt(config_label="exp_a", plate="A1", vin=None,
                   techniques={}, outcome={"queried": False})
    record_attempt(config_label="exp_b", plate="B1", vin=None,
                   techniques={}, outcome={"queried": True})
    record_attempt(config_label="exp_a", plate="A2", vin=None,
                   techniques={}, outcome={"queried": False})

    only_a = get_attempts(limit=10, config_label="exp_a")
    assert len(only_a) == 2
    assert all(r["config_label"] == "exp_a" for r in only_a)

    only_b = get_attempts(limit=10, config_label="exp_b")
    assert len(only_b) == 1
    assert only_b[0]["plate"] == "B1"


def test_record_attempt_failure_does_not_propagate(monkeypatch) -> None:
    """Si SQLite falla, telemetry NO debe romper el caller."""
    # Apunta a un path inválido
    monkeypatch.setenv("SCRAPE_TELEMETRY_DB", "/definitely/no/such/dir/db.sqlite")
    # No raise:
    record_attempt(
        config_label="default", plate="ABC", vin=None,
        techniques={}, outcome={"queried": False},
    )


# ---------------------------------------------------------------------------
# aggregate_stats


def test_aggregate_stats_empty_db() -> None:
    stats = aggregate_stats()
    assert stats["total"] == 0
    assert stats["by_config"] == []


def test_aggregate_stats_single_config_with_mixed_outcomes() -> None:
    # 8 attempts, 2 hits → 25%
    for i in range(8):
        record_attempt(
            config_label="default", plate=f"P{i}", vin=None,
            techniques={"headless": True},
            outcome={
                "queried": i < 2,  # 2 primeros queried=True
                "raw_status": "sin_reportes" if i < 2 else "captcha_required",
                "duration_ms": 10000,
            },
        )
    stats = aggregate_stats()
    assert stats["total"] == 8
    assert len(stats["by_config"]) == 1
    cfg = stats["by_config"][0]
    assert cfg["config_label"] == "default"
    assert cfg["attempts"] == 8
    assert cfg["queried_count"] == 2
    assert cfg["hit_rate_pct"] == 25.0


def test_aggregate_stats_multiple_configs_compared() -> None:
    """A/B comparison: dos configs con diferente hit rate."""
    # exp_a: 3/5 = 60%
    for i in range(5):
        record_attempt(
            config_label="exp_a", plate=f"A{i}", vin=None,
            techniques={"variant": "a"},
            outcome={"queried": i < 3, "raw_status": "sin_reportes" if i < 3 else "captcha_required"},
        )
    # exp_b: 1/5 = 20%
    for i in range(5):
        record_attempt(
            config_label="exp_b", plate=f"B{i}", vin=None,
            techniques={"variant": "b"},
            outcome={"queried": i < 1, "raw_status": "sin_reportes" if i < 1 else "captcha_required"},
        )

    stats = aggregate_stats()
    assert stats["total"] == 10
    by_label = {c["config_label"]: c for c in stats["by_config"]}
    assert by_label["exp_a"]["hit_rate_pct"] == 60.0
    assert by_label["exp_b"]["hit_rate_pct"] == 20.0


def test_aggregate_stats_common_status_per_config() -> None:
    # Mayoritaria captcha_required en exp_a
    for i in range(10):
        record_attempt(
            config_label="exp_a", plate=f"P{i}", vin=None,
            techniques={},
            outcome={"queried": False, "raw_status": "captcha_required"},
        )
    record_attempt(
        config_label="exp_a", plate="P_unique", vin=None,
        techniques={},
        outcome={"queried": False, "raw_status": "rate_limit_429"},
    )

    stats = aggregate_stats()
    cfg = stats["by_config"][0]
    assert cfg["common_status"] == "captcha_required"
    assert cfg["attempts"] == 11
