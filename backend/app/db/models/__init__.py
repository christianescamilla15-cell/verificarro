"""ORM models — importadas aquí para que Alembic las descubra
automáticamente cuando hace `--autogenerate`."""

from app.db.models.payment import Payment, PaymentStatus
from app.db.models.photo_hash import PhotoHash
from app.db.models.report import ReportRecord, ReportStatus
from app.db.models.user import User

__all__ = [
    "User", "ReportRecord", "ReportStatus", "Payment", "PaymentStatus",
    "PhotoHash",
]
