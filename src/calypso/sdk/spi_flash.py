"""SPI flash operations wrapping PLX SDK SPI functions."""

from __future__ import annotations

import ctypes
from ctypes import byref, c_int, c_uint8, c_uint32

from calypso.bindings.library import get_library
from calypso.bindings.types import PEX_SPI_OBJ, PLX_DEVICE_OBJECT
from calypso.exceptions import check_status


def get_properties(device: PLX_DEVICE_OBJECT, chip_select: int = 0) -> PEX_SPI_OBJ:
    """Get SPI flash properties.

    Args:
        device: Open device handle.
        chip_select: SPI chip select index.

    Returns:
        SPI flash object with properties.
    """
    lib = get_library()
    spi = PEX_SPI_OBJ()
    status = lib.PlxPci_SpiFlashPropGet(byref(device), chip_select, byref(spi))
    check_status(status, "SpiFlashPropGet")
    return spi


def read_buffer(
    device: PLX_DEVICE_OBJECT,
    spi: PEX_SPI_OBJ,
    offset: int,
    size: int,
) -> bytes:
    """Read a buffer from SPI flash.

    Returns:
        Bytes read from flash.
    """
    lib = get_library()
    buf = (c_uint8 * size)()
    status = lib.PlxPci_SpiFlashReadBuffer(byref(device), byref(spi), offset, buf, size)
    check_status(status, f"SpiFlashReadBuffer(offset=0x{offset:X}, size={size})")
    return bytes(buf)


def write_buffer(
    device: PLX_DEVICE_OBJECT,
    spi: PEX_SPI_OBJ,
    offset: int,
    data: bytes,
) -> None:
    """Write a buffer to SPI flash."""
    lib = get_library()
    buf = (c_uint8 * len(data))(*data)
    status = lib.PlxPci_SpiFlashWriteBuffer(byref(device), byref(spi), offset, buf, len(data))
    check_status(status, f"SpiFlashWriteBuffer(offset=0x{offset:X}, size={len(data)})")


def read_dword(device: PLX_DEVICE_OBJECT, spi: PEX_SPI_OBJ, offset: int) -> int:
    """Read a single 32-bit value from SPI flash."""
    lib = get_library()
    status = c_int()
    value = lib.PlxPci_SpiFlashReadByOffset(byref(device), byref(spi), offset, byref(status))
    check_status(status.value, f"SpiFlashReadByOffset(offset=0x{offset:X})")
    return value


def write_dword(device: PLX_DEVICE_OBJECT, spi: PEX_SPI_OBJ, offset: int, value: int) -> None:
    """Write a single 32-bit value to SPI flash."""
    lib = get_library()
    status = lib.PlxPci_SpiFlashWriteByOffset(byref(device), byref(spi), offset, value)
    check_status(status, f"SpiFlashWriteByOffset(offset=0x{offset:X})")


def erase(
    device: PLX_DEVICE_OBJECT,
    spi: PEX_SPI_OBJ,
    offset: int,
    wait_complete: bool = True,
) -> None:
    """Erase SPI flash sector(s)."""
    lib = get_library()
    status = lib.PlxPci_SpiFlashErase(byref(device), byref(spi), offset, int(wait_complete))
    check_status(status, f"SpiFlashErase(offset=0x{offset:X})")


def get_flash_status(device: PLX_DEVICE_OBJECT, spi: PEX_SPI_OBJ) -> None:
    """Update SPI object with current flash status."""
    lib = get_library()
    status = lib.PlxPci_SpiFlashGetStatus(byref(device), byref(spi))
    check_status(status, "SpiFlashGetStatus")
