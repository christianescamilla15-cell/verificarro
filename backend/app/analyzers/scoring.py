"""Combina los hallazgos de un `Report` en score 0-100 + risk_level + summary.

100% local. Función pura sin red ni I/O.

## Ponderación

Pesos style CWE: cada categoría aporta penalties con cap propio para que
un anuncio con 30 findings `low` no termine peor que uno robado.

| Señal                                      | Penalty | Cap (max acumulado) |
|--------------------------------------------|---------|---------------------|
| REPUVE: vehículo robado                    | 50      | 50 (terminal)       |
| REPUVE: situación legal irregular          | 25      | 25                  |
| Precio sobrepuesto (anuncio +30% vs fair)  | 10      | 10                  |
| Precio sospechosamente barato (-30%+)      | 15      | 15                  |
| photo / description finding `high`         | 10 c/u  | 30                  |
| photo / description finding `medium`       | 3 c/u   | 15                  |
| photo / description finding `low`          | 1 c/u   | 5                   |
| seller_finding `high`                      | 15 c/u  | 30                  |
| seller_finding `medium`                    | 5 c/u   | 15                  |
| seller_finding `low`                       | 0       | 0 (informativo)     |

`score = max(0, 100 - sum(penalties))`.

## Risk levels

- `green` ≥ 70: probablemente legítimo
- `yellow` 40-69: precaución, varios flags
- `red` < 40: red flags graves, no compres sin verificar

## Summary

Texto en español explicando el score con los 3 hallazgos más importantes
y una recomendación accionable.
"""

from __future__ import annotations

from app.models.report import (
    DescriptionFinding,
    PhotoFinding,
    PriceEstimate,
    Report,
    RepuveResult,
    RiskLevel,
    SellerFinding,
)


_PRICE_OVERPRICED_THRESHOLD = 30.0  # delta_pct ≥ +30% → sobrepuesto
_PRICE_TOO_CHEAP_THRESHOLD = -30.0  # delta_pct ≤ -30% → sospechoso

_GREEN_MIN = 70
_YELLOW_MIN = 40

# Caps acumulados por categoría
_CAP_FINDING_HIGH = 30
_CAP_FINDING_MEDIUM = 15
_CAP_FINDING_LOW = 5
_CAP_SELLER_HIGH = 30
_CAP_SELLER_MEDIUM = 15


def compute_score(report: Report) -> tuple[int, RiskLevel, str]:
    """Devuelve (score, risk_level, summary) para el `Report` dado.

    No muta el report — solo lee. La función `populate` lo escribe.

    Kill switches: ciertas señales convierten el risk a `red`
    independientemente del score numérico, porque indican fraude
    terminal:
    - REPUVE marca el vehículo como robado
    - VIN escaneado tiene alerta `high` (placa clonada / VIN distinto
      al de la descripción / VIN no coincide con REPUVE)
    """
    penalty, reasons = _compute_penalty(report)
    score = max(0, 100 - penalty)
    risk = _risk_level(score)

    # Kill switches → fuerzan red sin importar el score
    if report.repuve.is_stolen is True:
        risk = RiskLevel.RED
    if report.vin_check is not None and any(
        a.severity == "high" for a in report.vin_check.alerts
    ):
        risk = RiskLevel.RED

    summary = _build_summary(report, score, risk, reasons)
    return score, risk, summary


def populate(report: Report) -> Report:
    """Mutante conveniente: corre `compute_score` y escribe los campos."""
    score, risk, summary = compute_score(report)
    report.score = score
    report.risk_level = risk
    report.summary = summary
    return report


# ---------------------------------------------------------------------------
# Penalty calculator


def _compute_penalty(report: Report) -> tuple[int, list[str]]:
    """Devuelve (penalty_total, lista de razones legibles para el summary)."""
    total = 0
    reasons: list[str] = []

    total += _repuve_penalty(report.repuve, reasons)
    total += _price_penalty(report.price, reasons)
    total += _findings_penalty(
        report.photo_findings,
        label="fotos",
        reasons=reasons,
    )
    total += _findings_penalty(
        report.description_findings,
        label="descripción",
        reasons=reasons,
    )
    total += _seller_penalty(report.seller_findings, reasons)
    total += _vin_penalty(report.vin_check, reasons)

    return total, reasons


def _vin_penalty(vin_check, reasons: list[str]) -> int:
    """Penaliza alertas del VIN escaneado.

    `high` es penalty -25 (equivalente a REPUVE legal irregular) porque
    indica posible clonación de placa — uno de los fraudes más caros.
    `medium` es -8 (año fuera de tolerancia, etc).
    `low` es 0 (informativo, ej. ±1 año).
    """
    if vin_check is None:
        return 0
    high = sum(1 for a in vin_check.alerts if a.severity == "high")
    med = sum(1 for a in vin_check.alerts if a.severity == "medium")
    if high:
        reasons.append(
            f"VIN escaneado discrepa con el anuncio ({high} alerta(s) graves)"
        )
        return min(25 * high, 50)
    if med:
        return min(8 * med, 16)
    return 0


