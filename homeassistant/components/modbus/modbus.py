"""Support for Modbus."""
import asyncio
from datetime import timedelta
import logging
import typing
from typing import Any, Callable, List

from pymodbus.client.sync import ModbusSerialClient, ModbusTcpClient, ModbusUdpClient
from pymodbus.constants import Defaults
from pymodbus.exceptions import ModbusException
from pymodbus.transaction import ModbusRtuFramer

from homeassistant.components.enocean.const import (
    DATA_ENOCEAN,
    DOMAIN as ENOCEAN_DOMAIN,
    ENOCEAN_DONGLE,
)
from homeassistant.const import (
    CONF_DELAY,
    CONF_HOST,
    CONF_METHOD,
    CONF_NAME,
    CONF_PORT,
    CONF_SLAVE,
    CONF_TIMEOUT,
    CONF_TYPE,
    EVENT_HOMEASSISTANT_STOP,
)
from homeassistant.core import callback
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.event import async_call_later, async_track_time_interval

from .const import (
    ATTR_ADDRESS,
    ATTR_HUB,
    ATTR_STATE,
    ATTR_UNIT,
    ATTR_VALUE,
    CALL_TYPE_COIL,
    CALL_TYPE_DISCRETE,
    CALL_TYPE_REGISTER_HOLDING,
    CALL_TYPE_REGISTER_INPUT,
    CALL_TYPE_WRITE_COIL,
    CALL_TYPE_WRITE_COILS,
    CALL_TYPE_WRITE_REGISTER,
    CALL_TYPE_WRITE_REGISTERS,
    CONF_BAUDRATE,
    CONF_BYTESIZE,
    CONF_CLOSE_COMM_ON_ERROR,
    CONF_ENOCEAN,
    CONF_ESP_VERSION,
    CONF_INPUT_ADDRESS,
    CONF_OUTPUT_ADDRESS,
    CONF_PARITY,
    CONF_RETRIES,
    CONF_RETRY_ON_EMPTY,
    CONF_RTUOVERTCP,
    CONF_SCAN_GROUPS,
    CONF_SCAN_INTERVAL_MILLIS,
    CONF_SERIAL,
    CONF_STOPBITS,
    CONF_TCP,
    CONF_UDP,
    DEFAULT_HUB,
    MODBUS_DOMAIN as DOMAIN,
    PLATFORMS,
    SERVICE_WRITE_COIL,
    SERVICE_WRITE_REGISTER,
)

ENTRY_FUNC = "func"
ENTRY_ATTR = "attr"
ENTRY_NAME = "name"

_LOGGER = logging.getLogger(__name__)

PYMODBUS_CALL = {
    CALL_TYPE_COIL: {
        ENTRY_ATTR: "bits",
        ENTRY_NAME: "read_coils",
        ENTRY_FUNC: None,
    },
    CALL_TYPE_DISCRETE: {
        ENTRY_ATTR: "bits",
        ENTRY_NAME: "read_discrete_inputs",
        ENTRY_FUNC: None,
    },
    CALL_TYPE_REGISTER_HOLDING: {
        ENTRY_ATTR: "registers",
        ENTRY_NAME: "read_holding_registers",
        ENTRY_FUNC: None,
    },
    CALL_TYPE_REGISTER_INPUT: {
        ENTRY_ATTR: "registers",
        ENTRY_NAME: "read_input_registers",
        ENTRY_FUNC: None,
    },
    CALL_TYPE_WRITE_COIL: {
        ENTRY_ATTR: "value",
        ENTRY_NAME: "write_coil",
        ENTRY_FUNC: None,
    },
    CALL_TYPE_WRITE_COILS: {
        ENTRY_ATTR: "count",
        ENTRY_NAME: "write_coils",
        ENTRY_FUNC: None,
    },
    CALL_TYPE_WRITE_REGISTER: {
        ENTRY_ATTR: "value",
        ENTRY_NAME: "write_register",
        ENTRY_FUNC: None,
    },
    CALL_TYPE_WRITE_REGISTERS: {
        ENTRY_ATTR: "count",
        ENTRY_NAME: "write_registers",
        ENTRY_FUNC: None,
    },
}


