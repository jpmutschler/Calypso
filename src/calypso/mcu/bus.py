"""Bus abstraction layer for I2C/I3C access through the MCU.

Provides Bus ABC and concrete I2cBus/I3cBus classes that bind a
McuClient to a specific connector+channel pair.  MCTP transport
and other consumers take a Bus instance rather than raw McuClient,
enabling mock buses for testing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from calypso.mcu.client import McuClient
from calypso.utils.logging import get_logger

logger = get_logger(__name__)


class Bus(ABC):
    """Abstract bus interface for byte-level read/write."""

    @property
    @abstractmethod
    def bus_type(self) -> str:
        """Return 'i2c' or 'i3c'."""

    @property
    @abstractmethod
    def connector(self) -> int:
        """Connector index this bus is bound to."""

    @property
    @abstractmethod
    def channel(self) -> str:
        """Channel this bus is bound to."""

    @abstractmethod
    def read(self, address: int, register: int, count: int) -> list[int]:
        """Read *count* bytes from *address* at *register*."""

    @abstractmethod
    def write(self, address: int, data: list[int]) -> bool:
        """Write *data* bytes to *address*."""

    @abstractmethod
    def write_register(self, address: int, register: int, data: list[int]) -> bool:
        """Write *data* bytes to *address* at *register*."""


class I2cBus(Bus):
    """I2C bus bound to a specific connector and channel."""

    def __init__(self, client: McuClient, connector: int, channel: str) -> None:
        self._client = client
        self._connector = connector
        self._channel = channel

    @property
    def bus_type(self) -> str:
        return "i2c"

    @property
    def connector(self) -> int:
        return self._connector

    @property
    def channel(self) -> str:
        return self._channel

    def read(self, address: int, register: int, count: int) -> list[int]:
        return self._client.i2c_read(
            address=address,
            connector=self._connector,
            channel=self._channel,
            read_bytes=count,
            register=register,
        )

    def write(self, address: int, data: list[int]) -> bool:
        return self._client.i2c_write(
            address=address,
            connector=self._connector,
            channel=self._channel,
            data=data,
        )

    def write_register(self, address: int, register: int, data: list[int]) -> bool:
        return self._client.i2c_write(
            address=address,
            connector=self._connector,
            channel=self._channel,
            data=[register] + data,
        )


class I3cBus(Bus):
    """I3C bus bound to a specific connector and channel."""

    def __init__(self, client: McuClient, connector: int, channel: str) -> None:
        self._client = client
        self._connector = connector
        self._channel = channel

    @property
    def bus_type(self) -> str:
        return "i3c"

    @property
    def connector(self) -> int:
        return self._connector

    @property
    def channel(self) -> str:
        return self._channel

    def read(self, address: int, register: int, count: int) -> list[int]:
        resp = self._client.i3c_read(
            address=address,
            connector=self._connector,
            channel=self._channel,
            read_bytes=count,
            register=register,
        )
        return resp.data

    def write(self, address: int, data: list[int]) -> bool:
        return self._client.i3c_write(
            address=address,
            connector=self._connector,
            channel=self._channel,
            data=data,
        )

    def write_register(self, address: int, register: int, data: list[int]) -> bool:
        return self._client.i3c_write(
            address=address,
            connector=self._connector,
            channel=self._channel,
            data=data,
            register=register,
        )
