"""Decoder de VIN (Vehicle Identification Number) según ISO 3779.

100% local, sin red, sin API. Decodifica:

- **WMI** (posiciones 1-3): país de fabricación + marca, con aliases
  (Honda↔Acura, Toyota↔Lexus, Nissan↔Infiniti, etc.)
- **Año modelo** (posición 10): tabla cíclica 1980-2039 con
  desambiguación 1980-2009 vs 2010-2039 mediante posición 7
  (dígito → ciclo viejo, letra → ciclo nuevo)
- **Checksum** (posición 9): validación ISO 3779 estándar (USA + MX
  obligatorio; Europa lo omite — algunos VINs alemanes legítimos
  fallan el checksum y no es alarma por sí mismo)
- **Validación de formato**: 17 chars, sin I/O/Q (caracteres prohibidos
  por estándar para evitar confusión con 1/0)

## Cobertura WMI

La tabla cubre las ~40 marcas que dominan Marketplace MX. Si llega un
WMI fuera de la tabla (ej. fabricante chino o europeo raro), devolvemos
`manufacturer=None` y NO emitimos alerta — mejor falso negativo que
falso positivo en la marca.

Para ampliar la tabla, fuentes públicas:
- SAE WMI registry
- nhtsa.dot.gov (USA, gratis)
- vinaudit.com listings
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Year codes (posición 10)
#
# El estándar ISO 3779 cicla cada 30 años. Para desambiguar, se usa la
# posición 7: si es DÍGITO, año está en ciclo 1980-2009; si es LETRA,
# año está en 2010+.

_YEAR_CODES_OLD: dict[str, int] = {
    "A": 1980, "B": 1981, "C": 1982, "D": 1983, "E": 1984,
    "F": 1985, "G": 1986, "H": 1987, "J": 1988, "K": 1989,
    "L": 1990, "M": 1991, "N": 1992, "P": 1993, "R": 1994,
    "S": 1995, "T": 1996, "V": 1997, "W": 1998, "X": 1999,
    "Y": 2000,
    "1": 2001, "2": 2002, "3": 2003, "4": 2004, "5": 2005,
    "6": 2006, "7": 2007, "8": 2008, "9": 2009,
}

_YEAR_CODES_NEW: dict[str, int] = {
    "A": 2010, "B": 2011, "C": 2012, "D": 2013, "E": 2014,
    "F": 2015, "G": 2016, "H": 2017, "J": 2018, "K": 2019,
    "L": 2020, "M": 2021, "N": 2022, "P": 2023, "R": 2024,
    "S": 2025, "T": 2026, "V": 2027, "W": 2028, "X": 2029,
    "Y": 2030,
    # Después de Y: vuelve a dígitos para 2031-2039
    "1": 2031, "2": 2032, "3": 2033, "4": 2034, "5": 2035,
    "6": 2036, "7": 2037, "8": 2038, "9": 2039,
}


# ---------------------------------------------------------------------------
# WMI table — top 40 marcas de Marketplace MX
#
# Formato: WMI (3 chars uppercase) → (country, manufacturer, [aliases])
# Aliases listan marcas hermanas que pueden compartir WMI (Honda↔Acura).

_WMI_TABLE: dict[str, tuple[str, str, list[str]]] = {
    # --- Honda + Acura ---
    "1HG": ("USA", "Honda", ["Acura"]),
    "2HG": ("Canadá", "Honda", ["Acura"]),
    "2HK": ("Canadá", "Honda", []),
    "2HM": ("Canadá", "Honda", []),
    "3HG": ("México", "Honda", []),
    "3HM": ("México", "Honda", []),
    "JHM": ("Japón", "Honda", []),
    "JHL": ("Japón", "Honda", []),
    "JH4": ("Japón", "Acura", ["Honda"]),
    "19U": ("USA", "Honda", ["Acura"]),
    "19X": ("USA", "Honda", []),
    "19V": ("USA", "Honda", []),
    "5J6": ("USA", "Honda", []),
    "5J8": ("USA", "Acura", ["Honda"]),
    "5FN": ("USA", "Honda", []),
    "2FA": ("Canadá", "Ford", []),

    # --- Toyota + Lexus ---
    "1NX": ("USA", "Toyota", []),
    "2T1": ("Canadá", "Toyota", []),
    "2T3": ("Canadá", "Toyota", []),
    "4T1": ("USA", "Toyota", ["Lexus"]),
    "4T3": ("USA", "Toyota", []),
    "5TD": ("USA", "Toyota", []),
    "5TF": ("USA", "Toyota", []),
    "5TB": ("USA", "Toyota", []),
    "5YF": ("USA", "Toyota", []),
    "JTD": ("Japón", "Toyota", []),
    "JTE": ("Japón", "Toyota", []),
    "JTH": ("Japón", "Lexus", ["Toyota"]),
    "JTJ": ("Japón", "Lexus", ["Toyota"]),
    "JTM": ("Japón", "Toyota", []),
    "JTN": ("Japón", "Toyota", []),

    # --- Nissan + Infiniti ---
    "1N4": ("USA", "Nissan", []),
    "1N6": ("USA", "Nissan", []),
    "3N1": ("México", "Nissan", []),
    "3N6": ("México", "Nissan", []),
    "5N1": ("USA", "Nissan", []),
    "5N3": ("USA", "Infiniti", ["Nissan"]),
    "JN1": ("Japón", "Nissan", []),
    "JN6": ("Japón", "Nissan", []),
    "JN8": ("Japón", "Nissan", []),
    "JNK": ("Japón", "Infiniti", ["Nissan"]),
    "JNR": ("Japón", "Infiniti", ["Nissan"]),

    # --- Volkswagen + Audi ---
    "1VW": ("USA", "Volkswagen", []),
    "3VW": ("México", "Volkswagen", []),
    "9BW": ("Brasil", "Volkswagen", []),
    "WVW": ("Alemania", "Volkswagen", []),
    "WV1": ("Alemania", "Volkswagen", []),
    "WV2": ("Alemania", "Volkswagen", []),
    "WAU": ("Alemania", "Audi", []),
    "WA1": ("Alemania", "Audi", []),
    "TRU": ("Hungría", "Audi", []),

    # --- Chevrolet + Buick + GMC + Cadillac ---
    "1G1": ("USA", "Chevrolet", []),
    "1G6": ("USA", "Cadillac", []),
    "1GC": ("USA", "Chevrolet", []),
    "1GD": ("USA", "GMC", ["Chevrolet"]),
    "1GK": ("USA", "GMC", []),
    "1GN": ("USA", "Chevrolet", []),
    "1GT": ("USA", "GMC", []),
    "1G4": ("USA", "Buick", []),
    "2G1": ("Canadá", "Chevrolet", []),
    "3G1": ("México", "Chevrolet", []),
    "3GN": ("México", "Chevrolet", []),
    "KL": ("Corea", "Chevrolet", []),
    "KLA": ("Corea", "Chevrolet", []),

    # --- Ford + Lincoln ---
    "1FA": ("USA", "Ford", []),
    "1FT": ("USA", "Ford", []),
    "1FM": ("USA", "Ford", []),
    "1FD": ("USA", "Ford", []),
    "1LN": ("USA", "Lincoln", ["Ford"]),
    "1L1": ("USA", "Lincoln", []),
    "3FA": ("México", "Ford", []),
    "5LM": ("USA", "Lincoln", []),

    # --- Hyundai + Kia ---
    "KMH": ("Corea", "Hyundai", []),
    "KM8": ("Corea", "Hyundai", []),
    "5XY": ("USA", "Hyundai", []),
    "5NP": ("USA", "Hyundai", []),
    "KNA": ("Corea", "Kia", []),
    "KND": ("Corea", "Kia", []),
    "KNH": ("Corea", "Kia", []),
    "5XX": ("USA", "Kia", []),

    # --- Mazda ---
    "JM1": ("Japón", "Mazda", []),
    "JM3": ("Japón", "Mazda", []),
    "4F2": ("USA", "Mazda", []),
    "4F4": ("USA", "Mazda", []),
    "3MZ": ("México", "Mazda", []),

    # --- Mitsubishi ---
    "JA3": ("Japón", "Mitsubishi", []),
    "JA4": ("Japón", "Mitsubishi", []),
    "4A3": ("USA", "Mitsubishi", []),
    "4A4": ("USA", "Mitsubishi", []),

    # --- Subaru ---
    "JF1": ("Japón", "Subaru", []),
    "JF2": ("Japón", "Subaru", []),
    "4S3": ("USA", "Subaru", []),
    "4S4": ("USA", "Subaru", []),

    # --- BMW + Mini ---
    "WBA": ("Alemania", "BMW", []),
    "WBS": ("Alemania", "BMW", []),
    "WBX": ("Alemania", "BMW", []),
    "5UX": ("USA", "BMW", []),
    "5YM": ("USA", "BMW", []),
    "WMW": ("Reino Unido", "Mini", ["BMW"]),

    # --- Mercedes-Benz ---
    "WDD": ("Alemania", "Mercedes-Benz", []),
    "WDC": ("Alemania", "Mercedes-Benz", []),
    "WDB": ("Alemania", "Mercedes-Benz", []),
    "4JG": ("USA", "Mercedes-Benz", []),
    "55S": ("USA", "Mercedes-Benz", []),

    # --- Stellantis (Jeep, Dodge, Chrysler, Ram, Fiat) ---
    "1J4": ("USA", "Jeep", []),
    "1J8": ("USA", "Jeep", []),
    "1C4": ("USA", "Chrysler", ["Jeep"]),
    "1C6": ("USA", "Chrysler", ["Ram"]),
    "1C3": ("USA", "Chrysler", []),
    "2D4": ("Canadá", "Dodge", []),
    "3C4": ("México", "Chrysler", []),
    "3C6": ("México", "Ram", []),
    "ZFA": ("Italia", "Fiat", []),
    "ZFC": ("Italia", "Fiat", []),

    # --- Volvo, Land Rover, Jaguar, Porsche ---
    "YV1": ("Suecia", "Volvo", []),
    "YV4": ("Suecia", "Volvo", []),
    "SAJ": ("Reino Unido", "Jaguar", []),
    "SAL": ("Reino Unido", "Land Rover", []),
    "WP0": ("Alemania", "Porsche", []),
    "WP1": ("Alemania", "Porsche", []),

    # --- Tesla ---
    "5YJ": ("USA", "Tesla", []),
    "7SA": ("USA", "Tesla", []),

    # --- Marcas chinas crecientes en MX (Chirey, BYD, MG, JAC) ---
    "LVT": ("China", "Chirey", []),  # Chery
    "LVS": ("China", "Chirey", []),
    "LGX": ("China", "BYD", []),
    "LGB": ("China", "BYD", []),
    "L6T": ("China", "MG", []),
    "LSV": ("China", "MG", []),
    "LJ1": ("China", "JAC", []),
    "LJD": ("China", "JAC", []),
    "LMG": ("China", "Geely", []),
    "LB3": ("China", "Geely", []),

    # --- SEAT, Renault ---
    "VSS": ("España", "Seat", []),
    "VF1": ("Francia", "Renault", []),
    "VF6": ("Francia", "Renault", []),
    "8A1": ("Argentina", "Renault", []),

    # --- Peugeot, Citroën ---
    "VF3": ("Francia", "Peugeot", []),
    "VF7": ("Francia", "Citroën", []),
}


_INVALID_VIN_CHARS = re.compile(r"[IOQ]")
# Preserva A-Z y 0-9 (incluye I/O/Q intencionalmente — el decoder los
# detecta y emite diagnóstico claro). Solo quita guiones/espacios/símbolos.
_NORMALIZE_RE = re.compile(r"[^A-Z0-9]")


@dataclass(frozen=True)
class VinDecoded:
    """Resultado de decodificar un VIN. Dataclass para que el módulo
    `app.analyzers` no necesite Pydantic — los modelos Pydantic vivien
    aparte y se construyen desde aquí.
    """

    vin: str
    valid_format: bool
    valid_checksum: bool
    wmi: str
    country: str | None = None
    manufacturer: str | None = None
    manufacturer_aliases: list[str] = field(default_factory=list)
    year: int | None = None
    errors: list[str] = field(default_factory=list)


def normalize_vin(raw: str) -> str:
    """Uppercase + remueve guiones/espacios. NO valida formato."""
    if not raw:
        return ""
    return _NORMALIZE_RE.sub("", raw.upper())


def decode(raw_vin: str) -> VinDecoded:
    """Decodifica un VIN string. Función pura, sin red."""
    vin = normalize_vin(raw_vin)
    errors: list[str] = []

    if len(vin) != 17:
        errors.append(f"VIN debe tener 17 caracteres, tiene {len(vin)}")
        return VinDecoded(
            vin=vin, valid_format=False, valid_checksum=False, wmi=vin[:3],
            errors=errors,
        )

    invalid_match = _INVALID_VIN_CHARS.search(vin)
    if invalid_match:
        errors.append(
            f"VIN contiene carácter prohibido '{invalid_match.group()}' "
            f"(I/O/Q no permitidos por ISO 3779)"
        )
        return VinDecoded(
            vin=vin, valid_format=False, valid_checksum=False, wmi=vin[:3],
            errors=errors,
        )

    wmi = vin[:3]
    country, manufacturer, aliases = _lookup_wmi(wmi)
    if manufacturer is None:
        errors.append(
            f"WMI '{wmi}' no está en la tabla de Verificarro — marca "
            "desconocida (no es alarma por sí solo)"
        )

    year = _decode_year(vin)
    if year is None:
        errors.append("No pude decodificar el año modelo del VIN")

    valid_checksum = _validate_checksum(vin)
    if not valid_checksum:
        errors.append(
            "Checksum ISO 3779 inválido — el VIN puede estar mal "
            "transcrito o ser inválido (Europa a veces omite checksum)"
        )

    return VinDecoded(
        vin=vin,
        valid_format=True,
        valid_checksum=valid_checksum,
        wmi=wmi,
        country=country,
        manufacturer=manufacturer,
        manufacturer_aliases=aliases,
        year=year,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Internal helpers


def _lookup_wmi(wmi: str) -> tuple[str | None, str | None, list[str]]:
    if wmi in _WMI_TABLE:
        country, manufacturer, aliases = _WMI_TABLE[wmi]
        return country, manufacturer, list(aliases)
    # Fallback: prueba prefijo de 2 chars (algunos WMIs varían en 3°)
    prefix = wmi[:2]
    for key, value in _WMI_TABLE.items():
        if key.startswith(prefix):
            # Solo aceptamos prefijo si es un fabricante con ≥3 entradas
            # con ese prefijo (evita falsos positivos).
            count = sum(1 for k in _WMI_TABLE if k.startswith(prefix))
            if count >= 3:
                return value[0], value[1], []
            break
    return None, None, []


def _decode_year(vin: str) -> int | None:
    pos10 = vin[9]
    pos7 = vin[6]
    table = _YEAR_CODES_NEW if pos7.isalpha() else _YEAR_CODES_OLD
    return table.get(pos10)


# Tabla de transliteration ISO 3779 para checksum
_TRANSLIT: dict[str, int] = {
    **{str(d): d for d in range(10)},
    "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8,
    "J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "P": 7, "R": 9,
    "S": 2, "T": 3, "U": 4, "V": 5, "W": 6, "X": 7, "Y": 8, "Z": 9,
}

_WEIGHTS: tuple[int, ...] = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)


def _validate_checksum(vin: str) -> bool:
    if len(vin) != 17:
        return False
    try:
        total = sum(_TRANSLIT[c] * _WEIGHTS[i] for i, c in enumerate(vin))
    except KeyError:
        return False
    expected = total % 11
    expected_char = "X" if expected == 10 else str(expected)
    return vin[8] == expected_char
