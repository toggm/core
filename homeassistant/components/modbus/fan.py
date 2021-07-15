"""Support for Modbus fans."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.fan import ENTITY_ID_FORMAT, FanEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .base_platform import BaseSwitch
from .const import CONF_FANS, MODBUS_DOMAIN
from .modbus import ModbusHub

PARALLEL_UPDATES = 1
_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant, config: ConfigType, async_add_entities, discovery_info=None
):
    """Read configuration and create Modbus fans."""
    if discovery_info is None:  # pragma: no cover
        return
    fans = []

    for entry in discovery_info[CONF_FANS]:
        hub: ModbusHub = hass.data[MODBUS_DOMAIN][discovery_info[CONF_NAME]]
        fans.append(ModbusFan(hub, entry))
    async_add_entities(fans)


class ModbusFan(BaseSwitch, FanEntity):
    """Class representing a Modbus fan."""

    def __init__(
        self,
        hub: ModbusHub,
        config: dict[str, Any],
    ) -> None:
        """Initialize the modbus fan."""
        super().__init__(hub, config)
        self.entity_id = ENTITY_ID_FORMAT.format(self._id)

    async def async_turn_on(
        self,
        speed: str | None = None,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs,
    ) -> None:
        """Set fan on."""
        await self.async_turn(self.command_on)
