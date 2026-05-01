"""Genera el PDF del reporte de Verificarro a partir de un `Report`.

Usa `reportlab` (ya en requirements.txt). Sin red, sin descarga de
imágenes — el PDF muestra URLs de fotos como links pero no las
embebe (mantiene el PDF chico y rápido).

## Layout

1. **Header**: "Verificarro" + logo de texto + fecha del reporte
2. **Score chip**: número grande 0-100 + risk_level coloreado
3. **Summary**: texto narrativo del scoring engine
4. **Datos del anuncio**: título, precio, año/marca/modelo, kms, ubicación
5. **REPUVE**: status (robado/limpio/no consultado)
6. **Precio justo**: fair, rango, delta
7. **Red flags** (3 secciones):
   - Descripción (máx 5)
   - Fotos (máx 5)
   - Vendedor (máx 5)
8. **Preguntas para el vendedor**
9. **Footer**: disclaimer + URL Verificarro

Output: `bytes` con el PDF binario. El caller decide si lo escribe a
disco, lo manda al frontend como `application/pdf`, o lo guarda en
storage para link compartible.
"""

from __future__ import annotations

import io
from datetime import datetime, UTC

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.models.report import Report, RiskLevel


_RISK_COLORS = {
    RiskLevel.GREEN: colors.HexColor("#14a34a"),
    RiskLevel.YELLOW: colors.HexColor("#d97706"),
    RiskLevel.RED: colors.HexColor("#dc2626"),
}

_RISK_LABELS = {
    RiskLevel.GREEN: "RIESGO BAJO",
    RiskLevel.YELLOW: "PRECAUCIÓN",
    RiskLevel.RED: "ALTO RIESGO",
}


