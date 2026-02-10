"""Abstract transport layer for device communication."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum

from calypso.bindings.constants import PlxApiMode, SdbBaudRate, SdbUartCable
from calypso.bindings.types import PLX_MODE_PROP


class TransportMode(StrEnum):
    """Available transport modes."""
    UART_MCU = "uart_mcu"
    SDB_USB = "sdb_usb"
    PCIE_BUS = "pcie_bus"


@dataclass(frozen=True)
class TransportConfig:
    """Base transport configuration."""
    mode: TransportMode


@dataclass(frozen=True)
class UartConfig(TransportConfig):
    """UART via MCU (USB) transport configuration."""
    mode: TransportMode = field(default=TransportMode.UART_MCU, init=False)
    port: int = 0
    baud_rate: SdbBaudRate = SdbBaudRate.BAUD_115200
    cable_type: SdbUartCable = SdbUartCable.USB


@dataclass(frozen=True)
class SdbConfig(TransportConfig):
    """SDB serial port (USB) transport configuration."""
    mode: TransportMode = field(default=TransportMode.SDB_USB, init=False)
    port: int = 0
    baud_rate: SdbBaudRate = SdbBaudRate.BAUD_115200
    cable_type: SdbUartCable = SdbUartCable.UART


@dataclass(frozen=True)
class PcieConfig(TransportConfig):
    """PCIe bus transport configuration."""
    mode: TransportMode = field(default=TransportMode.PCIE_BUS, init=False)


class Transport(ABC):
    """Abstract base for all transport implementations."""

    def __init__(self, config: TransportConfig) -> None:
        self._config = config
        self._connected = False

    @property
    def config(self) -> TransportConfig:
        return self._config

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    @abstractmethod
    def api_mode(self) -> PlxApiMode:
        """Return the PLX API mode for this transport."""

    @abstractmethod
    def build_mode_prop(self) -> PLX_MODE_PROP | None:
        """Build the PLX_MODE_PROP for DeviceFindEx calls.

        Returns None for PCI mode which doesn't need mode props.
        """

    @abstractmethod
    def scan_ports(self) -> list[str]:
        """Scan for available ports/devices on this transport.

        Returns list of port names or device addresses.
        """

    @abstractmethod
    def connect(self) -> None:
        """Establish the transport connection."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close the transport connection."""

    def __enter__(self) -> Transport:
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.disconnect()
