"""Rate limiter compartido (slowapi) para defender endpoints públicos.

## Por qué (MOD-004)

Sin rate limit, los endpoints públicos son vector de:

- **Email-bombing**: `/api/auth/request-link` mandando magic links a
  emails ajenos.
- **Drain de Anthropic**: `/api/scan/auto`, `/api/scan/plate`,
  `/api/analyze` cada uno consume crédito Claude (~$0.005-0.01 USD).
  Un atacante con script puede vaciar saldo en minutos.
- **MP API quota**: `/api/payments/webhook` puede ser DoS amplificado
  haciéndonos hacer lookups innecesarios contra MP.
- **PDF generation DoS**: `/api/analyze/pdf` corre reportlab que
  consume CPU + RAM.

## Política de límites

Por IP (`get_remote_address`):

| Endpoint | Límite | Razón |
|---|---|---|
| `/api/auth/request-link` | 5/min | Mail bombing prevention |
| `/api/auth/verify` | 10/min | Multiple attempts OK pero bot abuse no |
| `/api/scan/*` | 30/min | Scan rate normal humano <1/min, 30 cubre devs |
| `/api/analyze` | 10/min | Pipeline pesado |
| `/api/analyze/pdf` | 10/min | reportlab CPU |
| `/api/payments/checkout` | 10/min | UX OK, abuse improbable |
| `/api/payments/subscribe` | 10/min | Igual |
| `/api/payments/webhook` | 60/min | MP burst tolerance |

## Storage

In-memory por default (slowapi `MemoryStorage`). Suficiente para 1
worker Render Starter. Cuando crezcamos a multi-worker, swap a Redis
storage (`storage_uri="redis://..."`).

## Tests

Los tests existentes hacen <5 requests por test al mismo endpoint, no
hitean estos límites. Hay tests específicos en `test_rate_limit.py`
que sí abusan a propósito para validar los 429.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

# Singleton — slowapi recomienda crear una vez y reutilizar.
#
# `headers_enabled=False` porque inyectar X-RateLimit-* headers requiere
# que cada endpoint declare `response: Response` parameter, lo cual
# inflaría 9 firmas. Los clientes pueden manejar 429 sin esos headers
# (el body del 429 incluye `retry_after_seconds`).
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    headers_enabled=False,
)
