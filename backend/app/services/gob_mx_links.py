"""Generador de links a portales oficiales gob.mx para auto-verificación.

En lugar de scrapear cada portal estatal (cada uno con su captcha y
anti-bot), generamos los URLs pre-llenados con la placa y dejamos
que el usuario haga la consulta él mismo. Tradeoffs:

| Approach        | Costo | Confiabilidad | Latencia | Cobertura |
|-----------------|-------|---------------|----------|-----------|
| Scraping directo| alto  | 30-60%        | 5-30s    | Solo el estado scrapeado |
| Links pre-llenos| $0    | 100%          | 0s       | Todos los portales públicos |

Para el preview gratis: incluimos los links como "verifica tú mismo
en 30s". Para el unlock pro: agregamos contexto + prioridad por
estado del listing.

## Portales cubiertos

| Portal                        | Aplica a              | Requiere |
|-------------------------------|-----------------------|----------|
| REPUVE federal                | Todo México           | Placa o NIV |
| Tenencia CDMX                 | Vehículos CDMX        | Placa + tarjeta circulación |
| Tenencia Edomex               | Vehículos Edomex      | Placa |
| Verificación CDMX             | Vehículos CDMX        | Placa |
| Verificación Edomex           | Vehículos Edomex      | Placa |
| Infracciones CDMX             | Vehículos CDMX        | Placa |
| Pago de tenencias federal     | Algunos estados       | Placa + serie |

## Detección de estado

Si `listing.location` menciona "CDMX", "Ciudad de México", "DF",
"Edomex", "Estado de México" o municipios conocidos, marcamos los
portales correspondientes como `applicable=True`. El resto vienen
con `applicable=False` pero igual los ofrecemos por si el dueño
del auto está en otro estado del que vive el comprador.
"""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlencode


PortalCategory = Literal["robo", "fiscal", "ambiental", "infracciones"]


# MOD-016: ConsultationLink ahora es directamente el Pydantic v2 model
# que el Report consume. Antes había un mapper que convertía
# dataclass → ConsultationLinkModel byte-por-byte; ya no es necesario.
from app.models.report import ConsultationLinkModel as ConsultationLink


