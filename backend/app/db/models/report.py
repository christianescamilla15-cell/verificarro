"""Tabla `reports` — cache de reportes generados por el pipeline.

El reporte completo se serializa como JSON en `report_json` (no se
normaliza en columnas porque la estructura de `Report` evoluciona — D5
agregó `photo_findings`, D6 agregó text findings, D7 agregó `vin_check`).
Mantener el JSON entero permite migraciones de schema sin tocar la DB.

Las columnas dedicadas son las que se usan para queries / analytics:
- `score`, `risk_level` para ranking
- `make`, `model`, `year` para búsqueda
- `source_url` para deduplicación (mismo URL → mismo reporte cacheado
  por 24h)
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ReportRecord(Base, TimestampMixin):
    """Reporte generado por `run_pipeline`. Cacheado 24h por URL."""

    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Identificación del listing — si dos requests piden la misma URL
    # dentro de 24h, devolvemos el reporte cacheado.
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    listing_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )

    # Datos rápidos para queries / analytics
    make: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_mxn: Mapped[float | None] = mapped_column(nullable=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)

    # JSON completo del Report (Pydantic .model_dump(mode="json"))
    report_json: Mapped[dict] = mapped_column(JSON, nullable=False)

    # Cache expiration (24h por default, los precios y REPUVE cambian)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # Vinculación con Payment cuando el reporte fue pagado
    payment_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("payments.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_reports_listing_hash_expires", "listing_hash", "expires_at"),
        Index("ix_reports_user_created", "user_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Report id={self.id} score={self.score} risk={self.risk_level}>"
