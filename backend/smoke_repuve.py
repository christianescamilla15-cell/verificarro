"""Smoke en vivo del scraper REPUVE.

Por default usa una placa intencionalmente improbable (`ZZZ999Z`) que
debería devolver "no encontrado" — basta para validar el flujo completo
sin tocar datos reales. Para una placa real:

    VERIFICARRO_LIVE_PLATE=ABC1234 python smoke_repuve.py

## Logging

Configuramos `basicConfig(level=INFO)` para que se vean los logs de
captcha_solver y audio_captcha_solver. Sin esto los `logger.info()` de
"Sin challenge frame", "Whisper raw=...", etc. quedan invisibles y es
imposible diagnosticar qué path activó.
"""

import asyncio
import json
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    force=True,  # override cualquier handler instalado por imports previos
)

from app.scrapers.repuve import query  # noqa: E402  (after basicConfig)


async def main() -> int:
    plate = os.getenv("VERIFICARRO_LIVE_PLATE", "ZZZ999Z")
    vin = os.getenv("VERIFICARRO_LIVE_VIN")
    print(f"[smoke] Consultando REPUVE — plate={plate}, vin={vin}", flush=True)
    result = await query(plate=plate, vin=vin)
    print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))

    if result.error and "Error al consultar" in result.error:
        print(f"[smoke] FAIL: {result.error}", file=sys.stderr)
        return 1
    print("[smoke] OK — el scraper completó la consulta sin excepciones")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
