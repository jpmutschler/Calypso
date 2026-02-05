"""EEPROM access operations wrapping PLX SDK EEPROM functions."""

from __future__ import annotations

from ctypes import byref, c_int, c_int8, c_uint8, c_uint16, c_uint32

from calypso.bindings.library import get_library
from calypso.bindings.types import PLX_DEVICE_OBJECT
from calypso.exceptions import check_status


def probe(device: PLX_DEVICE_OBJECT) -> bool:
    """Check if an EEPROM is present and accessible.

    Returns:
        True if EEPROM is present.
    """
    lib = get_library()
    status = c_int()
    result = lib.PlxPci_EepromProbe(byref(device), byref(status))
    check_status(status.value, "EepromProbe")
    return bool(result)


def get_status(device: PLX_DEVICE_OBJECT) -> int:
    """Get EEPROM presence/validity status.

    Returns:
        PLX_EEPROM_STATUS value (0=none, 1=valid, 2=invalid/blank).
    """
    lib = get_library()
    status = c_int()
    result = lib.PlxPci_EepromPresent(byref(device), byref(status))
    check_status(status.value, "EepromPresent")
    return result


def read_32(device: PLX_DEVICE_OBJECT, offset: int) -> int:
    """Read a 32-bit value from EEPROM.

    Args:
        device: Open device handle.
        offset: EEPROM byte offset.

    Returns:
        32-bit value at the given offset.
    """
    lib = get_library()
    value = c_uint32()
    status = lib.PlxPci_EepromReadByOffset(byref(device), offset, byref(value))
    check_status(status, f"EepromRead(offset=0x{offset:X})")
    return value.value


def write_32(device: PLX_DEVICE_OBJECT, offset: int, value: int) -> None:
    """Write a 32-bit value to EEPROM."""
    lib = get_library()
    status = lib.PlxPci_EepromWriteByOffset(byref(device), offset, value)
    check_status(status, f"EepromWrite(offset=0x{offset:X})")


def read_16(device: PLX_DEVICE_OBJECT, offset: int) -> int:
    """Read a 16-bit value from EEPROM."""
    lib = get_library()
    value = c_uint16()
    status = lib.PlxPci_EepromReadByOffset_16(byref(device), offset, byref(value))
    check_status(status, f"EepromRead16(offset=0x{offset:X})")
    return value.value


def write_16(device: PLX_DEVICE_OBJECT, offset: int, value: int) -> None:
    """Write a 16-bit value to EEPROM."""
    lib = get_library()
    status = lib.PlxPci_EepromWriteByOffset_16(byref(device), offset, value)
    check_status(status, f"EepromWrite16(offset=0x{offset:X})")


def get_crc(device: PLX_DEVICE_OBJECT) -> tuple[int, int]:
    """Get EEPROM CRC value and status.

    Returns:
        Tuple of (crc_value, crc_status).
    """
    lib = get_library()
    crc = c_uint32()
    crc_status = c_uint8()
    status = lib.PlxPci_EepromCrcGet(byref(device), byref(crc), byref(crc_status))
    check_status(status, "EepromCrcGet")
    return crc.value, crc_status.value


def update_crc(device: PLX_DEVICE_OBJECT, write_to_eeprom: bool = True) -> int:
    """Calculate and optionally write CRC to EEPROM.

    Returns:
        Calculated CRC value.
    """
    lib = get_library()
    crc = c_uint32()
    status = lib.PlxPci_EepromCrcUpdate(byref(device), byref(crc), c_int8(write_to_eeprom))
    check_status(status, "EepromCrcUpdate")
    return crc.value
