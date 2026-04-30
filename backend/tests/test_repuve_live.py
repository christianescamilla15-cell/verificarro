"""Live network smoke test for REPUVE.

Skipped by default. Activarlo con:

    RUN_LIVE_REPUVE=1 \
    VERIFICARRO_LIVE_PLATE=ABC123D \
    pytest tests/test_repuve_live.py -v -s
"""

import os

import pytest

from app.scrapers.repuve import query


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_LIVE_REPUVE") != "1",
    reason="Live REPUVE query disabled — set RUN_LIVE_REPUVE=1 to enable",
)
async def test_live_repuve_query() -> None:
    plate = os.getenv("VERIFICARRO_LIVE_PLATE")
    vin = os.getenv("VERIFICARRO_LIVE_VIN")
    if not plate and not vin:
        pytest.skip("Set VERIFICARRO_LIVE_PLATE or VERIFICARRO_LIVE_VIN to run")

    result = await query(plate=plate, vin=vin)
    print("\n--- REPUVE LIVE RESULT ---")
    print(result.model_dump_json(indent=2))
    # No assertion sobre is_stolen — depende de la placa.
    assert result.queried or result.error
