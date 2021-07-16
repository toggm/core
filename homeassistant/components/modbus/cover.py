"""Support for Modbus covers."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import (
    ENTITY_ID_FORMAT,
    SUPPORT_CLOSE,
    SUPPORT_OPEN,
    CoverEntity,
)
from homeassistant.const import (
    CONF_ADDRESS,
    CONF_COVERS,
    CONF_NAME,
    STATE_CLOSED,
    STATE_CLOSING,
    STATE_OPEN,
    STATE_OPENING,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .base_platform import BasePlatform
from .const import (
    CALL_TYPE_COIL,
    CALL_TYPE_WRITE_COIL,
    CALL_TYPE_WRITE_REGISTER,
    CONF_ADDRESS_CLOSE,
    CONF_STATE_CLOSED,
    CONF_STATE_CLOSING,
    CONF_STATE_OPEN,
    CONF_STATE_OPENING,
    CONF_STATUS_REGISTER,
    CONF_STATUS_REGISTER_TYPE,
    CONF_VERIFY,
    MODBUS_DOMAIN,
)
from .modbus import ModbusHub

PARALLEL_UPDATES = 1
_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities,
    discovery_info: DiscoveryInfoType | None = None,
):
    """Read configuration and create Modbus cover."""
    if discovery_info is None:  # pragma: no cover
        return

    covers = []
    for cover in discovery_info[CONF_COVERS]:
        hub: ModbusHub = hass.data[MODBUS_DOMAIN][discovery_info[CONF_NAME]]
        covers.append(ModbusCover(hub, cover))

    async_add_entities(covers)


class ModbusCover(BasePlatform, CoverEntity, RestoreEntity):
    """Representation of a Modbus cover."""

    def __init__(
        self,
        hub: ModbusHub,
        config: dict[str, Any],
    ) -> None:
        """Initialize the modbus cover."""
        super().__init__(hub, config)
        self.entity_id = ENTITY_ID_FORMAT.format(self._id)
        self._state_closed = config[CONF_STATE_CLOSED]
        self._state_closing = config[CONF_STATE_CLOSING]
        self._state_open = config[CONF_STATE_OPEN]
        self._state_opening = config[CONF_STATE_OPENING]
        self._status_register = config.get(CONF_STATUS_REGISTER)
        self._status_register_type = config[CONF_STATUS_REGISTER_TYPE]

        # If we read cover status from coil, and not from optional status register,
        # we interpret boolean value False as closed cover, and value True as open cover.
        # Intermediate states are not supported in such a setup.
        if self._input_type == CALL_TYPE_COIL:
            self._write_type = CALL_TYPE_WRITE_COIL
            self._write_address_open = self._address
            self._write_address_close = config.get(CONF_ADDRESS_CLOSE, self._address)
            if self._status_register is None:
                self._state_closed = False
                self._state_open = True
                if self._write_address_open != self._write_address_close:
                    # If we configured two coil addressed we can identity closing and opening state,
                    # but not final state closed or open as we might stop the closing or opening process
                    self._state_closing = -1
                    self._state_opening = -2

                    self._address_open = self._write_address_open
                    self._address_close = self._write_address_close
                else:
                    self._state_closing = None
                    self._state_opening = None
        else:
            # If we read cover status from the main register (i.e., an optional
            # status register is not specified), we need to make sure the register_type
            # is set to "holding".
            self._write_type = CALL_TYPE_WRITE_REGISTER
            self._write_address_open = self._address
            self._write_address_close = self._address
            self._address_open = self._address
            self._address_close = self._address

        if self._status_register:
            self._address_open = self._status_register
            self._address_close = self._status_register
            self._input_type = self._status_register_type
        elif CONF_VERIFY in config:
            self._address_open = config[CONF_VERIFY].get(CONF_ADDRESS)
            self._address_close = config[CONF_VERIFY].get(
                CONF_ADDRESS_CLOSE, config[CONF_VERIFY].get(CONF_ADDRESS)
            )

    def init_update_listeners(self):
        """Initialize update listeners."""
        # override default behaviour as we register based on the verify address
        if self._slave and self._input_type and self._scan_group is not None:
            if self._address_open is not None:
                self._hub.register_update_listener(
                    self._scan_group,
                    self._slave,
                    self._input_type,
                    self._address_open,
                    self.update,
                )

            if self._address_close is not None:
                self._hub.register_update_listener(
                    self._scan_group,
                    self._slave,
                    self._input_type,
                    self._address_close,
                    self.update,
                )

    async def async_added_to_hass(self):
        """Handle entity which will be added."""
        await self.async_base_added_to_hass()
        state = await self.async_get_last_state()
        if state:
            convert = {
                STATE_CLOSED: self._state_closed,
                STATE_CLOSING: self._state_closing,
                STATE_OPENING: self._state_opening,
                STATE_OPEN: self._state_open,
                STATE_UNAVAILABLE: None,
                STATE_UNKNOWN: None,
            }
            self._value = convert[state.state]

    @property
    def supported_features(self):
        """Flag supported features."""
        return SUPPORT_OPEN | SUPPORT_CLOSE

    @property
    def is_opening(self):
        """Return if the cover is opening or not."""
        return self._value == self._state_opening

    @property
    def is_closing(self):
        """Return if the cover is closing or not."""
        return self._value == self._state_closing

    @property
    def is_closed(self):
        """Return if the cover is closed or not."""
        return self._value == self._state_closed

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open cover."""
        if (
            self._write_type == CALL_TYPE_WRITE_COIL
            and self._write_address_close != self._write_address_open
        ):
            # If we use two different coils to control up and down, we need to ensure not both coils
            # get On state at the same time, therefore we use value not stored in state object
            # Write inverted state to opposite coil
            await self._hub.async_pymodbus_call(
                self._slave, self._write_address_close, False, self._write_type
            )
            result = await self._hub.async_pymodbus_call(
                self._slave, self._write_address_open, True, self._write_type
            )
        else:
            result = await self._hub.async_pymodbus_call(
                self._slave,
                self._write_address_open,
                self._state_open,
                self._write_type,
            )
        self._available = result is not None
        await self.async_update()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close cover."""
        if (
            self._write_type == CALL_TYPE_WRITE_COIL
            and self._write_address_close != self._write_address_open
        ):
            # If we use two different coils to control up and down, we need to ensure not both coils
            # get On state at the same time, therefore we use value not stored in state object
            # Write inverted state to opposite coil
            await self._hub.async_pymodbus_call(
                self._slave, self._write_address_open, False, self._write_type
            )
            result = await self._hub.async_pymodbus_call(
                self._slave, self._write_address_close, True, self._write_type
            )
        else:
            result = await self._hub.async_pymodbus_call(
                self._slave,
                self._write_address_close,
                self._state_closed,
                self._write_type,
            )
        self._available = result is not None
        await self.async_update()

    async def async_stop_cover(self, **kwargs):
        """Stop the cover."""
        if (
            self._write_type == CALL_TYPE_WRITE_COIL
            and self._write_address_close != self._write_address_open
        ):
            # Stop is only possible if cover is configured with two coil addresses
            await self._hub.async_pymodbus_call(
                self._slave, self._write_address_open, False, self._write_type
            )
            result = await self._hub.async_pymodbus_call(
                self._slave, self._write_address_close, False, self._write_type
            )
            self._available = result is not None
        await self.async_update()

    async def async_update(self, now=None):
        """Update the state of the cover."""
        # remark "now" is a dummy parameter to avoid problems with
        # async_track_time_interval
        start_address = min(self._address_open, self._address_close)
        end_address = min(self._address_open, self._address_close)
        result = await self._hub.async_pymodbus_call(
            self._slave, start_address, end_address - start_address, self._input_type
        )
        self.update(result, self._slave, self._input_type, 0)

    async def update(self, result, slaveId, input_type, address):
        """Update the state of the cover."""
        if result is None:
            self._available = False
            self.async_write_ha_state()
            return None
        self._available = True
        if input_type == CALL_TYPE_COIL:
            _LOGGER.debug(
                "update cover slave=%s, input_type=%s, address=%s -> result=%s",
                slaveId,
                input_type,
                address,
                result.bits,
            )
            if self._address_open != self._address_close:
                # Get min_address of open and close, address will be relative to this address
                start_address = min(self._address_open, self._address_close)
                opening = bool(
                    result.bits[address + (self._address_open - start_address)] & 1
                )
                closing = bool(
                    result.bits[address + (self._address_close - start_address)] & 1
                )
                if opening:
                    self.update_value(self._state_opening)
                elif closing:
                    self.update_value(self._state_closing)
                else:
                    # we assume either closed or closing based on previous statue
                    if self._value == self._state_opening:
                        self.update_value(self._state_open)
                    elif self._value == self._state_closing:
                        self.update_value(self._state_closed)
            else:
                self.update_value(bool(result.bits[address] & 1))
        else:
            _LOGGER.debug(
                "update cover slave=%s, input_type=%s, address=%s -> result=%s",
                slaveId,
                input_type,
                address,
                result.registers,
            )
            self.update_value(int(result.registers[address]))
