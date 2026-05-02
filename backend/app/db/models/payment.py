"""Tabla `payments` — registro de cada intento de pago vía Mercado Pago.

Flow de estados:
  pending → paid (webhook MP confirma) → refunded (raro)
  pending → failed (timeout, cancelación)

`mp_preference_id` es el ID de la Preference que crea el checkout.
`mp_payment_id` se popula cuando el webhook llega con el pago real.
`external_reference` es nuestro UUID local — lo enviamos a MP como
identificador opaco para que en el webhook podamos linkar.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.db.types import EncryptedString


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Detalles del cobro
    amount_mxn: Mapped[float] = mapped_column(Float, nullable=False)
    tier: Mapped[str] = mapped_column(String(16), nullable=False, default="basic")
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, native_enum=False, length=16),
        nullable=False, default=PaymentStatus.PENDING,
    )

    # Mercado Pago IDs
    mp_preference_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    mp_payment_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    mp_external_reference: Mapped[str] = mapped_column(
        String(36), nullable=False, unique=True
    )

    # Datos del listing que se va a analizar (snapshot del momento del checkout)
    listing_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    # MOD-032: PII encriptada at-rest con Fernet. Length 200 cubre el
    # plaintext típico (16 chars plate / 24 VIN / 100 char emails)
    # con el overhead de Fernet (~4× plaintext: IV + HMAC + base64).
    plate: Mapped[str | None] = mapped_column(EncryptedString(200), nullable=True)
    vin: Mapped[str | None] = mapped_column(EncryptedString(200), nullable=True)
    # Número de factura del auto (folio o UUID CFDI). Opcional al checkout.
    # Si se provee, el reporte incluye instrucciones explícitas para que el
    # comprador pida ver la factura física con ese folio. Fase B agregará
    # OCR + cross-validation; Fase C verificación SAT.
    invoice_number: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    # Email del comprador — encriptado at-rest. Si Postgres se filtra,
    # los emails NO quedan expuestos.
    payer_email: Mapped[str | None] = mapped_column(
        EncryptedString(500), nullable=True
    )

    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<Payment id={self.id} status={self.status.value} "
            f"amount=${self.amount_mxn} MXN>"
        )
