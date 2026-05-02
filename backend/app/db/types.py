"""SQLAlchemy custom types compartidos.

`EncryptedString` (MOD-032): encripta on-write, desencripta on-read,
transparente para el ORM. La columna sigue siendo `String` en DB
pero el caller ve el valor en plaintext.

Uso:

    from app.db.types import EncryptedString

    payer_email: Mapped[str | None] = mapped_column(
        EncryptedString(), nullable=True
    )

El `length` del String que envuelve es 4× el plaintext máximo
(Fernet token es ~3-4× más largo que el plaintext gracias a IV +
HMAC + base64). Si el plaintext típico es <100 chars, `EncryptedString(500)`
es seguro.
"""

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

from app.services.crypto import decrypt_pii_safe, encrypt_pii


class EncryptedString(TypeDecorator):
    """String que encripta con Fernet en bind (write), desencripta en
    result (read). Stored como String en DB.

    Backward compat: si el row tiene plaintext legacy (pre-MOD-032),
    `decrypt_pii_safe` detecta el missing prefix Fernet y devuelve
    as-is sin error.
    """
    impl = String
    cache_ok = True

    def __init__(self, length: int = 500, *args, **kwargs):
        super().__init__(length, *args, **kwargs)

    def process_bind_param(self, value, dialect):
        """Plaintext (caller) → token Fernet (DB). Llamado en INSERT/UPDATE."""
        return encrypt_pii(value)

    def process_result_value(self, value, dialect):
        """Token Fernet (DB) → plaintext (caller). Llamado en SELECT."""
        return decrypt_pii_safe(value)
