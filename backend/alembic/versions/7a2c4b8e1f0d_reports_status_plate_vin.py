"""reports.status + reports.plate + reports.vin

Revision ID: 7a2c4b8e1f0d
Revises: 3fc452813bf2
Create Date: 2026-05-01 12:00:00.000000

Scan-first rework (2026-05-01):
- `status` distingue `preview` (gratis, score+REPUVE básico) vs
  `unlocked` (full pipeline tras pago confirmado).
- `plate` y `vin` se snapshot al momento del scan para que el unlock
  pueda re-correr el pipeline aunque el Payment se haya borrado.
- Filas existentes (creadas por el flow anterior) se marcan como
  `unlocked` porque el flow viejo solo creaba reportes después de pago.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7a2c4b8e1f0d'
down_revision: Union[str, None] = '3fc452813bf2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'reports',
        sa.Column(
            'status',
            sa.Enum('PREVIEW', 'UNLOCKED', name='reportstatus',
                    native_enum=False, length=16),
            nullable=False,
            server_default='UNLOCKED',
        ),
    )
    op.add_column(
        'reports',
        sa.Column('plate', sa.String(length=16), nullable=True),
    )
    op.add_column(
        'reports',
        sa.Column('vin', sa.String(length=24), nullable=True),
    )
    op.create_index('ix_reports_status', 'reports', ['status'], unique=False)

    # Drop server_default ahora que las filas existentes ya tienen valor.
    # Las nuevas filas reciben default desde el ORM (PREVIEW).
    with op.batch_alter_table('reports') as batch_op:
        batch_op.alter_column('status', server_default=None)


def downgrade() -> None:
    op.drop_index('ix_reports_status', table_name='reports')
    op.drop_column('reports', 'vin')
    op.drop_column('reports', 'plate')
    op.drop_column('reports', 'status')
