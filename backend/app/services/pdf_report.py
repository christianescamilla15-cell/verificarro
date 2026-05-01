"""Genera el PDF del reporte de Verificarro a partir de un `Report`.

Usa `reportlab` (ya en requirements.txt). Sin red, sin descarga de
imágenes — el PDF muestra URLs de fotos como links pero no las
embebe (mantiene el PDF chico y rápido).

## Layout (v0.2 — incluye TODAS las features Fase A/B/C)

1. **Header**: "Verificarro" + fecha del reporte
2. **Score chip**: número grande 0-100 + risk_level coloreado
3. **Summary**: texto narrativo del scoring engine
4. **Datos del anuncio**: título, precio, año/marca/modelo, kms, ubicación
5. **REPUVE**: status (robado/limpio/no consultado)
6. **Verificación VIN físico** (si hubo escaneo): decoded local +
   NHTSA enrichment (make oficial, body class, plant country)
7. **Factura del auto** (si hay invoice_data): folio + datos OCR + SAT status
8. **Precio justo**: fair, rango, delta
9. **Cross-listings** (otros marketplaces): tabla con title/price/source
10. **Red flags** (4 secciones):
    - Descripción
    - Fotos (incluye photo dedup como issue=watermark_or_stock)
    - EXIF metadata (Photoshop, batch fakes)
    - Vendedor
11. **Consultas oficiales gob.mx**: lista de links pre-llenados
12. **Preguntas para el vendedor**
13. **Footer**: disclaimer + URL Verificarro

Output: `bytes` con el PDF binario.
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


# Paleta v2 (visual de confianza): primary blue, accent cyan.
# Para PDF print-safe usamos versión sólida (no gradients).
_BRAND_PRIMARY = colors.HexColor("#0084ff")  # blue-9 print-friendly
_BRAND_ACCENT = colors.HexColor("#06b6d4")   # cyan-9
_TEXT_PRIMARY = colors.HexColor("#0f172a")   # slate-12 (dark on white PDF)
_TEXT_SECONDARY = colors.HexColor("#475569")
_TEXT_MUTED = colors.HexColor("#94a3b8")
_BORDER_LIGHT = colors.HexColor("#e2e8f0")

_RISK_COLORS = {
    RiskLevel.GREEN: colors.HexColor("#16a34a"),
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
    flow += _vin_check_block(report, styles)
    flow += _invoice_block(report, styles)
    flow += _price_block(report, styles)
    flow += _cross_listings_block(report, styles)
    flow += _findings_block(report, styles)
    flow += _gob_mx_links_block(report, styles)
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
            textColor=_BRAND_PRIMARY, spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle", parent=base["Normal"], fontSize=10, leading=12,
            textColor=_TEXT_SECONDARY, alignment=TA_LEFT,
            spaceAfter=12,
        ),
        "section": ParagraphStyle(
            "Section", parent=base["Heading2"], fontSize=14, leading=18,
            textColor=_TEXT_PRIMARY, spaceBefore=14, spaceAfter=6,
        ),
        "subsection": ParagraphStyle(
            "Subsection", parent=base["Normal"], fontSize=11, leading=14,
            textColor=_BRAND_PRIMARY, spaceBefore=4, spaceAfter=2,
            fontName="Helvetica-Bold",
        ),
        "body": ParagraphStyle(
            "Body", parent=base["Normal"], fontSize=10, leading=14,
            textColor=_TEXT_PRIMARY,
        ),
        "muted": ParagraphStyle(
            "Muted", parent=base["Normal"], fontSize=9, leading=12,
            textColor=_TEXT_SECONDARY,
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
            textColor=_TEXT_MUTED, alignment=TA_CENTER,
        ),
        "warn_box": ParagraphStyle(
            "WarnBox", parent=base["Normal"], fontSize=9, leading=12,
            textColor=colors.HexColor("#92400e"),
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
    color = _RISK_COLORS.get(report.risk_level, _TEXT_MUTED)
    label = _RISK_LABELS.get(report.risk_level, "—")
    score_para = Paragraph(
        f'<font color="{color.hexval()}">{report.score}</font>'
        f'<font size="20" color="#94a3b8">/100</font>',
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
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
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

    # Trust signals nuevos del seller (Quick win 3)
    if listing.seller_account_age_days:
        years = listing.seller_account_age_days // 365
        rows.append(["Vendedor: tiempo en plataforma", f"~{years} años" if years > 0 else f"{listing.seller_account_age_days} días"])
    if listing.seller_sales_count is not None:
        rows.append(["Vendedor: ventas concretadas", f"{listing.seller_sales_count:,}"])
    if listing.seller_reputation:
        rep_text = {"green": "✓ Buena", "yellow": "⚠ Irregular", "red": "✗ Mala"}.get(
            listing.seller_reputation, listing.seller_reputation,
        )
        rows.append(["Vendedor: reputación ML", rep_text])

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


def _vin_check_block(report: Report, styles: dict) -> list:
    """VIN check con decoder local + NHTSA enrichment (Quick win 1)."""
    if not report.vin_check:
        return []
    vc = report.vin_check
    d = vc.decoded
    rows = [
        ["VIN escaneado", d.vin or "—"],
        ["Marca decoded local", d.manufacturer or "—"],
        ["Año decoded local", str(d.year) if d.year else "—"],
        ["País fabricación (WMI)", d.country or "—"],
        ["¿Coincide con anuncio?", "✓ Sí" if vc.matches_listing else "✗ NO COINCIDE"],
    ]

    # NHTSA enrichment (cuando viene)
    if d.nhtsa_found:
        rows.append(["", ""])  # separador visual
        rows.append(["NHTSA — fabricante oficial", ""])
        rows.append(["  Make oficial", _safe(d.nhtsa_make) or "—"])
        rows.append(["  Model oficial", _safe(d.nhtsa_model) or "—"])
        rows.append(["  Año modelo", str(d.nhtsa_model_year) if d.nhtsa_model_year else "—"])
        rows.append(["  Carrocería", _safe(d.nhtsa_body_class) or "—"])
        rows.append(["  Trim", _safe(d.nhtsa_trim) or "—"])
        rows.append(["  Cilindros", str(d.nhtsa_engine_cylinders) if d.nhtsa_engine_cylinders else "—"])
        rows.append(["  Desplazamiento (L)", str(d.nhtsa_engine_displacement_l) if d.nhtsa_engine_displacement_l else "—"])
        rows.append(["  Combustible", _safe(d.nhtsa_fuel_type) or "—"])
        rows.append(["  Transmisión", _safe(d.nhtsa_transmission) or "—"])
        rows.append(["  Tracción", _safe(d.nhtsa_drive_type) or "—"])
        rows.append(["  Puertas", str(d.nhtsa_doors) if d.nhtsa_doors else "—"])
        plant = ", ".join(filter(None, [d.nhtsa_plant_city, d.nhtsa_plant_country]))
        if plant:
            rows.append(["  Planta", _safe(plant)])

    out = [
        Paragraph("Verificación VIN físico", styles["section"]),
        _kv_table(rows),
    ]

    # Alertas del VIN check (criticas para anti-clonado)
    if vc.alerts:
        out.append(Spacer(1, 4))
        out.append(Paragraph("<b>Alertas del VIN:</b>", styles["body"]))
        for a in vc.alerts[:5]:
            sev = a.severity.upper()
            sev_color = {"HIGH": "#dc2626", "MEDIUM": "#d97706", "LOW": "#475569"}.get(sev, "#475569")
            out.append(Paragraph(
                f'<font color="{sev_color}"><b>{sev}</b></font>: {_safe(a.message)}',
                styles["body"],
            ))
    return out


def _invoice_block(report: Report, styles: dict) -> list:
    """Factura del auto + SAT verification (Fase A+B+C)."""
    inv = getattr(report, "invoice", None)
    if not inv:
        return []

    rows = [
        ["Folio declarado", _safe(inv.invoice_number) or "—"],
        ["UUID CFDI", _safe(inv.folio_fiscal_uuid) or "—"],
    ]
    if inv.rfc_emisor:
        rows.append(["RFC Emisor", _safe(inv.rfc_emisor)])
    if inv.rfc_receptor:
        rows.append(["RFC Receptor", _safe(inv.rfc_receptor)])
    if inv.fecha:
        rows.append(["Fecha factura", inv.fecha.strftime("%Y-%m-%d") if inv.fecha else "—"])
    if inv.total_mxn:
        rows.append(["Total factura", f"${inv.total_mxn:,.2f} MXN"])

    # SAT verify status (Fase C)
    if inv.sat_status:
        sat_text = {
            "vigente": "✓ Vigente — confirmada por SAT",
            "cancelado": "🚨 CANCELADA por el SAT",
            "no_encontrado": "🚨 NO EXISTE en SAT (factura falsa)",
        }.get(inv.sat_status, inv.sat_status)
        rows.append(["Estado SAT", _safe(sat_text)])
        if inv.sat_checked_at:
            rows.append(["SAT verificado", inv.sat_checked_at.strftime("%Y-%m-%d %H:%M UTC")])
    else:
        rows.append(["Estado SAT", "Pendiente verificar (faltan datos para consulta)"])

    out = [
        Paragraph("Factura del auto (CFDI)", styles["section"]),
        _kv_table(rows),
    ]
    if inv.notes:
        out.append(Spacer(1, 4))
        out.append(_warning_box(inv.notes, styles))
    return out


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
    delta_color = colors.HexColor("#16a34a")
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


def _cross_listings_block(report: Report, styles: dict) -> list:
    """Cross-listings de otros marketplaces (Vivanuncios, Seminuevos, etc.)."""
    cls = getattr(report, "cross_listings", []) or []
    if not cls:
        return []

    out = [
        Paragraph("Otros marketplaces — el mismo modelo", styles["section"]),
        Paragraph(
            f"Encontramos {len(cls)} listing(s) similares en otros sitios MX. "
            "Compara precios y verifica si el vendedor está cross-posteando.",
            styles["muted"],
        ),
        Spacer(1, 4),
    ]
    rows = [["Sitio", "Título", "Precio", "Ubicación"]]
    for cl in cls[:10]:
        price_str = (
            f"${cl.price_mxn:,.0f}" if cl.price_mxn else "—"
        )
        rows.append([
            cl.marketplace.replace("_", " "),
            _truncate(cl.title, 50),
            price_str,
            _truncate(cl.location, 25) if cl.location else "—",
        ])
    table = Table(rows, colWidths=[1.1 * inch, 3.4 * inch, 1.1 * inch, 1.7 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, _BORDER_LIGHT),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    out.append(table)
    return out


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
    # EXIF findings (Quick win 2)
    exif = getattr(report, "exif_findings", []) or []
    if exif:
        out += _findings_subsection(
            "Forensia EXIF (metadata de fotos)", exif, styles,
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
            "HIGH": "#dc2626", "MEDIUM": "#d97706", "LOW": "#475569",
        }.get(sev, "#475569")
        rows.append([
            Paragraph(f'<font color="{sev_color}"><b>{sev}</b></font>',
                      styles["body"]),
            Paragraph(_safe(get_text(f)), styles["body"]),
        ])
    table = Table(rows, colWidths=[0.9 * inch, 6.4 * inch])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, _BORDER_LIGHT),
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


def _gob_mx_links_block(report: Report, styles: dict) -> list:
    """Links a portales gob.mx oficiales para verificación manual."""
    links = getattr(report, "consultation_links", []) or []
    if not links:
        return []

    out = [
        Paragraph("Consultas oficiales gob.mx", styles["section"]),
        Paragraph(
            "Portales oficiales para que verifiques tú mismo. "
            "Las marcadas con ✓ aplican a este auto según su ubicación.",
            styles["muted"],
        ),
        Spacer(1, 4),
    ]
    for link in links[:8]:
        applicable_mark = "✓ " if link.applicable else "  "
        scope = f" [{link.state_scope}]" if link.state_scope else ""
        out.append(Paragraph(
            f'{applicable_mark}<b>{_safe(link.name)}</b>{scope}<br/>'
            f'<font size="8" color="{_TEXT_SECONDARY.hexval()}">{_safe(link.url)}</font>',
            styles["body"],
        ))
        out.append(Spacer(1, 2))
    return out


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
            "Verificarro v0.2 · Reporte informativo, no sustituye revisión "
            "mecánica profesional · Hecho en México · verificarro.mx",
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
    table = Table(formatted, colWidths=[1.8 * inch, 5.5 * inch])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, _BORDER_LIGHT),
    ]))
    return table


def _warning_box(text: str, styles: dict) -> Table:
    """Caja con borde + bg amarillo para texto de advertencia accionable."""
    para = Paragraph(_safe(text), styles["warn_box"])
    table = Table([[para]], colWidths=[7.3 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fef3c7")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#f59e0b")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
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


def _truncate(text: str, max_len: int) -> str:
    if not text:
        return ""
    s = str(text)
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"
