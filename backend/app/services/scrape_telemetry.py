"""Scrape telemetry — registro estructurado de cada intento del scraper REPUVE.

Almacena en SQLite local cada attempt con las técnicas aplicadas + outcome.
Permite A/B comparar configs distintas y aprender qué playbook tiene mejor
hit rate (Fase 2 del roadmap captcha).

## Schema

Tabla única `attempts`:
- id: autoincrement
- timestamp: ISO datetime UTC
- config_label: str — nombre del experimento (e.g. "default", "moremoves_v2")
- plate, vin: input
- techniques_json: JSON con técnicas aplicadas
- outcome_json: JSON con resultado completo
- queried: bool — True si el scrape SÍ devolvió datos REPUVE
- raw_status: str — captcha_required, sin_reportes, etc.
- duration_ms: int — total latency del attempt
- captcha_solver_ms: int | null — solo si se invocó 2Captcha

## Filosofía

- Fail-open: si DB write falla, NO se bloquea el scrape
- Tamaño bounded: rotar / vacuum cada 10K rows (no implementado MVP)
- Pure functions con dependency injection (DB path) → testeable

## Uso

    from app.services.scrape_telemetry import record_attempt, get_attempts

    record_attempt(
        config_label="default",
        plate="ABC123",
        vin=None,
        techniques={"headless": True, "stealth_flags": [...]},
        outcome={"queried": False, "raw_status": "captcha_required", ...},
    )
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_DEFAULT_DB_PATH = "/app/data/scrape_telemetry.db"
_db_lock = threading.Lock()


def _resolve_db_path() -> str:
    """Permite override vía env var (útil en tests + dev local)."""
    return os.environ.get("SCRAPE_TELEMETRY_DB", _DEFAULT_DB_PATH)


@contextmanager
def _connect():
    """Connection con WAL mode + auto-create dir/schema. Thread-safe via lock."""
    db_path = _resolve_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with _db_lock:
        conn = sqlite3.connect(db_path, timeout=10.0)
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    config_label TEXT NOT NULL,
                    plate TEXT,
                    vin TEXT,
                    techniques_json TEXT NOT NULL,
                    outcome_json TEXT NOT NULL,
                    queried INTEGER NOT NULL,
                    raw_status TEXT,
                    duration_ms INTEGER,
                    captcha_solver_ms INTEGER
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_attempts_ts ON attempts(timestamp DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_attempts_config ON attempts(config_label, queried)"
            )
            yield conn
            conn.commit()
        finally:
            conn.close()


def record_attempt(
    *,
    config_label: str,
    plate: str | None,
    vin: str | None,
    techniques: dict[str, Any],
    outcome: dict[str, Any],
) -> None:
    """Loguea un intento. Failure-tolerant: errores SQLite no propagan."""
    try:
        ts = datetime.now(UTC).isoformat()
        queried = bool(outcome.get("queried", False))
        raw_status = outcome.get("raw_status")
        duration_ms = outcome.get("duration_ms")
        captcha_solver_ms = outcome.get("captcha_solver_ms")
        with _connect() as conn:
            conn.execute(
                """INSERT INTO attempts (
                    timestamp, config_label, plate, vin,
                    techniques_json, outcome_json,
                    queried, raw_status, duration_ms, captcha_solver_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ts, config_label, plate, vin,
                    json.dumps(techniques, default=str),
                    json.dumps(outcome, default=str),
                    1 if queried else 0,
                    raw_status,
                    duration_ms,
                    captcha_solver_ms,
                ),
            )
    except Exception:  # noqa: BLE001
        logger.exception("Telemetry record falló (no-bloqueante)")


def get_attempts(
    *,
    limit: int = 100,
    config_label: str | None = None,
    since_ts: str | None = None,
) -> list[dict[str, Any]]:
    """Devuelve attempts ordenados por timestamp descendente.

    `since_ts`: opcional ISO timestamp; solo retorna attempts más recientes.
    `config_label`: opcional filter por experimento.
    """
    where = []
    params: list[Any] = []
    if config_label:
        where.append("config_label = ?")
        params.append(config_label)
    if since_ts:
        where.append("timestamp >= ?")
        params.append(since_ts)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    params.append(int(limit))

    with _connect() as conn:
        cursor = conn.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- WHERE armado con literales y valores con «?»
            f"""SELECT id, timestamp, config_label, plate, vin,
                techniques_json, outcome_json, queried, raw_status,
                duration_ms, captcha_solver_ms
                FROM attempts {where_sql}
                ORDER BY timestamp DESC LIMIT ?""",
            params,
        )
        rows = cursor.fetchall()

    out = []
    for r in rows:
        out.append({
            "id": r[0],
            "timestamp": r[1],
            "config_label": r[2],
            "plate": r[3],
            "vin": r[4],
            "techniques": json.loads(r[5]) if r[5] else {},
            "outcome": json.loads(r[6]) if r[6] else {},
            "queried": bool(r[7]),
            "raw_status": r[8],
            "duration_ms": r[9],
            "captcha_solver_ms": r[10],
        })
    return out


def aggregate_stats(
    *,
    since_ts: str | None = None,
) -> dict[str, Any]:
    """Estadísticas agregadas por config_label.

    Devuelve:
        {
          "total": 47,
          "by_config": [
            {"config_label": "default", "attempts": 30,
             "queried_count": 3, "hit_rate_pct": 10.0,
             "avg_duration_ms": 12500, "common_status": "captcha_required"},
            ...
          ]
        }
    """
    where = []
    params: list[Any] = []
    if since_ts:
        where.append("timestamp >= ?")
        params.append(since_ts)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    with _connect() as conn:
        total = conn.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- WHERE armado con literales y valores con «?»
            f"SELECT COUNT(*) FROM attempts {where_sql}", params,
        ).fetchone()[0]

        # Aggregate por config — también dame el raw_status más común
        rows = conn.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- WHERE armado con literales y valores con «?»
            f"""SELECT config_label,
                       COUNT(*) AS attempts,
                       SUM(queried) AS queried_count,
                       AVG(duration_ms) AS avg_dur,
                       AVG(captcha_solver_ms) AS avg_solver
                FROM attempts {where_sql}
                GROUP BY config_label
                ORDER BY attempts DESC""",
            params,
        ).fetchall()

        # Para cada config, buscar el raw_status más común
        result_configs = []
        for r in rows:
            config_label = r[0]
            attempts = r[1]
            queried_count = r[2] or 0
            inner_params = list(params)
            inner_params.append(config_label)
            common = conn.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- WHERE armado con literales y valores con «?»
                f"""SELECT raw_status, COUNT(*) AS c
                    FROM attempts {where_sql}
                    {"AND" if where else "WHERE"} config_label = ?
                    GROUP BY raw_status ORDER BY c DESC LIMIT 1""",
                inner_params,
            ).fetchone()
            common_status = common[0] if common else None
            result_configs.append({
                "config_label": config_label,
                "attempts": attempts,
                "queried_count": queried_count,
                "hit_rate_pct": round(queried_count * 100 / attempts, 2) if attempts else 0.0,
                "avg_duration_ms": int(r[3]) if r[3] else None,
                "avg_solver_ms": int(r[4]) if r[4] else None,
                "common_status": common_status,
            })

    return {"total": total, "by_config": result_configs}