async def async_modbus_setup(
    hass, config, service_write_register_schema, service_write_coil_schema
):
    """Set up Modbus component."""

    hass.data[DOMAIN] = hub_collect = {}
    for conf_hub in config[DOMAIN]:
        my_hub = ModbusHub(hass, conf_hub)
        hub_collect[conf_hub[CONF_NAME]] = my_hub

        # modbus needs to be activated before components are loaded
        # to avoid a racing problem
        if not await my_hub.async_setup():
            return False

        # Register modbus enocean dongle
        if conf_hub.get(CONF_ENOCEAN):
            await my_hub.async_create_and_register_enocean_dongle(
                conf_hub[CONF_ENOCEAN]
            )

        # load platforms
        for component, conf_key in PLATFORMS:
            if conf_key in conf_hub:
                hass.async_create_task(
                    async_load_platform(hass, component, DOMAIN, conf_hub, config)
                )

    async def async_stop_modbus(event):
        """Stop Modbus service."""

        for client in hub_collect.values():
            await client.async_close()
            del client

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_stop_modbus)

    async def async_write_register(service):
        """Write Modbus registers."""
        unit = int(float(service.data[ATTR_UNIT]))
        address = int(float(service.data[ATTR_ADDRESS]))
        value = service.data[ATTR_VALUE]
        client_name = (
            service.data[ATTR_HUB] if ATTR_HUB in service.data else DEFAULT_HUB
        )
        if isinstance(value, list):
            await hub_collect[client_name].async_pymodbus_call(
                unit, address, [int(float(i)) for i in value], CALL_TYPE_WRITE_REGISTERS
            )
        else:
            await hub_collect[client_name].async_pymodbus_call(
                unit, address, int(float(value)), CALL_TYPE_WRITE_REGISTER
            )

    hass.services.async_register(
        DOMAIN,
        SERVICE_WRITE_REGISTER,
        async_write_register,
        schema=service_write_register_schema,
    )

    async def async_write_coil(service):
        """Write Modbus coil."""
        unit = service.data[ATTR_UNIT]
        address = service.data[ATTR_ADDRESS]
        state = service.data[ATTR_STATE]
        client_name = (
            service.data[ATTR_HUB] if ATTR_HUB in service.data else DEFAULT_HUB
        )
        if isinstance(state, list):
            await hub_collect[client_name].async_pymodbus_call(
                unit, address, state, CALL_TYPE_WRITE_COILS
            )
        else:
            await hub_collect[client_name].async_pymodbus_call(
                unit, address, state, CALL_TYPE_WRITE_COIL
            )

    hass.services.async_register(
        DOMAIN, SERVICE_WRITE_COIL, async_write_coil, schema=service_write_coil_schema
    )
    return True


class ModbusUpdateListener:
    """Update listener configuration."""

    def __init__(
        self,
        slave: str,
        input_type: str,
        address: int,
        func: Callable[[Any, str, str, int], None],
    ):
        """Initialize the Modbus update listener configuration."""
        self._slave = slave
        self._input_type = input_type
        self._address = address
        self._func = func

    def notify(self, result, offset):
        """Notify update listener."""
        return self._func(result, self._slave, self._input_type, self._address - offset)


