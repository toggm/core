"""Support for EnOcean binary sensors."""
from __future__ import annotations

from enocean.utils import combine_hex
import voluptuous as vol

from homeassistant.components.binary_sensor import (
    DEVICE_CLASS_MOTION,
    DEVICE_CLASS_WINDOW,
    DEVICE_CLASSES_SCHEMA,
    ENTITY_ID_FORMAT,
    PLATFORM_SCHEMA,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.const import (
    CONF_DEVICE_CLASS,
    CONF_ID,
    CONF_NAME,
    DEVICE_CLASS_BATTERY,
    STATE_CLOSED,
    STATE_OFF,
    STATE_ON,
    STATE_OPEN,
)
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .device import EnOceanEntity

DEFAULT_NAME = "EnOcean binary sensor"
DEPENDENCIES = ["enocean"]
EVENT_BUTTON_PRESSED = "button_pressed"

CONF_INVERTED = "inverted"

SENSOR_TYPE_BATTERY = "battery"
SENSOR_TYPE_BUTTON_PRESSED = "button"
SENSOR_TYPE_MOTION = "motion"
SENSOR_TYPE_WINDOW = "window"

SENSOR_TYPES = {
    SENSOR_TYPE_BATTERY: {
        "name": "Battery state",
        "icon": "mdi:battery",
        "class": DEVICE_CLASS_BATTERY,
    },
    SENSOR_TYPE_BUTTON_PRESSED: {
        "name": "Button pressed",
        "icon": "mdi:gesture-tap-button",
        "class": None,
    },
    SENSOR_TYPE_MOTION: {
        "name": "Motion",
        "icon": "mdi:motion",
        "class": DEVICE_CLASS_MOTION,
    },
    SENSOR_TYPE_WINDOW: {
        "name": "Window",
        "icon": "mdi:window",
        "class": DEVICE_CLASS_WINDOW,
    },
}

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_ID): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_DEVICE_CLASS): DEVICE_CLASSES_SCHEMA,
        vol.Optional(CONF_INVERTED, default=0): cv.boolean,
    }
)


def setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the Binary Sensor platform for EnOcean."""
    dev_id = config.get(CONF_ID)
    dev_name = config.get(CONF_NAME)

    sensor_type = config.get(CONF_DEVICE_CLASS)

    if (
        sensor_type == SENSOR_TYPE_BATTERY
        or sensor_type == SENSOR_TYPE_BUTTON_PRESSED
        or sensor_type == SENSOR_TYPE_MOTION
    ):
        inverted = config.get(CONF_INVERTED)
        add_entities(
            [EnOceanOnOffSensor(dev_id, dev_name, sensor_type, inverted=inverted)]
        )
    elif sensor_type == SENSOR_TYPE_WINDOW:
        inverted = config.get(CONF_INVERTED)
        add_entities(
            [EnOceanOpenClosedSensor(dev_id, dev_name, sensor_type, inverted=inverted)]
        )
    else:
        add_entities([EnOceanBinarySensor(dev_id, dev_name, sensor_type)])


class EnOceanBinarySensor(EnOceanEntity, BinarySensorEntity):
    """Representation of EnOcean binary sensors such as wall switches.

    Supported EEPs (EnOcean Equipment Profiles):
    - F6-02-01 (Light and Blind Control - Application Style 2)
    - F6-02-02 (Light and Blind Control - Application Style 1)
    """

    def __init__(self, dev_id, dev_name, device_class):
        """Initialize the EnOcean binary sensor."""
        super().__init__(dev_id, dev_name)
        self._device_class = device_class
        self.which = -1
        self.onoff = -1
        self._attr_unique_id = f"{combine_hex(dev_id)}-{device_class}"
        self.entity_id = ENTITY_ID_FORMAT.format("_".join(str(e) for e in dev_id))

    @property
    def name(self):
        """Return the default name for the binary sensor."""
        return self.dev_name

    @property
    def device_class(self):
        """Return the class of this sensor."""
        return self._device_class

    def value_changed(self, packet):
        """Fire an event with the data that have changed.

        This method is called when there is an incoming packet associated
        with this platform.

        Example packet data:
        - 2nd button pressed
            ['0xf6', '0x10', '0x00', '0x2d', '0xcf', '0x45', '0x30']
        - button released
            ['0xf6', '0x00', '0x00', '0x2d', '0xcf', '0x45', '0x20']
        """
        # Energy Bow
        pushed = None

        if packet.data[6] == 0x30:
            pushed = 1
        elif packet.data[6] == 0x20:
            pushed = 0

        self.schedule_update_ha_state()

        action = packet.data[1]
        if action == 0x70:
            self.which = 0
            self.onoff = 0
        elif action == 0x50:
            self.which = 0
            self.onoff = 1
        elif action == 0x30:
            self.which = 1
            self.onoff = 0
        elif action == 0x10:
            self.which = 1
            self.onoff = 1
        elif action == 0x37:
            self.which = 10
            self.onoff = 0
        elif action == 0x15:
            self.which = 10
            self.onoff = 1
        self.hass.bus.fire(
            EVENT_BUTTON_PRESSED,
            {
                "id": self.dev_id,
                "pushed": pushed,
                "which": self.which,
                "onoff": self.onoff,
            },
        )


class EnOceanOnOffSensor(EnOceanBinarySensor):
    """Representation of an EnOcean on-off sensor device, storing state in data byte 0.0, most often part of a multi-sensor device.

    EEPs (EnOcean Equipment Profiles):
    - D5-00-01
    - A5-10-02 (slide switch of operating panel)
    - A5-10-06 (slide switch of operating panel)
    - A5-10-09 (slide switch of operating panel)
    - A5-10-0D (slide switch of operating panel)
    - A5-10-11 (slide switch of operating panel)
    - A5-10-14 (slide switch of operating panel)
    - A5-10-20 (user intervention on device)
    - A5-10-21 (user intervention on device)
    - A5-10-21 (occupied)
    - A5-11-02 (occupied)
    - A5-11-04 (light on)
    - A5-14-08 (vibration detected)
    - A5-14-0A (vibration detected)
    - A5-20-10 (HVAC unit running state)
    - A5-20-11 (HVAC alarm error state)
    - A5-38-08 (switching command)

    For the following EEPs the inverted flag has to be set to true:
    - A5-08-01 (occupancy button pressed)
    - A5-08-03 (occupancy button pressed)
    - A5-10-01 (occupancy button pressed)
    - A5-10-05 (occupancy button pressed)
    - A5-10-08 (occupancy button pressed)
    - A5-10-0C (occupancy button pressed)
    - A5-10-0D (occupancy button pressed)
    - A5-10-10 (occupancy button pressed)
    - A5-10-13 (occupancy button pressed)
    - A5-10-16 (occupancy button pressed)
    - A5-10-17 (occupancy button pressed)
    - A5-10-18 (occupancy button pressed)
    - A5-10-19 (room occupancied)
    - A5-10-1A (occupancy button pressed)
    - A5-10-1B (occupancy button pressed)
    - A5-10-1C (occupancy button pressed)
    - A5-10-1D (occupancy button pressed)
    - A5-10-1F (occupancy button pressed)
    - A5-13-07 (battery low=0, battery ok=1)
    - A5-13-08 (battery low=0, battery ok=1)
    - A5-20-12 (room occupancied)
    """

    def __init__(
        self,
        dev_id,
        dev_name,
        sensor_type,
        state_on=STATE_ON,
        state_off=STATE_OFF,
        inverted: bool = False,
    ):
        """Initialize the EnOcean on-off sensor device."""
        super().__init__(dev_id, dev_name, sensor_type)
        self._state_on = state_on
        self._state_off = state_off
        self._inverted = inverted

    def value_changed(self, packet):
        """Update the internal state of the sensor."""
        stateOn = (packet.data[0] & 0x01) == 0x01

        if stateOn and not self._inverted:
            self._state = self._state_on
        else:
            self._state = self._state_off

        self.schedule_update_ha_state()


class EnOceanOpenClosedSensor(EnOceanOnOffSensor):
    """Represents an EnOcean Open-Closed sensor device.

    EEPs (EnOcean Equipment Profiles):
    - D5-00-01

    For the following EEPs the inverted flag has to be set to true:
    - A5-10-0A (contact state, 1=Open)
    - A5-10-08 (contact state, 1=Open)
    - A5-14-01 to A5-14-04 (contact state, 1=Open)
    - A5-30-02 (contact state, 1=Open)
    """

    def __init__(self, dev_id, dev_name, sensor_type, inverted: bool = False):
        """Initialize EnOceanOpenClosedSensor."""
        super().__init__(
            dev_id,
            dev_name,
            sensor_type,
            state_on=STATE_OPEN,
            state_off=STATE_CLOSED,
            inverted=inverted,
        )
