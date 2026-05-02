from typing import Annotated

from fastapi import APIRouter, Depends

from app import __version__
from app.config import Settings, get_settings

router = APIRouter(tags=["health"])

SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": __version__, "service": "verificarro"}


@router.get("/api/config")
async def public_config(settings: SettingsDep) -> dict:
    """Configuración pública del servicio que el frontend consume.

    Solo expone toggles y datos no-secretos. El frontend lo usa para
    decidir qué CTAs mostrar (e.g., botón WhatsApp solo si hay número
    configurado).
    """
    wa_number = settings.whatsapp_support_number.strip()
    return {
        "whatsapp_enabled": bool(wa_number),
        "whatsapp_number": wa_number if wa_number else None,
        "pricing": {
            "basic_mxn": settings.price_basic_mxn,
            "premium_mxn": settings.price_premium_mxn,
            "search_mxn": settings.price_search_mxn,
            "dealer_mxn": settings.price_dealer_mxn,
        },
    }