def generate_pdf(report: Report) -> bytes:
    """Render del Report → PDF binario."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
        title=f"Verificarro — {report.listing.title or 'Reporte'}",
    )

    styles = _build_styles()
    flow = []
    flow += _header(styles)
    flow += _score_block(report, styles)
    flow += _summary_block(report, styles)
    flow += _listing_block(report, styles)
    flow += _repuve_block(report, styles)
    flow += _price_block(report, styles)
    flow += _findings_block(report, styles)
    flow += _questions_block(report, styles)
    flow += _footer(styles)

    doc.build(flow)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Styles


def _build_styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title", parent=base["Title"], fontSize=24, leading=28,
            textColor=colors.HexColor("#ffb84d"), spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle", parent=base["Normal"], fontSize=10, leading=12,
            textColor=colors.HexColor("#6b7280"), alignment=TA_LEFT,
            spaceAfter=12,
        ),
        "section": ParagraphStyle(
            "Section", parent=base["Heading2"], fontSize=14, leading=18,
            textColor=colors.HexColor("#11161c"), spaceBefore=12, spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "Body", parent=base["Normal"], fontSize=10, leading=14,
            textColor=colors.HexColor("#11161c"),
        ),
        "muted": ParagraphStyle(
            "Muted", parent=base["Normal"], fontSize=9, leading=12,
            textColor=colors.HexColor("#6b7280"),
        ),
        "score_num": ParagraphStyle(
            "ScoreNum", parent=base["Title"], fontSize=64, leading=68,
            alignment=TA_CENTER,
        ),
        "score_label": ParagraphStyle(
            "ScoreLabel", parent=base["Normal"], fontSize=11, leading=14,
            alignment=TA_CENTER, fontName="Helvetica-Bold",
        ),
        "footer": ParagraphStyle(
            "Footer", parent=base["Normal"], fontSize=8, leading=10,
            textColor=colors.HexColor("#9ca3af"), alignment=TA_CENTER,
        ),
    }


# ---------------------------------------------------------------------------
# Sections


def _header(styles: dict) -> list:
    fecha = datetime.now(UTC).strftime("%d/%m/%Y %H:%M UTC")
    return [
        Paragraph("Verificarro", styles["title"]),
        Paragraph(
            f"Reporte de verificación de auto usado · {fecha}",
            styles["subtitle"],
        ),
    ]


def _score_block(report: Report, styles: dict) -> list:
    color = _RISK_COLORS.get(report.risk_level, colors.HexColor("#6b7280"))
    label = _RISK_LABELS.get(report.risk_level, "—")
    score_para = Paragraph(
        f'<font color="{color.hexval()}">{report.score}</font>'
        f'<font size="20" color="#9ca3af">/100</font>',
        styles["score_num"],
    )
    label_para = Paragraph(
        f'<font color="{color.hexval()}">{label}</font>',
        styles["score_label"],
    )
    table = Table([[score_para], [label_para]], colWidths=[7.3 * inch])
    table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 1, color),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f9fafb")),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return [table, Spacer(1, 14)]


def _summary_block(report: Report, styles: dict) -> list:
    body = report.summary.replace("\n", "<br/>")
    return [
        Paragraph("Resumen", styles["section"]),
        Paragraph(body, styles["body"]),
    ]


def _listing_block(report: Report, styles: dict) -> list:
    listing = report.listing
    rows = [
        ["Título", _safe(listing.title)],
        [
            "Precio anuncio",
            f"${listing.price_mxn:,.0f} MXN" if listing.price_mxn else "—",
        ],
        ["Marca / Modelo", _safe(f"{listing.make} {listing.model}".strip())],
        ["Año", str(listing.year) if listing.year else "—"],
        [
            "Kilómetros",
            f"{listing.kilometers:,} km" if listing.kilometers else "—",
        ],
        ["Ubicación", _safe(listing.location)],
        ["Vendedor", _safe(listing.seller_name) or "—"],
    ]
    if listing.source_url:
        rows.append(["URL", _safe(listing.source_url)])
    return [
        Paragraph("Datos del anuncio", styles["section"]),
        _kv_table(rows),
    ]


def _repuve_block(report: Report, styles: dict) -> list:
    r = report.repuve
    if not r.queried and r.error:
        msg = r.error
    elif r.is_stolen is True:
        msg = "🚨 Vehículo REPORTADO COMO ROBADO"
    elif r.is_stolen is False:
        legal = (
            "situación legal regular" if r.has_legal_status is True
            else "situación legal irregular" if r.has_legal_status is False
            else "situación legal no verificada"
        )
        msg = f"Sin reportes de robo · {legal}"
    else:
        msg = "REPUVE no consultado"

    rows = [["Estatus", _safe(msg)]]
    if r.plate:
        rows.append(["Placa", r.plate])
    if r.vin:
        rows.append(["NIV", r.vin])
    return [
        Paragraph("REPUVE (gob.mx)", styles["section"]),
        _kv_table(rows),
    ]


def _price_block(report: Report, styles: dict) -> list:
    p = report.price
    if p.fair_price_mxn is None or p.comparables_count == 0:
        return [
            Paragraph("Precio justo", styles["section"]),
            Paragraph(
                "No se pudo estimar precio justo (no hay comparables suficientes).",
                styles["muted"],
            ),
        ]
    delta_color = colors.HexColor("#14a34a")
    if p.delta_pct is not None and abs(p.delta_pct) > 15:
        delta_color = colors.HexColor("#d97706")
    if p.delta_pct is not None and abs(p.delta_pct) > 30:
        delta_color = colors.HexColor("#dc2626")
    delta_text = (
        f'<font color="{delta_color.hexval()}">{p.delta_pct:+.1f}%</font>'
        if p.delta_pct is not None else "—"
    )
    rows = [
        ["Precio justo (mediana)", f"${p.fair_price_mxn:,.0f} MXN"],
        [
            "Rango p10-p90",
            f"${p.range_low_mxn:,.0f} – ${p.range_high_mxn:,.0f} MXN"
            if p.range_low_mxn and p.range_high_mxn else "—",
        ],
        ["Delta vs anuncio", Paragraph(delta_text, styles["body"])],
        ["Comparables analizados", str(p.comparables_count)],
        ["Fuentes", _safe(", ".join(p.sources)) or "—"],
    ]
    return [
        Paragraph("Precio justo", styles["section"]),
        _kv_table(rows),
    ]


def _findings_block(report: Report, styles: dict) -> list:
    out: list = [Paragraph("Banderas y hallazgos", styles["section"])]
    out += _findings_subsection(
        "Descripción del anuncio", report.description_findings, styles,
        get_text=lambda f: f.excerpt,
    )
    out += _findings_subsection(
        "Fotos analizadas con IA", report.photo_findings, styles,
        get_text=lambda f: f"Foto #{f.photo_index + 1}: {f.note}",
    )
    out += _findings_subsection(
        "Vendedor", report.seller_findings, styles,
        get_text=lambda f: f.note,
    )
    return out


def _findings_subsection(label: str, findings: list, styles: dict, *, get_text) -> list:
    if not findings:
        return [
            Paragraph(f"<b>{label}:</b> sin banderas detectadas.", styles["muted"]),
            Spacer(1, 4),
        ]
    rows = []
    for f in findings[:5]:
        sev = (f.severity or "low").upper()
        sev_color = {
            "HIGH": "#dc2626", "MEDIUM": "#d97706", "LOW": "#6b7280",
        }.get(sev, "#6b7280")
        rows.append([
            Paragraph(f'<font color="{sev_color}"><b>{sev}</b></font>',
                      styles["body"]),
            Paragraph(_safe(get_text(f)), styles["body"]),
        ])
    table = Table(rows, colWidths=[0.9 * inch, 6.4 * inch])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#e5e7eb")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    extra = ""
    if len(findings) > 5:
        extra = f" (+{len(findings) - 5} más)"
    return [
        Paragraph(f"<b>{label}{extra}</b>", styles["body"]),
        Spacer(1, 4),
        table,
        Spacer(1, 8),
    ]


def _questions_block(report: Report, styles: dict) -> list:
    if not report.questions_for_seller:
        return []
    items = "<br/>".join(
        f"{i + 1}. {_safe(q)}"
        for i, q in enumerate(report.questions_for_seller)
    )
    return [
        Paragraph("Preguntas para el vendedor", styles["section"]),
        Paragraph(items, styles["body"]),
    ]


def _footer(styles: dict) -> list:
    return [
        Spacer(1, 18),
        Paragraph(
            "Verificarro v0.1 · Reporte informativo, no sustituye revisión "
            "mecánica profesional · Hecho en México 🇲🇽",
            styles["footer"],
        ),
    ]


# ---------------------------------------------------------------------------
# Helpers


def _kv_table(rows: list) -> Table:
    """Tabla de 2 columnas (label / value) con estilo consistente."""
    formatted = []
    for label, value in rows:
        if not isinstance(value, Paragraph):
            value = Paragraph(_safe(str(value)), getSampleStyleSheet()["BodyText"])
        formatted.append([
            Paragraph(f"<b>{label}</b>", getSampleStyleSheet()["BodyText"]),
            value,
        ])
    table = Table(formatted, colWidths=[1.6 * inch, 5.7 * inch])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#e5e7eb")),
    ]))
    return table


def _safe(value) -> str:
    """Escapa caracteres conflictivos para el mini-HTML de reportlab."""
    if value is None:
        return ""
    s = str(value)
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
