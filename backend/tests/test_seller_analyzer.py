"""Tests del seller_analyzer.

Función pura: ListingData → list[SellerFinding].
"""

import pytest

from app.analyzers.seller_analyzer import analyze, _looks_throwaway
from app.models.report import ListingData, Source


def _listing(
    seller_name: str = "Juan Pérez",
    age: int | None = None,
) -> ListingData:
    return ListingData(
        source=Source.MERCADOLIBRE,
        title="Honda Civic 2018",
        price_mxn=230000,
        year=2018,
        make="Honda",
        model="Civic",
        kilometers=80000,
        location="CDMX",
        seller_name=seller_name,
        seller_account_age_days=age,
    )


# ---------------------------------------------------------------------------
# Account age


def test_new_account_under_30_days_is_high() -> None:
    findings = analyze(_listing(age=15))
    new_acc = [f for f in findings if f.flag == "new_account"]
    assert len(new_acc) == 1
    assert new_acc[0].severity == "high"


def test_new_account_under_90_days_is_medium() -> None:
    findings = analyze(_listing(age=60))
    new_acc = [f for f in findings if f.flag == "new_account"]
    assert len(new_acc) == 1
    assert new_acc[0].severity == "medium"


def test_old_account_no_finding() -> None:
    findings = analyze(_listing(age=400))
    new_acc = [f for f in findings if f.flag == "new_account"]
    assert new_acc == []


def test_unknown_age_no_account_finding() -> None:
    findings = analyze(_listing(age=None))
    new_acc = [f for f in findings if f.flag == "new_account"]
    assert new_acc == []


# ---------------------------------------------------------------------------
# Seller name heuristics


def test_empty_seller_name_yields_other_low() -> None:
    findings = analyze(_listing(seller_name="", age=400))
    others = [f for f in findings if f.flag == "other"]
    assert len(others) == 1
    assert others[0].severity == "low"


def test_legitimate_seller_name_no_findings() -> None:
    findings = analyze(_listing(seller_name="Auto Mart MX", age=500))
    assert findings == []


@pytest.mark.parametrize(
    "name",
    ["abc1234", "user12345", "x123", "foo_bar1234"],
)
def test_throwaway_names_flagged(name: str) -> None:
    findings = analyze(_listing(seller_name=name, age=400))
    assert any(f.flag == "new_account" and f.severity == "medium" for f in findings)


@pytest.mark.parametrize(
    "name",
    ["Juan Pérez", "Auto Mart MX", "Daytona Seminuevos", "María González"],
)
def test_real_names_not_flagged_as_throwaway(name: str) -> None:
    assert _looks_throwaway(name) is False


# ---------------------------------------------------------------------------
# Combos


def test_new_account_plus_throwaway_name_dual_flags() -> None:
    findings = analyze(_listing(seller_name="user98765", age=10))
    flags = [(f.flag, f.severity) for f in findings]
    # Cuenta nueva (high) + nombre throwaway (medium) → 2 findings new_account.
    new_acc = [f for f in findings if f.flag == "new_account"]
    assert len(new_acc) == 2
    severities = {f.severity for f in new_acc}
    assert severities == {"high", "medium"}
