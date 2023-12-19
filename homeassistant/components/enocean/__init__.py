"""Support for EnOcean devices."""
import voluptuous as vol

<<<<<<< HEAD
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_DEVICE
from homeassistant.core import HomeAssistant
=======
from homeassistant import config_entries, core
from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.const import CONF_DEVICE, CONF_TYPE
>>>>>>> 6a32ff977b (integrated enocean over modbus support, added enocean implementation with esp2 support)
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DATA_ENOCEAN, DOMAIN, ENOCEAN_DONGLE, TYPE_IMPLICIT, TYPE_SERIAL
from .dongle import EnOceanDongle

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_DEVICE): cv.string,
                vol.Optional(CONF_TYPE, default=TYPE_SERIAL): vol.In(
                    [
                        TYPE_SERIAL,
                        TYPE_IMPLICIT,
                    ]
                ),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the EnOcean component."""
    # support for text-based configuration (legacy)
    if DOMAIN not in config:
        return True

    if hass.config_entries.async_entries(DOMAIN):
        # We can only have one dongle. If there is already one in the config,
        # there is no need to import the yaml based config.
        return True

    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_IMPORT}, data=config[DOMAIN]
        )
    )

    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up an EnOcean dongle for the given entry."""
    enocean_data = hass.data.setdefault(DATA_ENOCEAN, {})
    if config_entry.data[CONF_TYPE] == TYPE_SERIAL:
        usb_dongle = EnOceanDongle(hass, config_entry.data[CONF_DEVICE])
        await usb_dongle.async_setup()
        enocean_data[ENOCEAN_DONGLE] = usb_dongle

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload EnOcean config entry."""

    enocean_dongle = hass.data[DATA_ENOCEAN][ENOCEAN_DONGLE]
    if enocean_dongle:
        enocean_dongle.unload()
    hass.data.pop(DATA_ENOCEAN)

    return True
