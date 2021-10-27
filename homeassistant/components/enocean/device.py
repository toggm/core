"""Representation of an EnOcean device."""
from enocean.protocol.packet import Packet
from enocean.utils import combine_hex

from homeassistant.helpers.entity import Entity

from .const import SIGNAL_RECEIVE_MESSAGE, SIGNAL_SEND_MESSAGE


class EnOceanEntity(Entity):
    """Parent class for all entities associated with the EnOcean component."""

    def __init__(self, dev_id, dev_name="EnOcean device"):
        """Initialize the device."""
        self.dev_id = dev_id
        self.dev_name = dev_name

    async def async_added_to_hass(self):
        """Register callbacks."""
        self.async_on_remove(
            self.hass.helpers.dispatcher.async_dispatcher_connect(
                SIGNAL_RECEIVE_MESSAGE, self._message_received_callback
            )
        )

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"enocean_{self.entity_id}"

    def _message_received_callback(self, packet):
        """Handle incoming packets."""
        if packet.sender_int == combine_hex(self.dev_id):
            self.value_changed(packet)

    def value_changed(self, packet):
        """Update the internal state of the device when a packet arrives."""

    def send_command(self, data, optional, packet_type):
        """Send a command via the EnOcean dongle."""

        packet = Packet(packet_type, data=data, optional=optional)
        self.hass.helpers.dispatcher.dispatcher_send(SIGNAL_SEND_MESSAGE, packet)
