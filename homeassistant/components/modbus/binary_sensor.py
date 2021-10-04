"""Support for Modbus Coil and Discrete Input sensors."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import ENTITY_ID_FORMAT, BinarySensorEntity
from homeassistant.components.modbus.modbus import ModbusHub
from homeassistant.const import CONF_BINARY_SENSORS, CONF_NAME, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .base_platform import BasePlatform
from .const import MODBUS_DOMAIN

PARALLEL_UPDATES = 1
_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities,
    discovery_info: DiscoveryInfoType | None = None,
):
    """Set up the Modbus binary sensors."""
    sensors = []

    if discovery_info is None:  # pragma: no cover
        return

    for entry in discovery_info[CONF_BINARY_SENSORS]:
        hub = hass.data[MODBUS_DOMAIN][discovery_info[CONF_NAME]]
        sensors.append(ModbusBinarySensor(hub, entry))

    async_add_entities(sensors)


class ModbusBinarySensor(BasePlatform, RestoreEntity, BinarySensorEntity):
    """Modbus binary sensor."""

    def __init__(
        self,
        hub: ModbusHub,
        config: dict[str, Any],
    ) -> None:
        """Initialize the modbus binary sensor."""
        super().__init__(hub, config)
        self.entity_id = ENTITY_ID_FORMAT.format(self._id)

    async def async_added_to_hass(self):
        """Handle entity which will be added."""
        await self.async_base_added_to_hass()
        state = await self.async_get_last_state()
        if state:
            self._value = state.state == STATE_ON
        else:
            self._value = None

    @property
    def is_on(self):
        """Return the state of the sensor."""
        return self._value

    async def async_update(self, now=None):
        """Update the state of the sensor."""
        result = await self._hub.async_pymodbus_call(
            self._slave, self._address, 1, self._input_type
        )
        self.update(result, self._slave, self._input_type, 0)

    async def update(self, result, slaveId, input_type, address):
        """Update the state of the sensor."""
        if result is None:
            self._available = False
            self.async_write_ha_state()
            return
        _LOGGER.debug(
            "update binary_sensor slave=%s, input_type=%s, address=%s -> result=%s",
            slaveId,
            input_type,
            address,
            result.bits[address],
        )
        self._available = True
        self.update_value(result.bits[address] & 1)
