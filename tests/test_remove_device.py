from types import SimpleNamespace
from typing import Any, cast

import pytest

from custom_components.ac_infinity import async_remove_config_entry_device
from custom_components.ac_infinity.const import DOMAIN


def _hass(active_ids, controller_id="1"):
    controller = SimpleNamespace(
        identifier=(DOMAIN, controller_id),
        devices=[SimpleNamespace(device_info={"identifiers": {(DOMAIN, f"{controller_id}_{i}")}}) for i in active_ids],
    )
    service = SimpleNamespace(get_all_controller_properties=lambda: [controller])
    return SimpleNamespace(data={DOMAIN: {"entry": SimpleNamespace(service=service)}})


@pytest.mark.asyncio
async def test_active_controller_and_port_devices_cannot_be_removed():
    hass = _hass([1])
    entry = SimpleNamespace(entry_id="entry")
    assert not await async_remove_config_entry_device(cast(Any, hass), cast(Any, entry), cast(Any, SimpleNamespace(identifiers={(DOMAIN, "1")})))
    assert not await async_remove_config_entry_device(cast(Any, hass), cast(Any, entry), cast(Any, SimpleNamespace(identifiers={(DOMAIN, "1_1")})))


@pytest.mark.asyncio
async def test_stale_device_can_be_removed():
    hass = _hass([])
    entry = SimpleNamespace(entry_id="entry")
    assert await async_remove_config_entry_device(cast(Any, hass), cast(Any, entry), cast(Any, SimpleNamespace(identifiers={(DOMAIN, "1_0")})))
