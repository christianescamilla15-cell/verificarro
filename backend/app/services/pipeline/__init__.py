"""Pipeline package: re-export de los entry points públicos.

Antes de MOD-014 esto era un archivo `pipeline.py` de 651 LOC. Ahora es
un package con responsabilidades separadas:

- `orchestrator.py` — entry points (`run_pipeline`, `run_preview_pipeline`)
- `steps.py` — step runners I/O paralelos (`_resolve_*`)
- `mappers.py` — Pydantic conversion (`_maybe_run_vin_check`,
  `_build_consultation_links_models`)
- `invoice.py` — InvoiceData + SAT verify + questions for seller
- `_preview.py` — preview-only helpers (placeholder, summary, run_repuve)

Public API se mantiene idéntica: `from app.services.pipeline import
run_pipeline, run_preview_pipeline` sigue funcionando porque están
re-exportadas aquí.
"""

from app.services.pipeline.orchestrator import (
    run_pipeline,
    run_preview_pipeline,
)

__all__ = ["run_pipeline", "run_preview_pipeline"]