def build_consultation_links(
    plate: str | None = None,
    vin: str | None = None,
    location: str | None = None,
) -> list[ConsultationLink]:
    """Genera la lista de links de consulta pre-llenados.

    `applicable=True` solo para portales que coinciden con el estado
    detectado en `location`. Los demás siguen en la lista (el comprador
    puede estar en otro estado) pero marcados como tal.
    """
    state = _detect_state(location)
    links: list[ConsultationLink] = []

    # ===== Federal: REPUVE =====
    repuve_url = "https://www2.repuve.gob.mx:8443/ciudadania/"
    links.append(ConsultationLink(
        name="REPUVE — Registro Público Vehicular",
        url=repuve_url,
        description=(
            "Consulta oficial federal para reportes de robo y situación "
            "legal del vehículo. La consulta requiere reCaptcha; ingresa "
            f"placa {plate or '___'} o NIV {vin or '___'} y resuelve el "
            "captcha."
        ),
        category="robo",
        applicable=True,
        state_scope="Federal",
    ))

    # ===== CDMX =====
    cdmx_applicable = state == "CDMX"

    # Tenencia + refrendo CDMX
    links.append(ConsultationLink(
        name="Adeudo de tenencia y refrendo — CDMX",
        url="https://data.finanzas.cdmx.gob.mx/sma/sm_paginas/Adeudo_vehicular_movil.html",
        description=(
            f"Consulta adeudos de tenencia/refrendo CDMX. Ingresa placa "
            f"{plate or '___'}. Si hay adeudos pendientes, el dueño actual "
            "los traspasa al comprador en muchos casos."
        ),
        category="fiscal",
        applicable=cdmx_applicable,
        state_scope="CDMX",
    ))

    # Verificación vehicular CDMX
    if plate:
        verif_cdmx_url = (
            "https://www.verificacionvehicular.cdmx.gob.mx/Inicio/"
            "?" + urlencode({"placa": plate})
        )
    else:
        verif_cdmx_url = "https://www.verificacionvehicular.cdmx.gob.mx/"
    links.append(ConsultationLink(
        name="Verificación vehicular — CDMX",
        url=verif_cdmx_url,
        description=(
            f"Consulta el estado de verificación ambiental (holograma, "
            f"vencimiento) en CDMX. Placa: {plate or '___'}. Si está "
            "vencida o no verifica, hay multas pendientes y restricción "
            "de circulación."
        ),
        category="ambiental",
        applicable=cdmx_applicable,
        state_scope="CDMX",
    ))

    # Infracciones CDMX
    links.append(ConsultationLink(
        name="Infracciones de tránsito — CDMX",
        url="https://www.consultapagosvehiculares.cdmx.gob.mx/",
        description=(
            f"Consulta multas e infracciones pendientes en CDMX para "
            f"placa {plate or '___'}. El dueño nuevo hereda algunas de "
            "estas obligaciones."
        ),
        category="infracciones",
        applicable=cdmx_applicable,
        state_scope="CDMX",
    ))

    # ===== Edomex =====
    edomex_applicable = state == "Edomex"

    links.append(ConsultationLink(
        name="Adeudos vehiculares — Estado de México",
        url="https://sfpya.edomexico.gob.mx/recaudacion/",
        description=(
            f"Consulta tenencia, refrendo e infracciones para vehículos "
            f"con placa Edomex. Ingresa {plate or '___'} en el portal."
        ),
        category="fiscal",
        applicable=edomex_applicable,
        state_scope="Edomex",
    ))

    links.append(ConsultationLink(
        name="Verificación vehicular — Estado de México",
        url="https://sma.edomex.gob.mx/verificacion_vehicular",
        description=(
            "Consulta el estado de verificación ambiental para vehículos "
            f"Edomex (placa {plate or '___'})."
        ),
        category="ambiental",
        applicable=edomex_applicable,
        state_scope="Edomex",
    ))

    return links


# ---------------------------------------------------------------------------
# State detection


_CDMX_PATTERNS = (
    r"cdmx",
    r"ciudad de m[éexico]",
    r"\bd\.?\s*f\.?\b",
    r"distrito federal",
)
# Delegaciones / alcaldías CDMX
_CDMX_DELEGATIONS = (
    "alvaro obregon", "azcapotzalco", "benito juarez", "coyoacan",
    "cuajimalpa", "cuauhtemoc", "gustavo a madero", "gustavo madero",
    "iztacalco", "iztapalapa", "magdalena contreras", "miguel hidalgo",
    "milpa alta", "tlahuac", "tlalpan", "venustiano carranza", "xochimilco",
)
# Edomex municipios mayores
_EDOMEX_MUNICIPALITIES = (
    "edomex", "estado de mexico", "estado de méxico",
    "naucalpan", "ecatepec", "tlalnepantla", "nezahualcoyotl",
    "neza", "atizapan", "cuautitlan", "tultitlan", "chimalhuacan",
    "huixquilucan", "metepec", "toluca",
)


def _detect_state(location: str | None) -> str | None:
    """Heurística para detectar CDMX / Edomex desde el texto de location."""
    if not location:
        return None
    norm = _strip_accents(location).lower()
    if any(re.search(p, norm) for p in _CDMX_PATTERNS):
        return "CDMX"
    if any(d in norm for d in _CDMX_DELEGATIONS):
        return "CDMX"
    if any(m in norm for m in _EDOMEX_MUNICIPALITIES):
        return "Edomex"
    return None


def _strip_accents(s: str) -> str:
    table = str.maketrans("áéíóúÁÉÍÓÚñÑ", "aeiouAEIOUnN")
    return s.translate(table)
