"""Support for Modbus switches."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import ENTITY_ID_FORMAT, SwitchEntity
from homeassistant.const import CONF_NAME, CONF_SWITCHES
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .base_platform import BaseSwitch
from .const import MODBUS_DOMAIN
from .modbus import ModbusHub

PARALLEL_UPDATES = 1
_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant, config: ConfigType, async_add_entities, discovery_info=None
):
    """Read configuration and create Modbus switches."""
    switches = []

    if discovery_info is None:  # pragma: no cover
        return

    for entry in discovery_info[CONF_SWITCHES]:
        hub: ModbusHub = hass.data[MODBUS_DOMAIN][discovery_info[CONF_NAME]]
        switches.append(ModbusSwitch(hub, entry))
    async_add_entities(switches)


class ModbusSwitch(BaseSwitch, SwitchEntity):
    """Base class representing a Modbus switch."""

    def __init__(
        self,
        hub: ModbusHub,
        config: dict[str, Any],
    ) -> None:
        """Initialize the modbus switch."""
        super().__init__(hub, config)
        self.entity_id = ENTITY_ID_FORMAT.format(self._id)

    async def async_turn_on(self, **kwargs):
        """Set switch on."""
        await self.async_turn(self.command_on)