class ModbusHub:
    """Thread safe wrapper class for pymodbus."""

    def __init__(self, hass, client_config):
        """Initialize the Modbus hub."""

        # generic configuration
        self._client = None
        self._async_cancel_listener = None
        self._in_error = False
        self._lock = asyncio.Lock()
        self.hass = hass
        self._config_name = client_config[CONF_NAME]
        self._config_type = client_config[CONF_TYPE]
        self._config_delay = client_config[CONF_DELAY]
        self._pb_call = PYMODBUS_CALL.copy()
        self._pb_class = {
            CONF_SERIAL: ModbusSerialClient,
            CONF_TCP: ModbusTcpClient,
            CONF_UDP: ModbusUdpClient,
            CONF_RTUOVERTCP: ModbusTcpClient,
        }
        self._pb_params = {
            "port": client_config[CONF_PORT],
            "timeout": client_config[CONF_TIMEOUT],
            "reset_socket": client_config[CONF_CLOSE_COMM_ON_ERROR],
            "retries": client_config[CONF_RETRIES],
            "retry_on_empty": client_config[CONF_RETRY_ON_EMPTY],
        }
        if self._config_type == CONF_SERIAL:
            # serial configuration
            self._pb_params.update(
                {
                    "method": client_config[CONF_METHOD],
                    "baudrate": client_config[CONF_BAUDRATE],
                    "stopbits": client_config[CONF_STOPBITS],
                    "bytesize": client_config[CONF_BYTESIZE],
                    "parity": client_config[CONF_PARITY],
                }
            )
        else:
            # network configuration
            self._pb_params["host"] = client_config[CONF_HOST]
            if self._config_type == CONF_RTUOVERTCP:
                self._pb_params["framer"] = ModbusRtuFramer
        self._update_listeners_by_scan_group = dict[
            str, dict[Any, List[ModbusUpdateListener]]
        ]()
        self._scan_groups = dict[str, int]()
        for entry in client_config[CONF_SCAN_GROUPS]:
            name = entry[CONF_NAME]
            self._scan_groups[name] = int(entry[CONF_SCAN_INTERVAL_MILLIS])
            self._update_listeners_by_scan_group[name] = dict[
                Any, List[ModbusUpdateListener]
            ]()

        Defaults.Timeout = client_config[CONF_TIMEOUT]

    def _log_error(self, text: str, error_state=True):
        log_text = f"Pymodbus: {text}"
        if self._in_error:
            _LOGGER.debug(log_text)
        else:
            _LOGGER.error(log_text)
            self._in_error = error_state

    async def async_setup(self):
        """Set up pymodbus client."""
        try:
            self._client = self._pb_class[self._config_type](**self._pb_params)
        except ModbusException as exception_error:
            self._log_error(str(exception_error), error_state=False)
            return False

        for entry in self._pb_call.values():
            entry[ENTRY_FUNC] = getattr(self._client, entry[ENTRY_NAME])

        async with self._lock:
            if not await self.hass.async_add_executor_job(self._pymodbus_connect):
                self._log_error("initial connect failed, no retry", error_state=False)
                return False

        # Start counting down to allow modbus requests.
        if self._config_delay:
            self._async_cancel_listener = async_call_later(
                self.hass, self._config_delay, self.async_end_delay
            )
        else:
            self.start_update_listener()

        return True

    async def async_create_and_register_enocean_dongle(
        self, config: typing.Dict[str, Any]
    ):
        """Create and register enocean dongle."""
        from .modbusenoceandongle import ModbusEnOceanDongle
        from .modbusenoceanwago750adapter import ModbusEnOceanWago750Adapter

        input_address = config[CONF_INPUT_ADDRESS]
        output_address = config[CONF_OUTPUT_ADDRESS]
        slave = config[CONF_SLAVE]
        esp_version = config.get(CONF_ESP_VERSION, 3)
        # Change as soon as other modbus enocean adapters are supported
        adapter = ModbusEnOceanWago750Adapter(
            self, slave, input_address, output_address
        )
        dongle = ModbusEnOceanDongle(self.hass, adapter, esp_version)
        # Register dongle if not another enocean dongle was registered yet
        if self.hass.config_entries.async_entries(ENOCEAN_DOMAIN):
            _LOGGER.debug("Register modbus enocean dongle")
            enocean_data = self.hass.data.setdefault(DATA_ENOCEAN, {})
            await dongle.async_setup()
            enocean_data[ENOCEAN_DONGLE] = dongle

    @callback
    def async_end_delay(self, args):
        """End startup delay."""
        self._async_cancel_listener = None
        self._config_delay = 0
        self.start_update_listener()

    def start_update_listener(self):
        """Possibly start monitoring of updates."""
        for (scan_group, interval_millis) in self._scan_groups.items():
            _LOGGER.debug(
                "Register scan listener scan_group=%s, interval_millis=%s",
                scan_group,
                interval_millis,
            )
            async_track_time_interval(
                self.hass,
                self.async_update_function(scan_group),
                timedelta(milliseconds=interval_millis),
            )

    def register_update_listener(
        self,
        scan_group,
        slave,
        input_type,
        address,
        func: Callable[[Any, str, str, int], None],
    ):
        """Register update listener."""
        _LOGGER.debug(
            "Register update listener slave=%s, input_type=%s, address=%s in scan_group=%s",
            slave,
            input_type,
            address,
            scan_group,
        )
        update_listeners = self._update_listeners_by_scan_group[scan_group]
        key = (slave, input_type)
        if key in update_listeners:
            update_listeners[key].append(
                ModbusUpdateListener(slave, input_type, address, func)
            )
        else:
            update_listeners[key] = [
                ModbusUpdateListener(slave, input_type, address, func)
            ]

    def async_update_function(self, scan_group):
        """Return async update function per scan group."""

        @callback
        async def async_update(now=None):
            """Update the state of all entities in a given scan group."""
            # remark "now" is a dummy parameter to avoid problems with
            # async_track_time_interval
            _LOGGER.debug(
                "async_update: scan_group=%s, items=%s",
                scan_group,
                self._update_listeners_by_scan_group[scan_group],
            )

            for (
                (slave, input_type),
                listeners,
            ) in self._update_listeners_by_scan_group[scan_group].items():
                min_address = 100000
                max_address = 0
                for listener in listeners:
                    min_address = min(min_address, listener._address)
                    max_address = max(max_address, listener._address)
                _LOGGER.debug(
                    "query modbus: scan_group=%s, slave=%s, minAdress=%s, maxAdress=%s, input_type=%s",
                    scan_group,
                    slave,
                    min_address,
                    max_address,
                    input_type,
                )
                result = await self.async_pymodbus_call(
                    slave, min_address, max_address + 1 - min_address, input_type
                )
                for listener in listeners:
                    await listener.notify(result, min_address)

        return async_update

    def _pymodbus_close(self):
        """Close sync. pymodbus."""
        if self._client:
            try:
                self._client.close()
            except ModbusException as exception_error:
                self._log_error(str(exception_error))
        self._client = None

    async def async_close(self):
        """Disconnect client."""
        if self._async_cancel_listener:
            self._async_cancel_listener()
            self._async_cancel_listener = None

        async with self._lock:
            return await self.hass.async_add_executor_job(self._pymodbus_close)

    def _pymodbus_connect(self):
        """Connect client."""
        try:
            return self._client.connect()
        except ModbusException as exception_error:
            self._log_error(str(exception_error), error_state=False)
            return False

    def _pymodbus_call(self, unit, address, value, use_call):
        """Call sync. pymodbus."""
        kwargs = {"unit": unit} if unit else {}
        try:
            result = self._pb_call[use_call][ENTRY_FUNC](address, value, **kwargs)
        except ModbusException as exception_error:
            self._log_error(str(exception_error))
            return None
        if not hasattr(result, self._pb_call[use_call][ENTRY_ATTR]):
            self._log_error(str(result))
            return None
        self._in_error = False
        return result

    async def async_pymodbus_call(self, unit, address, value, use_call):
        """Convert async to sync pymodbus call."""
        if self._config_delay:
            return None
        if not self._client:
            return None
        if not self._client.is_socket_open():
            return None
        async with self._lock:
            result = await self.hass.async_add_executor_job(
                self._pymodbus_call, unit, address, value, use_call
            )
            if self._config_type == "serial":
                # small delay until next request/response
                await asyncio.sleep(30 / 1000)
            return result
