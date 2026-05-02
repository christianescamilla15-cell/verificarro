"""Tests SSRF protection en photo_fetcher (MOD-003).

El check `_check_url_safe` debe rechazar:
- IPs literales privadas / loopback / link-local (incluye GCP metadata
  169.254.169.254)
- Schemes no http(s) (file://, gopher://, ftp://...)
- URLs malformadas o sin hostname
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.photo_fetcher import _check_url_safe, fetch_photos


@pytest.mark.parametrize(
    ("url", "reason_substr"),
    [
        # Loopback
        ("http://127.0.0.1/", "no pública"),
        ("http://127.1.2.3:5432/", "no pública"),
        ("http://[::1]/", "no pública"),
        # Private RFC 1918
        ("http://10.0.0.1/", "no pública"),
        ("http://172.16.0.5/api", "no pública"),
        ("http://192.168.1.1/", "no pública"),
        # Link-local (incluye GCP/AWS metadata)
        ("http://169.254.169.254/computeMetadata/v1/", "no pública"),
        ("http://169.254.0.1/", "no pública"),
        # Reserved / multicast
        ("http://0.0.0.0/", "no pública"),
        ("http://224.0.0.1/", "no pública"),
        # Schemes no permitidos
        ("file:///etc/passwd", "scheme"),
        ("gopher://example.com/", "scheme"),
        ("ftp://example.com/", "scheme"),
        ("javascript:alert(1)", "scheme"),
        # Malformadas
        ("", "vacía"),
        ("not-a-url", "scheme"),
        ("http://", "hostname"),
    ],
)
def test_check_url_safe_rejects_unsafe(url: str, reason_substr: str) -> None:
    allowed, reason = _check_url_safe(url)
    assert allowed is False, f"esperaba rechazar {url!r} pero pasó"
    assert reason_substr in reason, (
        f"para {url!r} esperaba reason con {reason_substr!r}, got {reason!r}"
    )


def test_check_url_safe_accepts_public_ip() -> None:
    """8.8.8.8 (Google DNS) es IP literal pública — debe pasar el check."""
    allowed, reason = _check_url_safe("https://8.8.8.8/")
    assert allowed is True, f"reason: {reason}"


def test_check_url_safe_accepts_https_to_real_domain() -> None:
    """Un dominio público resuelve a IPs públicas — pasa.

    Usamos `example.com` que es estable y siempre resuelve a IPs
    routeables públicas (no privadas).
    """
    allowed, reason = _check_url_safe("https://example.com/photo.jpg")
    assert allowed is True, f"reason: {reason}"


def test_fetch_photos_skips_unsafe_urls() -> None:
    """fetch_photos devuelve None para URLs SSRF, sin hacer la red call."""
    urls = [
        "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/",
        "http://localhost:5432/",
        "file:///etc/passwd",
    ]
    result = asyncio.get_event_loop().run_until_complete(fetch_photos(urls))
    assert result == [None, None, None]
    # Mantiene orden y largo
    assert len(result) == len(urls)


def test_fetch_photos_empty_list_returns_empty() -> None:
    result = asyncio.get_event_loop().run_until_complete(fetch_photos([]))
    assert result == []
