"""Tests del SAT CFDI verifier. Pure parser + mocked HTTP."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.services.sat_verify import parse_sat_response, verify_cfdi


def _vigente_xml() -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
        '<s:Body>'
        '<ConsultaResponse xmlns="http://tempuri.org/">'
        '<ConsultaResult xmlns:a="http://schemas.datacontract.org/2004/07/">'
        '<a:CodigoEstatus>S - Comprobante obtenido satisfactoriamente.</a:CodigoEstatus>'
        '<a:EsCancelable>Cancelable sin aceptación</a:EsCancelable>'
        '<a:Estado>Vigente</a:Estado>'
        '<a:EstatusCancelacion></a:EstatusCancelacion>'
        '</ConsultaResult>'
        '</ConsultaResponse>'
        '</s:Body>'
        '</s:Envelope>'
    )


def _cancelado_xml() -> str:
    return (
        '<a:Estado>Cancelado</a:Estado>'
        '<a:EsCancelable>No cancelable</a:EsCancelable>'
        '<a:EstatusCancelacion>Cancelado sin aceptación</a:EstatusCancelacion>'
        '<a:CodigoEstatus>S - Comprobante obtenido satisfactoriamente.</a:CodigoEstatus>'
    )


def _no_encontrado_xml() -> str:
    return (
        '<a:CodigoEstatus>N - 602 ... no se encuentra en los controles del SAT</a:CodigoEstatus>'
        '<a:Estado></a:Estado>'
    )


# ---------------------------------------------------------------------------
# parse_sat_response


def test_parse_vigente() -> None:
    out = parse_sat_response(_vigente_xml())
    assert out.queried is True
    assert out.status == "vigente"


def test_parse_cancelado() -> None:
    out = parse_sat_response(_cancelado_xml())
    assert out.status == "cancelado"
    assert out.estatus_cancelacion == "Cancelado sin aceptación"


def test_parse_no_encontrado() -> None:
    out = parse_sat_response(_no_encontrado_xml())
    assert out.status == "no_encontrado"


def test_parse_empty_response() -> None:
    out = parse_sat_response("")
    assert out.queried is False
    assert out.status is None


def test_parse_unknown_xml_falls_to_error() -> None:
    out = parse_sat_response("<xml>weird response</xml>")
    assert out.status == "error"


# ---------------------------------------------------------------------------
# verify_cfdi


@pytest.mark.asyncio
async def test_verify_cfdi_invalid_uuid_returns_error() -> None:
    out = await verify_cfdi(
        "not-a-uuid", "AAA010101AAA", "BBB020202BBB", 250000.0
    )
    assert out.queried is False
    assert "UUID inválido" in (out.error or "")


@pytest.mark.asyncio
async def test_verify_cfdi_missing_fields_returns_error() -> None:
    out = await verify_cfdi("", "AAA010101AAA", "BBB020202BBB", 250000.0)
    assert out.queried is False
    assert "Faltan campos" in (out.error or "")


@pytest.mark.asyncio
async def test_verify_cfdi_calls_sat_endpoint() -> None:
    captured = {}

    async def _mock_get(self, url, **kwargs):  # noqa: ARG001
        captured["url"] = url
        captured["params"] = kwargs.get("params", {})
        return httpx.Response(
            200, text=_vigente_xml(), request=httpx.Request("GET", url)
        )

    with patch.object(httpx.AsyncClient, "get", _mock_get):
        out = await verify_cfdi(
            "abcd1234-ef56-7890-abcd-ef1234567890",
            "AAA010101AAA", "BBB020202BBB", 250000.0,
        )

    assert out.queried is True
    assert out.status == "vigente"
    assert "verificacfdi" in captured["url"] or "consultaqr" in captured["url"]
    expr = captured["params"].get("expresionImpresa", "")
    assert "abcd1234-ef56-7890-abcd-ef1234567890" in expr.lower()
    assert "AAA010101AAA" in expr
    assert "250000" in expr


@pytest.mark.asyncio
async def test_verify_cfdi_handles_timeout() -> None:
    async def _raise(self, url, **kwargs):  # noqa: ARG001
        raise httpx.TimeoutException("simulated")

    with patch.object(httpx.AsyncClient, "get", _raise):
        out = await verify_cfdi(
            "abcd1234-ef56-7890-abcd-ef1234567890",
            "AAA010101AAA", "BBB020202BBB", 250000.0,
        )
    assert out.queried is False
    assert "no respondió" in (out.error or "")


@pytest.mark.asyncio
async def test_verify_cfdi_returns_cancelado() -> None:
    async def _mock_get(self, url, **kwargs):  # noqa: ARG001
        return httpx.Response(
            200, text=_cancelado_xml(), request=httpx.Request("GET", url)
        )

    with patch.object(httpx.AsyncClient, "get", _mock_get):
        out = await verify_cfdi(
            "abcd1234-ef56-7890-abcd-ef1234567890",
            "AAA010101AAA", "BBB020202BBB", 250000.0,
        )
    assert out.status == "cancelado"
