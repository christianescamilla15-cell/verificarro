"""payments.invoice_number

Revision ID: a4f8c2d6e9b1
Revises: 9b3e7f5a2c1d
Create Date: 2026-05-01 18:00:00.000000

Fase A: agrega invoice_number opcional al checkout. El usuario puede
declarar el folio de factura del auto al momento de pagar; el reporte
unlock incluye instrucciones explícitas para validarlo contra la
factura física del vendedor.

Fase B usará este folio para cross-validar via OCR de la factura.
Fase C lo verificará contra SAT (verificacfdi.sat.gob.mx).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a4f8c2d6e9b1'
down_revision: Union[str, None] = '9b3e7f5a2c1d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'payments',
        sa.Column('invoice_number', sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('payments', 'invoice_number')
