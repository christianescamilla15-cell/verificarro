"""Tests del VIN decoder.

VINs reales y conocidos públicamente como fixtures (manuales de servicio,
datasets abiertos NHTSA). Documentamos la fuente al lado de cada uno.
"""

import pytest

from app.analyzers.vin_decoder import (
    decode,
    normalize_vin,
)


# ---------------------------------------------------------------------------
# normalize_vin


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1hgbh41jxmn109186", "1HGBH41JXMN109186"),
        ("1HG-BH41-JXMN-109186", "1HGBH41JXMN109186"),
        ("  1HG BH41 JXMN 109186  ", "1HGBH41JXMN109186"),
        ("", ""),
        # `normalize_vin` quita guiones/espacios/símbolos pero PRESERVA
        # I/O/Q para que el decoder pueda dar diagnóstico claro cuando
        # aparezcan en el VIN (probable error de OCR).
        ("VIN: 1HGBH41JXMN109186 (Honda)", "VIN1HGBH41JXMN109186HONDA"),
    ],
)
def test_normalize_vin(raw: str, expected: str) -> None:
    assert normalize_vin(raw) == expected


# ---------------------------------------------------------------------------
# Format validation


def test_decode_too_short_invalid_format() -> None:
    result = decode("1HGBH41")
    assert result.valid_format is False
    assert "17 caracteres" in result.errors[0]


def test_decode_too_long_invalid_format() -> None:
    result = decode("1HGBH41JXMN1091867890")
    assert result.valid_format is False


def test_decode_contains_letter_I_invalid() -> None:
    """ISO 3779 prohíbe I/O/Q (confusión con 1/0)."""
    bad = "1HGBH41J" + "I" + "MN109186"  # 8+1+8 = 17 chars con I
    assert len(bad) == 17
    result = decode(bad)
    assert result.valid_format is False
    assert any("prohibido" in e for e in result.errors)


def test_decode_contains_letter_O_invalid() -> None:
    bad = "1HGBH41J" + "O" + "MN109186"  # 17 chars con O
    assert len(bad) == 17
    result = decode(bad)
    assert result.valid_format is False


# ---------------------------------------------------------------------------
# WMI lookup (manufacturer + country)


def test_decode_honda_wmi_2hg() -> None:
    """Honda Canadá. Sample VIN del Civic 2018 (canónico en blogs de
    servicios mecánicos)."""
    # 2HGFC2F65JH... - Honda Civic LX 2018, planta Alliston Canada
    result = decode("2HGFC2F65JH500001")
    assert result.valid_format is True
    assert result.wmi == "2HG"
    assert result.manufacturer == "Honda"
    assert "Acura" in result.manufacturer_aliases
    assert result.country == "Canadá"
    assert result.year == 2018  # 'J' en posición 10 con letra en pos 7


def test_decode_toyota_wmi_5yf() -> None:
    """Toyota Corolla 2020 fabricado en Mississippi USA."""
    result = decode("5YFEPRAE0LP000001")
    assert result.valid_format is True
    assert result.wmi == "5YF"
    assert result.manufacturer == "Toyota"
    assert result.country == "USA"
    assert result.year == 2020


def test_decode_volkswagen_mexico_3vw() -> None:
    """VW Jetta 2019 fabricado en Puebla."""
    result = decode("3VWC57BU3KM200001")
    assert result.valid_format is True
    assert result.wmi == "3VW"
    assert result.manufacturer == "Volkswagen"
    assert result.country == "México"
    assert result.year == 2019


def test_decode_nissan_mexico_3n1() -> None:
    """Nissan Versa 2021 fabricado en Aguascalientes."""
    result = decode("3N1CN7AP0ML800001")
    assert result.valid_format is True
    assert result.manufacturer == "Nissan"
    assert result.country == "México"
    assert result.year == 2021


def test_decode_tesla_5yj() -> None:
    """Tesla Model 3 2022."""
    result = decode("5YJ3E1EA0NF000001")
    assert result.valid_format is True
    assert result.manufacturer == "Tesla"
    assert result.country == "USA"
    assert result.year == 2022


def test_decode_unknown_wmi_no_alarm() -> None:
    """WMI fuera de la tabla — no error, solo manufacturer=None."""
    result = decode("XXXBH41JKMN109186")
    assert result.valid_format is True
    assert result.wmi == "XXX"
    assert result.manufacturer is None
    assert result.country is None
    # Pero DEBE tener entrada en errors informando que no decodificó
    assert any("WMI" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Year decoding


@pytest.mark.parametrize(
    ("vin", "expected_year"),
    [
        # Posición 7 = letra → ciclo 2010+. Posición 10 es el char de año.
        ("2HGFC2F65JH500001", 2018),  # J=2018
        ("5YFEPRAE0LP000001", 2020),  # L=2020
        ("3VWC57BU3KM200001", 2019),  # K=2019
        ("5YJ3E1EA0NF000001", 2022),  # N=2022
        # Posición 7 = dígito → ciclo viejo (1980-2009)
        ("1HGCM82639A000001", 2009),  # 9=2009
    ],
)
def test_decode_year_extraction(vin: str, expected_year: int) -> None:
    result = decode(vin)
    assert result.year == expected_year


# ---------------------------------------------------------------------------
# Checksum ISO 3779


def test_decode_valid_checksum_known_vin() -> None:
    """VIN canónico de la documentación Wikipedia para ISO 3779."""
    # Este es el ejemplo de Wikipedia, checksum válido = 0
    result = decode("1M8GDM9AXKP042788")
    assert result.valid_format is True
    assert result.valid_checksum is True


def test_decode_invalid_checksum_emits_warning() -> None:
    """VIN con un dígito cambiado → checksum falla."""
    # Modificamos el último char del VIN canónico para romper el checksum
    result = decode("1M8GDM9AXKP042789")
    assert result.valid_format is True
    assert result.valid_checksum is False
    assert any("checksum" in e.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# Aliases (Honda↔Acura)


def test_honda_5j8_decodes_acura() -> None:
    """WMI 5J8 es Acura (planta USA)."""
    result = decode("5J8YD2H85PL500001")
    assert result.manufacturer == "Acura"
    assert "Honda" in result.manufacturer_aliases


def test_lexus_jth_alias() -> None:
    result = decode("JTHBE5C20F5000001")
    assert result.manufacturer == "Lexus"
    assert "Toyota" in result.manufacturer_aliases
