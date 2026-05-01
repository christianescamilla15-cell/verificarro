"""photo_hashes table for pHash-based duplicate detection

Revision ID: 9b3e7f5a2c1d
Revises: 7a2c4b8e1f0d
Create Date: 2026-05-01 17:00:00.000000

Almacena perceptual hashes de fotos analizadas. Cada reporte generado
agrega N rows (1 por foto). Antes de cada reporte nuevo, buscamos
matches por Hamming distance para detectar fotos recicladas.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9b3e7f5a2c1d'
down_revision: Union[str, None] = '7a2c4b8e1f0d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'photo_hashes',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('listing_hash', sa.String(length=64), nullable=False),
        sa.Column('photo_index', sa.Integer(), nullable=False),
        sa.Column('phash', sa.BigInteger(), nullable=False),
        sa.Column('source_url', sa.String(length=2048), nullable=True),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_photo_hashes_phash', 'photo_hashes', ['phash'], unique=False,
    )
    op.create_index(
        'ix_photo_hashes_listing_hash', 'photo_hashes',
        ['listing_hash'], unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_photo_hashes_listing_hash', table_name='photo_hashes')
    op.drop_index('ix_photo_hashes_phash', table_name='photo_hashes')
    op.drop_table('photo_hashes')
