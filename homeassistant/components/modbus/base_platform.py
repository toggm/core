"""Base implementation for all modbus platforms."""
from __future__ import annotations

from abc import abstractmethod
from datetime import timedelta
import logging
from typing import Any

from homeassistant.const import (
    CONF_ADDRESS,
    CONF_COMMAND_OFF,
    CONF_COMMAND_ON,
    CONF_DELAY,
    CONF_DEVICE_CLASS,
    CONF_ID,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    CONF_SLAVE,
    STATE_ON,
)
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CALL_TYPE_COIL,
    CALL_TYPE_WRITE_COIL,
    CALL_TYPE_WRITE_REGISTER,
    CONF_INPUT_TYPE,
    CONF_SCAN_GROUP,
    CONF_STATE_OFF,
    CONF_STATE_ON,
    CONF_VERIFY,
    CONF_WRITE_TYPE,
)
from .modbus import ModbusHub

PARALLEL_UPDATES = 1
_LOGGER = logging.getLogger(__name__)


class BasePlatform(Entity):
    """Base for readonly platforms."""

    def __init__(self, hub: ModbusHub, entry: dict[str, Any]) -> None:
        """Initialize the Modbus binary sensor."""
        self._hub = hub
        self._id = entry[CONF_ID]
        self._name = entry[CONF_NAME]
        self._slave = entry.get(CONF_SLAVE)
        self._address = int(entry[CONF_ADDRESS])
        self._device_class = entry.get(CONF_DEVICE_CLASS)
        self._input_type = entry[CONF_INPUT_TYPE]
        self._value = None
        self._available = True
        self._scan_interval = int(entry[CONF_SCAN_INTERVAL])
        self._scan_group = entry.get(CONF_SCAN_GROUP)
        self._unique_id = f"modbus_{hub._config_name}_{self._slave}_{self._input_type}_{self._address}"

    def init_update_listeners(self):
        """Initialize update listeners."""
        if (
            self._slave is not None
            and self._input_type
            and self._address is not None
            and self._scan_group is not None
        ):
            self._hub.register_update_listener(
                self._scan_group,
                self._slave,
                self._input_type,
                self._address,
                self.update,
            )

    @abstractmethod
    async def update(self, result, slaveId, input_type, address):
        """Virtual function to be overwritten."""

    async def async_update(self, now=None):
        """Virtual function to be overwritten."""

    async def async_base_added_to_hass(self):
        """Handle entity which will be added."""
        self.init_update_listeners()
        if self._scan_interval > 0 and self._scan_group is None:
            async_track_time_interval(
                self.hass, self.async_update, timedelta(seconds=self._scan_interval)
            )

    @property
    def unique_id(self) -> str | None:
        """Return a unique ID."""
        return self._unique_id

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def should_poll(self):
        """Return True if entity has to be polled for state."""
        return False

    @property
    def device_class(self) -> str | None:
        """Return the device class of the sensor."""
        return self._device_class

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._available

    def update_value(self, new_value):
        """Update value and write state if value changed."""
        self._available = True
        if new_value != self._value:
            self._value = new_value
            self.async_write_ha_state()


class BaseSwitch(BasePlatform, RestoreEntity):
    """Base class representing a Modbus switch."""

    def __init__(self, hub: ModbusHub, config: dict) -> None:
        """Initialize the switch."""
        config[CONF_INPUT_TYPE] = ""
        super().__init__(hub, config)
        self._is_on = None
        if config[CONF_WRITE_TYPE] == CALL_TYPE_COIL:
            self._write_type = CALL_TYPE_WRITE_COIL
        else:
            self._write_type = CALL_TYPE_WRITE_REGISTER
        self.command_on = config[CONF_COMMAND_ON]
        self._command_off = config[CONF_COMMAND_OFF]
        if CONF_VERIFY in config:
            if config[CONF_VERIFY] is None:
                config[CONF_VERIFY] = {}
            self._verify_active = True
            self._verify_delay = config[CONF_VERIFY].get(CONF_DELAY, 0)
            self._verify_address = config[CONF_VERIFY].get(
                CONF_ADDRESS, config[CONF_ADDRESS]
            )
            self._verify_type = config[CONF_VERIFY].get(
                CONF_INPUT_TYPE, config[CONF_WRITE_TYPE]
            )
            self._state_on = config[CONF_VERIFY].get(CONF_STATE_ON, self.command_on)
            self._state_off = config[CONF_VERIFY].get(CONF_STATE_OFF, self._command_off)
        else:
            self._verify_active = False

    def init_update_listeners(self):
        """Initialize update listeners."""
        if (
            self._verify_active is True
            and self._slave is not None
            and self._verify_type
            and self._verify_address is not None
            and self._scan_group is not None
        ):
            self._hub.register_update_listener(
                self._scan_group,
                self._slave,
                self._verify_type,
                self._verify_address,
                self.update,
            )
        else:
            super().init_update_listeners()

    async def async_added_to_hass(self):
        """Handle entity which will be added."""
        await self.async_base_added_to_hass()
        state = await self.async_get_last_state()
        if state:
            self._is_on = state.state == STATE_ON

    @property
    def is_on(self):
        """Return true if switch is on."""
        return self._is_on

    async def async_turn(self, command):
        """Evaluate switch result."""
        result = await self._hub.async_pymodbus_call(
            self._slave, self._address, command, self._write_type
        )
        if result is None:
            self._available = False
            self.async_write_ha_state()
            return

        self._available = True
        if not self._verify_active:
            self._is_on = command == self.command_on
            self.async_write_ha_state()
            return

        if self._verify_delay:
            async_call_later(self.hass, self._verify_delay, self.async_update)
        else:
            await self.async_update()

    async def async_turn_off(self, **kwargs):
        """Set switch off."""
        await self.async_turn(self._command_off)

    async def async_update(self, now=None):
        """Update the entity state."""
        # remark "now" is a dummy parameter to avoid problems with
        # async_track_time_interval
        if not self._verify_active:
            self._available = True
            self.async_write_ha_state()
            return

        result = await self._hub.async_pymodbus_call(
            self._slave, self._verify_address, 1, self._verify_type
        )
        await self.update(result, self._slave, self._verify_type, 0)

    async def update(self, result, slaveId, input_type, address):
        """Update the entity state."""
        if not self._verify_active:
            self._available = True
            self.async_write_ha_state()
            return

        if result is None:
            self._available = False
            self.async_write_ha_state()
            return

        self._available = True
        if result.bits:
            _LOGGER.debug(
                "update switch slave=%s, input_type=%s, address=%s -> result=%s",
                slaveId,
                input_type,
                address,
                result.bits[address],
            )
            self._is_on = bool(result.bits[address] & 1)
        elif result.registers:
            _LOGGER.debug(
                "update switch slave=%s, input_type=%s, address=%s -> result=%s",
                slaveId,
                input_type,
                address,
                result.registers,
            )
            value = int(result.registers[address])
            if value == self._state_on:
                self._is_on = True
            elif value == self._state_off:
                self._is_on = False
            elif value is not None:
                _LOGGER.error(
                    "Unexpected response from modbus device slave %s register %s, got 0x%2x",
                    self._slave,
                    self._verify_address,
                    value,
                )
        self.async_write_ha_state()
