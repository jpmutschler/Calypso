"""UART via MCU (USB) transport implementation."""

from __future__ import annotations

from calypso.bindings.constants import PlxApiMode
from calypso.bindings.types import PLX_MODE_PROP
from calypso.exceptions import ConnectionError, TransportError
from calypso.transport.base import Transport, TransportMode, UartConfig
from calypso.utils.logging import get_logger

logger = get_logger(__name__)


class UartTransport(Transport):
    """Transport using UART connection via MCU over USB.

    Uses PLX_API_MODE_SDB with SDB_UART_CABLE_USB.
    """

    def __init__(self, config: UartConfig | None = None) -> None:
        super().__init__(config or UartConfig())

    @property
    def api_mode(self) -> PlxApiMode:
        return PlxApiMode.SDB

    def build_mode_prop(self) -> PLX_MODE_PROP:
        config = self._config
        if not isinstance(config, UartConfig):
            raise TransportError("Invalid config type for UART transport")
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
            "uart_connecting",
            port=self._config.port if isinstance(self._config, UartConfig) else 0,
        )
        self._connected = True
        logger.info("uart_connected")

    def disconnect(self) -> None:
        if not self._connected:
            return
        logger.info("uart_disconnecting")
        self._connected = False
        logger.info("uart_disconnected")
