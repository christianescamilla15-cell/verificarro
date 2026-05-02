"""Encriptación de PII at-rest (MOD-032).

Usa Fernet (cryptography) para encriptar campos sensibles antes de
persistirlos en DB. Detalles del algoritmo:

- AES-128 en modo CBC con PKCS7 padding
- HMAC-SHA256 para autenticación (previene tampering)
- IV random de 128 bits por mensaje
- Output url-safe base64 — almacenable en columnas `String`

## Por qué

Auditoría 2026-05-01 (Security agent, severidad MEDIA score 6/25):
`Payment.payer_email`, `Payment.plate`, `Payment.vin` se almacenaban en
plaintext. En caso de filtración de Postgres (e.g. backup leak,
SQLi en algún query futuro, breach de Render), todo queda expuesto.
LFPDPPP MX no obliga encriptación at-rest pero es estándar para PII.

## Key management

- `FERNET_KEY` env var (32 bytes url-safe base64, ej. el output de
  `Fernet.generate_key()`).
- Si vacío en dev, fallback determinístico desde JWT_SECRET (suficiente
  para tests y desarrollo local, NO production).
- En producción, generar con:

      python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

  y setear como `FERNET_KEY` en Render.

## Rotación

Si la key se compromete o expira, el plan de rotación es:

1. Generar nueva key.
2. Setear ambas como `FERNET_KEY` (nueva) y `FERNET_KEY_OLD` (vieja).
3. Run migration que decripta con OLD y re-encripta con NEW.
4. Eliminar `FERNET_KEY_OLD`.

Pendiente: implementar el OLD fallback aquí cuando hagamos primera
rotación (no urgente para MVP).

## Backward compat (legacy plain data)

`decrypt_pii_safe()` detecta si el value parece un Fernet token
(prefijo `gAAAAA`) y solo entonces intenta decrypt. Si es plain,
devuelve as-is. Esto permite migración gradual sin downtime — datos
viejos no encriptados siguen leyéndose mientras la migración corre.
"""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

logger = logging.getLogger(__name__)

_FERNET_TOKEN_PREFIX = "gAAAAA"  # all valid Fernet tokens start with this


def _get_fernet() -> Fernet:
    """Lazy singleton del Fernet instance.

    Si `FERNET_KEY` está set, lo usa directo. Si vacío, deriva una key
    determinística del `JWT_SECRET` (dev/MVP fallback). El warning ayuda
    a no olvidar setear el env var en producción.
    """
    settings = get_settings()
    key = settings.fernet_key.strip()
    if not key:
        # Fallback dev: SHA-256 del JWT_SECRET → 32 bytes → base64 url-safe
        digest = hashlib.sha256(settings.jwt_secret.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest).decode("ascii")
        logger.warning(
            "FERNET_KEY no configurado — usando derivación determinística "
            "de JWT_SECRET. NO usar en producción; rotar JWT_SECRET "
            "invalidaría toda la PII encriptada.",
        )
    return Fernet(key.encode("utf-8") if isinstance(key, str) else key)


def encrypt_pii(value: str | None) -> str | None:
    """Encripta un string. None → None (no encriptar nulos).

    Idempotent NO — encriptar dos veces produce token distinto cada vez
    (Fernet usa IV random). Si el caller pasa un token ya encriptado,
    lo encripta de nuevo (double-encrypt). Por eso los TypeDecorator
    de SQLAlchemy aplican esto solo en el bind path (write), nunca en
    el result path.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    f = _get_fernet()
    token = f.encrypt(value.encode("utf-8"))
    return token.decode("ascii")


def decrypt_pii_safe(value: str | None) -> str | None:
    """Desencripta un Fernet token. Si el value es plain (legacy data
    pre-MOD-032), devuelve as-is sin error.

    Esto permite migración gradual: datos viejos sin encriptar siguen
    leyéndose mientras los nuevos se encriptan. Después de la
    migración Alembic completa, todos los rows están encriptados y
    este safe-mode no se ejerce más.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    if not value.startswith(_FERNET_TOKEN_PREFIX):
        # Probablemente es legacy plaintext, no token Fernet
        return value
    try:
        f = _get_fernet()
        return f.decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        # Token corrupted o key cambió. Devolvemos as-is con warning —
        # mejor que tumbar la app por un row corrupto.
        logger.warning("Fernet decrypt falló para token (key cambió?)")
        return value
