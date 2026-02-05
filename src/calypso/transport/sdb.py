"""SDB serial port (USB) transport implementation."""

from __future__ import annotations

from calypso.bindings.constants import PlxApiMode
from calypso.bindings.types import PLX_MODE_PROP
from calypso.exceptions import TransportError
from calypso.transport.base import SdbConfig, Transport
from calypso.utils.logging import get_logger

logger = get_logger(__name__)


class SdbTransport(Transport):
    """Transport using SDB serial debug port over USB.

    Uses PLX_API_MODE_SDB with SDB_UART_CABLE_UART.
    """

    def __init__(self, config: SdbConfig | None = None) -> None:
        super().__init__(config or SdbConfig())

    @property
    def api_mode(self) -> PlxApiMode:
        return PlxApiMode.SDB

    def build_mode_prop(self) -> PLX_MODE_PROP:
        config = self._config
        if not isinstance(config, SdbConfig):
            raise TransportError("Invalid config type for SDB transport")
        prop = PLX_MODE_PROP()
        prop.Sdb.Port = config.port
        prop.Sdb.Baud = config.baud_rate.value
        prop.Sdb.Cable = config.cable_type.value
        return prop

    def scan_ports(self) -> list[str]:
        """Scan for available COM/ttyUSB ports."""
        try:
            from serial.tools.list_ports import comports
            return [p.device for p in comports()]
        except ImportError:
            logger.warning("pyserial_not_available", msg="Install pyserial for port scanning")
            return []

    def connect(self) -> None:
        if self._connected:
            return
        logger.info(
            "sdb_connecting",
            port=self._config.port if isinstance(self._config, SdbConfig) else 0,
        )
        self._connected = True
        logger.info("sdb_connected")

    def disconnect(self) -> None:
        if not self._connected:
            return
        logger.info("sdb_disconnecting")
        self._connected = False
        logger.info("sdb_disconnected")
