"""Pytest fixtures globales del backend.

## Rate limiter (MOD-004)

Por default, deshabilitamos el `slowapi.Limiter` en tests. Razón:
TestClient siempre hace requests desde la IP `testclient` así que
todos los tests del proyecto comparten el mismo bucket — los que
hacen 6+ requests al mismo endpoint en ráfaga (`test_request_link_*`,
`test_verify_*`) hitean el límite y devuelven 429 en lugar del
status real esperado.

Para los tests específicos que VALIDAN el rate limiter, usar el
fixture `enable_rate_limit` que vuelve a activarlo solo durante esa
prueba.
"""

from __future__ import annotations

import pytest

from app.rate_limit import limiter


@pytest.fixture(autouse=True)
def _disable_rate_limit_by_default():
    """Auto-fixture: deshabilita el limiter para cada test."""
    original = limiter.enabled
    limiter.enabled = False
    try:
        yield
    finally:
        limiter.enabled = original


@pytest.fixture
def enable_rate_limit():
    """Re-habilita el limiter solo dentro del test que lo solicite.

    Uso:

        def test_rate_limit_works(client, enable_rate_limit):
            for _ in range(6):
                res = client.post("/api/auth/request-link", ...)
            assert res.status_code == 429
    """
    limiter.reset()
    limiter.enabled = True
    try:
        yield
    finally:
        limiter.enabled = False
        limiter.reset()
