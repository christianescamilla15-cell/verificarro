"""Regla operativa: producción no arranca con secretos de ejemplo (H-3).

`Settings` aborta el arranque con ENV=production si JWT_SECRET es el
valor de desarrollo (público en el repo) o mide < 32 caracteres, si falta
FERNET_KEY (cifrado de PII) o si falta MP_WEBHOOK_SECRET (el webhook de
pagos aceptaría firmas sin verificar). Fuera de producción no exige nada.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import _JWT_SECRET_PLACEHOLDER, Settings

_OK = {
    "ENV": "production",
    "JWT_SECRET": "x" * 64,
    "FERNET_KEY": "clave-fernet-de-prueba",
    "MP_WEBHOOK_SECRET": "secreto-webhook-de-prueba",
}


def _settings(monkeypatch, **cambios: str) -> Settings:
    for clave in ("ENV", "JWT_SECRET", "FERNET_KEY", "MP_WEBHOOK_SECRET"):
        monkeypatch.delenv(clave, raising=False)
    for clave, valor in {**_OK, **cambios}.items():
        monkeypatch.setenv(clave, valor)
    return Settings(_env_file=None)


def test_production_with_real_secrets_boots(monkeypatch) -> None:
    assert _settings(monkeypatch).is_production is True


@pytest.mark.parametrize(
    ("clave", "valor", "mensaje"),
    [
        ("JWT_SECRET", _JWT_SECRET_PLACEHOLDER, "placeholder"),
        ("JWT_SECRET", "corto-de-31-caracteres-xxxxxxxx", "demasiado corto"),
        ("JWT_SECRET", "", "ausente"),
        ("FERNET_KEY", "", "FERNET_KEY"),
        ("MP_WEBHOOK_SECRET", "", "MP_WEBHOOK_SECRET"),
    ],
)
def test_production_rejects_missing_or_placeholder_secrets(
    monkeypatch, clave: str, valor: str, mensaje: str,
) -> None:
    with pytest.raises(ValidationError, match=mensaje):
        _settings(monkeypatch, **{clave: valor})


def test_non_production_does_not_require_secrets(monkeypatch) -> None:
    s = _settings(
        monkeypatch, ENV="development", JWT_SECRET=_JWT_SECRET_PLACEHOLDER,
        FERNET_KEY="", MP_WEBHOOK_SECRET="",
    )
    assert s.is_production is False
