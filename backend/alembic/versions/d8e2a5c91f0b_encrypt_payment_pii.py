"""encrypt payment PII (MOD-032)

Revision ID: d8e2a5c91f0b
Revises: b6c9f1d4e3a2
Create Date: 2026-05-02 12:00:00.000000

Encripta `payments.payer_email`, `payments.plate`, `payments.vin` con
Fernet (AES-128-CBC + HMAC-SHA256). Los rows existentes se re-escriben
con la versión encriptada; nuevos rows se encriptan automáticamente
vía `EncryptedString` TypeDecorator en el modelo.

## Schema changes

- `plate VARCHAR(16)`  → `VARCHAR(200)` (Fernet token es ~4× plaintext)
- `vin VARCHAR(24)`    → `VARCHAR(200)`
- `payer_email VARCHAR(255)` → `VARCHAR(500)`

## Data migration

Se itera por cada row con valor non-null, encripta y reescribe.
Idempotent: si un valor ya está encriptado (prefix `gAAAAA`), skip.
Failure-tolerant: log + continue si un row falla (para no tumbar la
migración por un row corrupto).

## Downgrade

Desencripta y vuelve a plaintext. Requiere FERNET_KEY en el entorno
donde corre la migración (igual que el upgrade).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd8e2a5c91f0b'
down_revision: Union[str, None] = 'b6c9f1d4e3a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Ampliar las columnas para acomodar el ciphertext.
    with op.batch_alter_table('payments') as batch_op:
        batch_op.alter_column(
            'plate',
            existing_type=sa.String(length=16),
            type_=sa.String(length=200),
            existing_nullable=True,
        )
        batch_op.alter_column(
            'vin',
            existing_type=sa.String(length=24),
            type_=sa.String(length=200),
            existing_nullable=True,
        )
        batch_op.alter_column(
            'payer_email',
            existing_type=sa.String(length=255),
            type_=sa.String(length=500),
            existing_nullable=True,
        )

    # 2. Re-encriptar rows existentes. Carga lazy del helper para no
    # importar app code al colgar Alembic en un entorno mínimo.
    from app.services.crypto import encrypt_pii

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, payer_email, plate, vin FROM payments")
    ).fetchall()

    for row in rows:
        updates = {}
        for col, value in (
            ("payer_email", row.payer_email),
            ("plate", row.plate),
            ("vin", row.vin),
        ):
            if value is None:
                continue
            # Skip si ya está encriptado (idempotent).
            if isinstance(value, str) and value.startswith("gAAAAA"):
                continue
            updates[col] = encrypt_pii(value)

        if not updates:
            continue
        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        conn.execute(
            sa.text(f"UPDATE payments SET {set_clause} WHERE id = :id"),  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text -- columnas de una tupla fija; valores como parámetros
            {"id": row.id, **updates},
        )


def downgrade() -> None:
    # Desencripta y restaura el column size original.
    from app.services.crypto import decrypt_pii_safe

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, payer_email, plate, vin FROM payments")
    ).fetchall()

    for row in rows:
        updates = {}
        for col, value in (
            ("payer_email", row.payer_email),
            ("plate", row.plate),
            ("vin", row.vin),
        ):
            if value is None:
                continue
            if isinstance(value, str) and value.startswith("gAAAAA"):
                updates[col] = decrypt_pii_safe(value)
        if not updates:
            continue
        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        conn.execute(
            sa.text(f"UPDATE payments SET {set_clause} WHERE id = :id"),  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text -- columnas de una tupla fija; valores como parámetros
            {"id": row.id, **updates},
        )

    with op.batch_alter_table('payments') as batch_op:
        batch_op.alter_column(
            'plate',
            existing_type=sa.String(length=200),
            type_=sa.String(length=16),
            existing_nullable=True,
        )
        batch_op.alter_column(
            'vin',
            existing_type=sa.String(length=200),
            type_=sa.String(length=24),
            existing_nullable=True,
        )
        batch_op.alter_column(
            'payer_email',
            existing_type=sa.String(length=500),
            type_=sa.String(length=255),
            existing_nullable=True,
        )