def _repuve_penalty(repuve: RepuveResult, reasons: list[str]) -> int:
    if repuve.is_stolen is True:
        reasons.append("REPUVE marca el vehículo como ROBADO")
        return 50
    penalty = 0
    if repuve.has_legal_status is False:
        reasons.append("REPUVE indica situación legal irregular")
        penalty += 25
    return penalty


def _price_penalty(price: PriceEstimate, reasons: list[str]) -> int:
    if price.delta_pct is None or price.fair_price_mxn is None:
        return 0
    delta = price.delta_pct
    if delta >= _PRICE_OVERPRICED_THRESHOLD:
        reasons.append(
            f"Precio del anuncio está {delta:+.0f}% sobre el justo (sobrepuesto)"
        )
        return 10
    if delta <= _PRICE_TOO_CHEAP_THRESHOLD:
        reasons.append(
            f"Precio del anuncio está {delta:+.0f}% bajo el justo "
            "(sospechosamente barato — verifica que no sea estafa)"
        )
        return 15
    return 0


def _findings_penalty(
    findings: list[PhotoFinding] | list[DescriptionFinding],
    *,
    label: str,
    reasons: list[str],
) -> int:
    """Pondera findings de fotos o descripción con cap por severidad."""
    high = sum(1 for f in findings if f.severity == "high")
    med = sum(1 for f in findings if f.severity == "medium")
    low = sum(1 for f in findings if f.severity == "low")

    pen_high = min(high * 10, _CAP_FINDING_HIGH)
    pen_med = min(med * 3, _CAP_FINDING_MEDIUM)
    pen_low = min(low * 1, _CAP_FINDING_LOW)

    if high:
        reasons.append(f"{high} red flag(s) graves en {label}")
    elif med:
        reasons.append(f"{med} hallazgo(s) medio(s) en {label}")

    return pen_high + pen_med + pen_low


def _seller_penalty(findings: list[SellerFinding], reasons: list[str]) -> int:
    high = sum(1 for f in findings if f.severity == "high")
    med = sum(1 for f in findings if f.severity == "medium")

    pen_high = min(high * 15, _CAP_SELLER_HIGH)
    pen_med = min(med * 5, _CAP_SELLER_MEDIUM)

    if high:
        reasons.append(f"{high} bandera(s) graves en el vendedor")

    return pen_high + pen_med


# ---------------------------------------------------------------------------
# Summary builder


def _risk_level(score: int) -> RiskLevel:
    if score >= _GREEN_MIN:
        return RiskLevel.GREEN
    if score >= _YELLOW_MIN:
        return RiskLevel.YELLOW
    return RiskLevel.RED


def _build_summary(
    report: Report,
    score: int,
    risk: RiskLevel,
    reasons: list[str],
) -> str:
    """Texto narrativo en español. Cierra con recomendación según risk."""
    head = _head_for_risk(score, risk, report)
    body = ""
    if reasons:
        top = reasons[:3]
        bullets = "\n".join(f"  • {r}" for r in top)
        body = f"\n\nHallazgos principales:\n{bullets}"
        if len(reasons) > 3:
            body += f"\n  • (+{len(reasons) - 3} hallazgo(s) menor(es))"
    recommendation = _recommendation_for_risk(risk)
    return f"{head}{body}\n\n{recommendation}"


def _head_for_risk(score: int, risk: RiskLevel, report: Report) -> str:
    listing = report.listing
    titulo = listing.title or f"{listing.make} {listing.model}".strip() or "el anuncio"
    if risk == RiskLevel.GREEN:
        return (
            f"Verificarro le da {score}/100 a este anuncio ({titulo}). "
            "El análisis no encontró banderas graves — el riesgo aparente "
            "es bajo."
        )
    if risk == RiskLevel.YELLOW:
        return (
            f"Verificarro le da {score}/100 a este anuncio ({titulo}). "
            "Hay varios puntos a revisar antes de soltar el cash."
        )
    return (
        f"Verificarro le da {score}/100 a este anuncio ({titulo}). "
        "El análisis encontró banderas graves — alto riesgo de estafa o "
        "problema legal."
    )


def _recommendation_for_risk(risk: RiskLevel) -> str:
    if risk == RiskLevel.GREEN:
        return (
            "Recomendación: aún así, pide ver el auto físicamente, verifica "
            "factura original y consulta REPUVE manualmente con la placa "
            "antes de cerrar."
        )
    if risk == RiskLevel.YELLOW:
        return (
            "Recomendación: NO cierres trato sin (1) ver el auto en persona, "
            "(2) verificar REPUVE con la placa, y (3) revisión mecánica con "
            "tu mecánico de confianza."
        )
    return (
        "Recomendación: NO compres este auto sin verificación profesional. "
        "Si el vendedor presiona o se niega a inspección, walk away — no "
        "hay precio que justifique el riesgo."
    )
