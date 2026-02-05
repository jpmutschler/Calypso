"""Device lifecycle management wrapping PLX SDK device functions."""

from __future__ import annotations

import ctypes
from ctypes import POINTER, byref, c_uint8, c_uint16

from calypso.bindings.constants import PlxApiMode, PlxChipFamily
from calypso.bindings.library import get_library
from calypso.bindings.types import (
    PEX_CHIP_FEAT,
    PLX_DEVICE_KEY,
    PLX_DEVICE_OBJECT,
    PLX_DRIVER_PROP,
    PLX_MODE_PROP,
    PLX_PORT_PROP,
)
from calypso.exceptions import DeviceNotFoundError, check_status
from calypso.utils.logging import get_logger

logger = get_logger(__name__)


def find_devices(
    api_mode: PlxApiMode = PlxApiMode.PCI,
    mode_prop: PLX_MODE_PROP | None = None,
    vendor_id: int = 0xFFFF,
    device_id: int = 0xFFFF,
) -> list[PLX_DEVICE_KEY]:
    """Find all PLX devices accessible via the given API mode.

    Args:
        api_mode: Transport mode to use for device discovery.
        mode_prop: Mode-specific properties (SDB port/baud, I2C address, etc).
        vendor_id: Filter by vendor ID. 0xFFFF = any.
        device_id: Filter by device ID. 0xFFFF = any.

    Returns:
        List of device keys for all matching devices found.
    """
    lib = get_library()
    devices: list[PLX_DEVICE_KEY] = []
    device_num = 0

    while True:
        key = PLX_DEVICE_KEY()
        if vendor_id != 0xFFFF:
            key.VendorId = vendor_id
        if device_id != 0xFFFF:
            key.DeviceId = device_id

        if api_mode == PlxApiMode.PCI:
            status = lib.PlxPci_DeviceFind(byref(key), device_num)
        else:
            prop = mode_prop if mode_prop is not None else PLX_MODE_PROP()
            status = lib.PlxPci_DeviceFindEx(byref(key), device_num, api_mode.value, byref(prop))

        if status != 0x200:  # PLX_STATUS_OK
            break

        devices.append(key)
        device_num += 1

    logger.info("devices_found", count=len(devices), api_mode=api_mode.name)
    return devices


def open_device(key: PLX_DEVICE_KEY) -> PLX_DEVICE_OBJECT:
    """Open a device for access.

    Args:
        key: Device key from find_devices().

    Returns:
        Device object handle for subsequent API calls.

    Raises:
        CalypsoError: If the device cannot be opened.
    """
    lib = get_library()
    device = PLX_DEVICE_OBJECT()
    status = lib.PlxPci_DeviceOpen(byref(key), byref(device))
    check_status(status, "DeviceOpen")
    logger.info("device_opened", bus=key.bus, slot=key.slot, function=key.function)
    return device


def close_device(device: PLX_DEVICE_OBJECT) -> None:
    """Close a previously opened device.

    Args:
        device: Device object to close.
    """
    lib = get_library()
    status = lib.PlxPci_DeviceClose(byref(device))
    check_status(status, "DeviceClose")
    logger.info("device_closed")


def reset_device(device: PLX_DEVICE_OBJECT) -> None:
    """Reset the device.

    Args:
        device: Device object handle.
    """
    lib = get_library()
    status = lib.PlxPci_DeviceReset(byref(device))
    check_status(status, "DeviceReset")
    logger.info("device_reset")


def get_chip_type(device: PLX_DEVICE_OBJECT) -> tuple[int, int]:
    """Get chip type and revision.

    Returns:
        Tuple of (chip_type, revision).
    """
    lib = get_library()
    chip_type = c_uint16()
    revision = c_uint8()
    status = lib.PlxPci_ChipTypeGet(byref(device), byref(chip_type), byref(revision))
    check_status(status, "ChipTypeGet")
    return chip_type.value, revision.value


def get_port_properties(device: PLX_DEVICE_OBJECT) -> PLX_PORT_PROP:
    """Get port properties for the current device port.

    Returns:
        Port properties structure with link info.
    """
    lib = get_library()
    props = PLX_PORT_PROP()
    status = lib.PlxPci_GetPortProperties(byref(device), byref(props))
    check_status(status, "GetPortProperties")
    return props


def get_chip_port_mask(chip_id: int, revision: int) -> PEX_CHIP_FEAT:
    """Get chip feature information including port mask.

    Returns:
        Chip features structure with station/port info.
    """
    lib = get_library()
    feat = PEX_CHIP_FEAT()
    status = lib.PlxPci_ChipGetPortMask(chip_id, revision, byref(feat))
    check_status(status, "ChipGetPortMask")
    return feat


def get_driver_properties(device: PLX_DEVICE_OBJECT) -> PLX_DRIVER_PROP:
    """Get driver properties.

    Returns:
        Driver properties structure.
    """
    lib = get_library()
    props = PLX_DRIVER_PROP()
    status = lib.PlxPci_DriverProperties(byref(device), byref(props))
    check_status(status, "DriverProperties")
    return props


def get_driver_version(device: PLX_DEVICE_OBJECT) -> tuple[int, int, int]:
    """Get driver version.

    Returns:
        Tuple of (major, minor, revision).
    """
    lib = get_library()
    major = c_uint8()
    minor = c_uint8()
    revision = c_uint8()
    status = lib.PlxPci_DriverVersion(byref(device), byref(major), byref(minor), byref(revision))
    check_status(status, "DriverVersion")
    return major.value, minor.value, revision.value


def get_api_version() -> tuple[int, int, int]:
    """Get PLX API library version.

    Returns:
        Tuple of (major, minor, revision).
    """
    lib = get_library()
    major = c_uint8()
    minor = c_uint8()
    revision = c_uint8()
    status = lib.PlxPci_ApiVersion(byref(major), byref(minor), byref(revision))
    check_status(status, "ApiVersion")
    return major.value, minor.value, revision.value
