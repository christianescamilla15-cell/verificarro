"""Genera reportes seed para campañas orgánicas de Reddit.

Para cada URL de ML Motors recibida:
1. Corre el pipeline completo (`run_pipeline`)
2. Guarda `output/<slug>/report.json`
3. Genera `output/<slug>/report.pdf`
4. Renderiza el draft de Reddit thread con tono mexicano según el
   risk_level (green / yellow / red)

Uso:
    cd backend
    source .venv/Scripts/activate
    python scripts/seed_reports.py URL1 URL2 URL3 ...

    # O con un archivo de URLs (una por línea):
    python scripts/seed_reports.py --file ../seeds/urls.txt

Tip: si NO hay ANTHROPIC_API_KEY exportada, los `photo_findings`
quedarán vacíos (graceful degradation), pero el resto del reporte
funciona.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

# Permitir `from app...` cuando se corre desde scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.report import AnalyzeRequest, Report, RiskLevel, Source
from app.services.pdf_report import generate_pdf
from app.services.pipeline import run_pipeline


SEED_DIR = Path(__file__).resolve().parent.parent.parent / "seeds"
OUTPUT_DIR = SEED_DIR / "output"
TEMPLATES_DIR = SEED_DIR / "templates"


def slugify(url: str) -> str:
    """Extrae un slug único del URL ML para nombrar el folder de output."""
    m = re.search(r"MLM-?(\d+)-([a-z0-9-]+)", url, re.I)
    if not m:
        return re.sub(r"[^a-z0-9]+", "-", url.lower())[:60]
    return f"MLM{m.group(1)}-{m.group(2)}"[:80]


async def process_url(url: str) -> Path | None:
    """Corre el pipeline contra `url` y persiste assets. Devuelve dir o None."""
    print(f"\n{'=' * 70}")
    print(f"  Procesando: {url}")
    print("=" * 70)

    try:
        report = await run_pipeline(
            AnalyzeRequest(
                url=url,  # type: ignore[arg-type]
                source=Source.MERCADOLIBRE,
            )
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  ❌ Pipeline falló: {exc}", file=sys.stderr)
        return None

    slug = slugify(url)
    out_dir = OUTPUT_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    # JSON
    json_path = out_dir / "report.json"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # PDF
    pdf_path = out_dir / "report.pdf"
    try:
        pdf_path.write_bytes(generate_pdf(report))
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠️ PDF gen falló: {exc}", file=sys.stderr)

    # Reddit draft
    thread_path = out_dir / "reddit_thread.md"
    thread_path.write_text(
        render_reddit_thread(report), encoding="utf-8"
    )

    print(
        f"  ✓ {report.listing.make} {report.listing.model} {report.listing.year}"
        f" — score {report.score}/{report.risk_level.value}"
    )
    print(f"  → {out_dir.relative_to(SEED_DIR.parent)}/")
    return out_dir


def render_reddit_thread(report: Report) -> str:
    """Selecciona template según risk_level y rellena placeholders."""
    risk = report.risk_level.value
    template_path = TEMPLATES_DIR / f"{risk}.md"
    if not template_path.exists():
        template_path = TEMPLATES_DIR / "yellow.md"
    template = template_path.read_text(encoding="utf-8")

    listing = report.listing
    price = report.price

    # Construye placeholders
    title_line = _build_title_line(report)
    photo_summary = _photo_summary(report)
    repuve_line = _repuve_line(report)
    price_line = _price_line(price)
    flags_block = _flags_block(report)
    top_alert_count = _top_alert_count(report)

    return template.format(
        title=title_line,
        year=listing.year or "—",
        make=listing.make or "Auto",
        model=listing.model or "",
        price_mxn=listing.price_mxn or 0,
        kilometers=listing.kilometers or 0,
        location=listing.location or "—",
        source_url=listing.source_url or "(URL no disponible)",
        score=report.score,
        fair_price_mxn=price.fair_price_mxn or 0,
        delta_pct=price.delta_pct or 0,
        photo_summary=photo_summary,
        repuve_line=repuve_line,
        price_line=price_line,
        flags_block=flags_block,
        top_alert_count=top_alert_count,
    )


def _build_title_line(report: Report) -> str:
    listing = report.listing
    if report.risk_level == RiskLevel.GREEN:
        return (
            f"Limpio: pasé este {listing.year} {listing.make} {listing.model} "
            "por Verificarro y no encontró banderas"
        )
    if report.risk_level == RiskLevel.YELLOW:
        return (
            f"Dudas: este {listing.year} {listing.make} {listing.model} "
            f"tiene banderas amarillas, ¿le entrarían?"
        )
    return (
        f"🚨 OJO: este {listing.year} {listing.make} {listing.model} "
        "en Marketplace tiene banderas graves"
    )


def _photo_summary(report: Report) -> str:
    if not report.photo_findings:
        return "0 problemas detectados en las fotos"
    counts = {}
    for f in report.photo_findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    parts = []
    for sev in ("high", "medium", "low"):
        if sev in counts:
            parts.append(f"{counts[sev]} {sev}")
    return f"{len(report.photo_findings)} hallazgos ({', '.join(parts)})"


def _repuve_line(report: Report) -> str:
    r = report.repuve
    if r.is_stolen is False:
        return "- ✅ REPUVE: sin reportes de robo (consultado por placa)"
    if r.is_stolen is True:
        return "- 🚨 REPUVE: vehículo ROBADO"
    if r.raw_status == "captcha_required":
        return "- ⚠️ REPUVE: pendiente consulta manual (gob.mx pide reCaptcha)"
    return "- ℹ️ REPUVE: no consultado en este reporte"


def _price_line(price) -> str:
    if not price.fair_price_mxn:
        return "Precio: no hay comparables suficientes para estimar"
    delta = price.delta_pct or 0
    if delta < -20:
        return f"⚠️ Precio: {delta:+.1f}% por debajo del mercado — sospechosamente barato"
    if delta > 20:
        return f"⚠️ Precio: {delta:+.1f}% sobre el mercado — sobrepuesto"
    return f"✓ Precio: {delta:+.1f}% del mercado (~${price.fair_price_mxn:,.0f} MXN justo)"


def _flags_block(report: Report) -> str:
    """Listado de banderas para los templates yellow/red."""
    lines: list[str] = []

    if report.repuve.is_stolen is True:
        lines.append("- 🚨 REPUVE marca el vehículo como ROBADO")

    high_desc = [f for f in report.description_findings if f.severity == "high"]
    if high_desc:
        lines.append(
            f"- 🚨 {len(high_desc)} red flags graves en la descripción "
            f"({', '.join(set(f.flag for f in high_desc))})"
        )

    high_photo = [f for f in report.photo_findings if f.severity == "high"]
    if high_photo:
        lines.append(
            f"- 🚨 {len(high_photo)} hallazgos graves en fotos "
            f"({', '.join(set(f.issue for f in high_photo))})"
        )

    high_seller = [f for f in report.seller_findings if f.severity == "high"]
    if high_seller:
        lines.append(f"- 🚨 {len(high_seller)} banderas graves en el vendedor")

    price = report.price
    if price.delta_pct is not None and abs(price.delta_pct) > 20:
        if price.delta_pct < 0:
            lines.append(
                f"- ⚠️ Precio {price.delta_pct:+.1f}% bajo el mercado — "
                "sospechosamente barato"
            )
        else:
            lines.append(
                f"- ⚠️ Precio {price.delta_pct:+.1f}% sobre el mercado"
            )

    medium_desc = [f for f in report.description_findings if f.severity == "medium"]
    if medium_desc:
        lines.append(
            f"- ⚠️ {len(medium_desc)} hallazgos medios en descripción"
        )

    if not lines:
        lines.append("- (Sin red flags significativos detectados)")

    return "\n".join(lines)


def _top_alert_count(report: Report) -> int:
    """Cuántas alertas high (para el header del thread red)."""
    count = 0
    if report.repuve.is_stolen is True:
        count += 1
    count += sum(
        1 for f in report.description_findings if f.severity == "high"
    )
    count += sum(1 for f in report.photo_findings if f.severity == "high")
    count += sum(1 for f in report.seller_findings if f.severity == "high")
    return count


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "urls", nargs="*",
        help="URLs de ML Motors a procesar (auto.mercadolibre.com.mx/MLM-...)",
    )
    parser.add_argument(
        "--file", type=Path,
        help="Archivo con URLs (una por línea). Comentarios con #.",
    )
    args = parser.parse_args()

    urls: list[str] = list(args.urls)
    if args.file:
        for line in args.file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)

    if not urls:
        print("No URLs. Usa: seed_reports.py URL1 URL2 ... o --file urls.txt")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results: list[Path | None] = []
    for url in urls:
        results.append(await process_url(url))

    success = [r for r in results if r is not None]
    print(f"\n{'=' * 70}")
    print(f"  Reportes generados: {len(success)} / {len(urls)}")
    print(f"  Output: {OUTPUT_DIR.relative_to(SEED_DIR.parent)}/")
    print("=" * 70)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
