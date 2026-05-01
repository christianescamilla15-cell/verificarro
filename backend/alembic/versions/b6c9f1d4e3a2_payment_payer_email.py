"""payments.payer_email

Revision ID: b6c9f1d4e3a2
Revises: a4f8c2d6e9b1
Create Date: 2026-05-01 19:00:00.000000

Guarda el email del comprador al checkout para que el unlock pueda
mandarle el reporte completo + PDF adjunto vía SMTP/Resend.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b6c9f1d4e3a2'
down_revision: Union[str, None] = 'a4f8c2d6e9b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'payments',
        sa.Column('payer_email', sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('payments', 'payer_email')
