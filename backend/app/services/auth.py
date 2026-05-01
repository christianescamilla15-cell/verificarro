"""Auth helpers: magic link tokens + JWT sessions.

## Magic link flow

1. User pide login con email → generamos un token aleatorio de 32 bytes,
   guardamos su HMAC-SHA256 en `User.magic_link_hash` con
   `magic_link_expires_at` (15 min). Mandamos el TOKEN PLANO al email
   en un link `{MAGIC_LINK_BASE_URL}?token=<token>&email=<email>`.
2. User clic → frontend manda token + email a `/api/auth/verify`.
3. Backend re-hashea token + busca `User.magic_link_hash`. Si coincide
   y no expiró → genera JWT de sesión (30 días) y lo retorna.

## Por qué hash y no plaintext

Si la DB se filtra, los hashes no son útiles para el atacante (no
puede generar links válidos sin el token plano original). El TTL de
15min limita la ventana aún si se intercepta.

## JWT session

Standard HS256 firmado con `JWT_SECRET`. Claims: `sub` (user_id),
`iat`, `exp`. El frontend lo manda en `Authorization: Bearer <jwt>`.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import TypedDict

import jwt

from app.config import get_settings


class MagicLink(TypedDict):
    token: str         # plain token, va al email
    token_hash: str    # HMAC-SHA256 del token, se guarda en DB
    expires_at: datetime


def generate_magic_link() -> MagicLink:
    """Genera un magic link nuevo. Plain token al email + hash a DB."""
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    expires_at = datetime.now(UTC) + timedelta(
        minutes=settings.magic_link_ttl_minutes
    )
    return MagicLink(token=token, token_hash=token_hash, expires_at=expires_at)


def verify_magic_link(plain_token: str, stored_hash: str) -> bool:
    """Compara token plano contra hash almacenado en constant time."""
    if not plain_token or not stored_hash:
        return False
    return hmac.compare_digest(_hash_token(plain_token), stored_hash)


def build_magic_link_url(token: str, email: str) -> str:
    """Construye el URL completo que va al cuerpo del email."""
    settings = get_settings()
    from urllib.parse import urlencode

    qs = urlencode({"token": token, "email": email})
    base = settings.magic_link_base_url
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}{qs}"


# ---------------------------------------------------------------------------
# JWT session


def create_session_token(user_id: str) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int(
            (now + timedelta(days=settings.session_ttl_days)).timestamp()
        ),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_session_token(token: str) -> str | None:
    """Devuelve `user_id` si el token es válido, None si expiró/inválido."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
    sub = payload.get("sub")
    return str(sub) if sub else None


# ---------------------------------------------------------------------------
# Internal


def _hash_token(token: str) -> str:
    """HMAC-SHA256(token, JWT_SECRET) → hex.

    Usamos HMAC en lugar de hash directo para que un atacante con la DB
    no pueda generar tablas rainbow ni adivinar tokens cortos sin
    conocer el secret.
    """
    settings = get_settings()
    digest = hmac.new(
        settings.jwt_secret.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    )
    return digest.hexdigest()
