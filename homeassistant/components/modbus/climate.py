"""Support for Generic Modbus Thermostats."""
from __future__ import annotations

from datetime import datetime
import logging
import struct
from typing import Any, cast

from pymodbus.pdu import ModbusResponse

from homeassistant.components.climate import (
    ENTITY_ID_FORMAT,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_ADDRESS,
    CONF_NAME,
    CONF_TEMPERATURE_UNIT,
    PRECISION_TENTHS,
    PRECISION_WHOLE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import get_hub
from .base_platform import BaseStructPlatform
from .const import (
    CALL_TYPE_REGISTER_HOLDING,
    CALL_TYPE_WRITE_REGISTER,
    CALL_TYPE_WRITE_REGISTERS,
    CONF_CLIMATES,
    CONF_HVAC_MODE_AUTO,
    CONF_HVAC_MODE_COOL,
    CONF_HVAC_MODE_DRY,
    CONF_HVAC_MODE_FAN_ONLY,
    CONF_HVAC_MODE_HEAT,
    CONF_HVAC_MODE_HEAT_COOL,
    CONF_HVAC_MODE_OFF,
    CONF_HVAC_MODE_REGISTER,
    CONF_HVAC_MODE_VALUES,
    CONF_HVAC_ONOFF_REGISTER,
    CONF_MAX_TEMP,
    CONF_MIN_TEMP,
    CONF_STEP,
    CONF_TARGET_TEMP,
    DataType,
)
from .modbus import ModbusHub

PARALLEL_UPDATES = 1

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Read configuration and create Modbus climate."""
    if discovery_info is None:
        return

    entities = []
    for entity in discovery_info[CONF_CLIMATES]:
        hub: ModbusHub = get_hub(hass, discovery_info[CONF_NAME])
        entities.append(ModbusThermostat(hub, entity))

    async_add_entities(entities)


class ModbusThermostat(BaseStructPlatform, RestoreEntity, ClimateEntity):
    """Representation of a Modbus Thermostat."""

    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE

    def __init__(
        self,
        hub: ModbusHub,
        config: dict[str, Any],
    ) -> None:
        """Initialize the modbus thermostat."""
        super().__init__(hub, config)
        self.entity_id = ENTITY_ID_FORMAT.format(self._id)
        self._target_temperature_register = config[CONF_TARGET_TEMP]
        self._unit = config[CONF_TEMPERATURE_UNIT]
        if self._scan_group is not None:
            hub.register_update_listener(
                self._scan_group,
                self._slave,
                CALL_TYPE_REGISTER_HOLDING,
                self._target_temperature_register,
                self._target_temperature_register,
                self.async_update_from_result,
            )

        self._attr_current_temperature = None
        self._attr_target_temperature = None
        self._attr_temperature_unit = (
            UnitOfTemperature.FAHRENHEIT
            if self._unit == "F"
            else UnitOfTemperature.CELSIUS
        )
        self._attr_precision = (
            PRECISION_TENTHS if self._precision >= 1 else PRECISION_WHOLE
        )
        self._attr_min_temp = config[CONF_MIN_TEMP]
        self._attr_max_temp = config[CONF_MAX_TEMP]
        self._attr_target_temperature_step = config[CONF_TARGET_TEMP]
        self._attr_target_temperature_step = config[CONF_STEP]

        if CONF_HVAC_MODE_REGISTER in config:
            mode_config = config[CONF_HVAC_MODE_REGISTER]
            self._hvac_mode_register = mode_config[CONF_ADDRESS]
            self._attr_hvac_modes = cast(list[HVACMode], [])
            self._attr_hvac_mode = None
            self._hvac_mode_mapping: list[tuple[int, HVACMode]] = []
            mode_value_config = mode_config[CONF_HVAC_MODE_VALUES]

            for hvac_mode_kw, hvac_mode in (
                (CONF_HVAC_MODE_OFF, HVACMode.OFF),
                (CONF_HVAC_MODE_HEAT, HVACMode.HEAT),
                (CONF_HVAC_MODE_COOL, HVACMode.COOL),
                (CONF_HVAC_MODE_HEAT_COOL, HVACMode.HEAT_COOL),
                (CONF_HVAC_MODE_AUTO, HVACMode.AUTO),
                (CONF_HVAC_MODE_DRY, HVACMode.DRY),
                (CONF_HVAC_MODE_FAN_ONLY, HVACMode.FAN_ONLY),
            ):
                if hvac_mode_kw in mode_value_config:
                    self._hvac_mode_mapping.append(
                        (mode_value_config[hvac_mode_kw], hvac_mode)
                    )
                    self._attr_hvac_modes.append(hvac_mode)

        else:
            # No HVAC modes defined
            self._hvac_mode_register = None
            self._attr_hvac_mode = HVACMode.AUTO
            self._attr_hvac_modes = [HVACMode.AUTO]

        if CONF_HVAC_ONOFF_REGISTER in config:
            self._hvac_onoff_register = config[CONF_HVAC_ONOFF_REGISTER]
            if HVACMode.OFF not in self._attr_hvac_modes:
                self._attr_hvac_modes.append(HVACMode.OFF)
        else:
            self._hvac_onoff_register = None

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await self.async_base_added_to_hass()
        state = await self.async_get_last_state()
        if state and state.attributes.get(ATTR_TEMPERATURE):
            self._attr_target_temperature = float(state.attributes[ATTR_TEMPERATURE])

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if self._hvac_onoff_register is not None:
            # Turn HVAC Off by writing 0 to the On/Off register, or 1 otherwise.
            await self._hub.async_pymodbus_call(
                self._slave,
                self._hvac_onoff_register,
                0 if hvac_mode == HVACMode.OFF else 1,
                CALL_TYPE_WRITE_REGISTER,
            )

        if self._hvac_mode_register is not None:
            # Write a value to the mode register for the desired mode.
            for value, mode in self._hvac_mode_mapping:
                if mode == hvac_mode:
                    await self._hub.async_pymodbus_call(
                        self._slave,
                        self._hvac_mode_register,
                        value,
                        CALL_TYPE_WRITE_REGISTER,
                    )
                    break

        await self.async_update()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        target_temperature = (
            float(kwargs[ATTR_TEMPERATURE]) - self._offset
        ) / self._scale
        if self._data_type in (
            DataType.INT16,
            DataType.INT32,
            DataType.INT64,
            DataType.UINT16,
            DataType.UINT32,
            DataType.UINT64,
        ):
            target_temperature = int(target_temperature)
        as_bytes = struct.pack(self._structure, target_temperature)
        raw_regs = [
            int.from_bytes(as_bytes[i : i + 2], "big")
            for i in range(0, len(as_bytes), 2)
        ]
        registers = self._swap_registers(raw_regs)
        if self._call_active:
            return
        self._call_active = True

        if self._data_type in (
            DataType.INT16,
            DataType.UINT16,
        ):
            result = await self._hub.async_pymodbus_call(
                self._slave,
                self._target_temperature_register,
                int(float(registers[0])),
                CALL_TYPE_WRITE_REGISTER,
            )
        else:
            result = await self._hub.async_pymodbus_call(
                self._slave,
                self._target_temperature_register,
                [int(float(i)) for i in registers],
                CALL_TYPE_WRITE_REGISTERS,
            )
        self._call_active = False
        self._attr_available = result is not None
        await self.async_update()

    async def async_update(self, now: datetime | None = None) -> None:
        """Update Target & Current Temperature."""
        # remark "now" is a dummy parameter to avoid problems with
        # async_track_time_interval
        # do not allow multiple active calls to the same platform
        if self._call_active:
            return
        self._call_active = True

        result = await self._hub.async_pymodbus_call(
            self._slave,
            self._target_temperature_register,
            self._count,
            CALL_TYPE_REGISTER_HOLDING,
        )
        self._call_active = False

        new_target_temperature = await self._async_read_register(result, 0)
        if new_target_temperature != self._attr_target_temperature:
            self._attr_target_temperature = new_target_temperature
            self.async_write_ha_state()

        result = await self._hub.async_pymodbus_call(
            self._slave, self._address, self._count, self._input_type
        )

        new_current_temperature = await self._async_read_register(result, 0)
        if new_current_temperature != self._attr_current_temperature:
            self._attr_current_temperature = new_current_temperature
            self.async_write_ha_state()

        # Read the mode register if defined
        if self._hvac_mode_register is not None:

            result = await self._hub.async_pymodbus_call(
                self._slave,
                self._hvac_mode_register,
                self._count,
                CALL_TYPE_REGISTER_HOLDING,
            )
            hvac_mode = await self._async_read_register(result, 0, raw=True)

            # Translate the value received
            if hvac_mode is not None:
                self._attr_hvac_mode = None
                for value, mode in self._hvac_mode_mapping:
                    if hvac_mode == value:
                        self._attr_hvac_mode = mode
                        break

            self.async_write_ha_state()

        # Read th on/off register if defined. If the value in this
        # register is "OFF", it will take precedence over the value
        # in the mode register.
        if self._hvac_onoff_register is not None:

            result = await self._hub.async_pymodbus_call(
                self._slave,
                self._hvac_onoff_register,
                self._count,
                CALL_TYPE_REGISTER_HOLDING,
            )

            onoff = await self._async_read_register(result, 0, raw=True)
            if onoff == 0:
                self._attr_hvac_mode = HVACMode.OFF
                self.async_write_ha_state()

        self._call_active = False

    async def async_update_from_result(
        self, result: ModbusResponse | None, slaveId: int, input_type: str, address: int
    ) -> None:
        """Update Target & Current Temperature."""
        if result is None:
            self._attr_available = False
            return
        if input_type == CALL_TYPE_REGISTER_HOLDING:
            new_value = await self._async_read_register(result, address)
            if new_value != self._attr_target_temperature:
                self._attr_target_temperature = new_value
                self.async_write_ha_state()
        else:
            new_value = await self._async_read_register(result, address)
            if new_value != self._attr_current_temperature:
                self._attr_current_temperature = new_value
                self.async_write_ha_state()
        self._attr_available = True

    async def _async_read_register(
        self, result: ModbusResponse, address: int, raw: bool | None = False
    ) -> float | None:
        """Read register using the Modbus hub slave."""
        if result is None:
            if self._lazy_errors:
                self._lazy_errors -= 1
                return -1
            self._lazy_errors = self._lazy_error_count
            self._attr_available = False
            return -1

        self._lazy_errors = self._lazy_error_count

        if raw:
            # Return the raw value read from the register, do not change
            # the object's state
            self._attr_available = True
            return int(result.registers[0])

        # The regular handling of the value
        self._value = self.unpack_structure_result(result.registers, address)
        if not self._value:
            self._attr_available = False
            return None
        self._attr_available = True
        return float(self._value)
