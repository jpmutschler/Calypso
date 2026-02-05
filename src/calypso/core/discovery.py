"""Device discovery service for Atlas3 switches."""

from __future__ import annotations

from calypso.bindings.constants import PlxApiMode, PlxChipFamily
from calypso.bindings.types import PLX_MODE_PROP
from calypso.models.device_info import DeviceInfo, TransportInfo, TransportMode
from calypso.sdk import device as sdk_device
from calypso.transport.base import Transport
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

# Broadcom vendor ID
BROADCOM_VENDOR_ID = 0x10B5


def scan_devices(transport: Transport) -> list[DeviceInfo]:
    """Scan for Atlas3 devices on the given transport.

    Args:
        transport: Transport to scan on.

    Returns:
        List of DeviceInfo for each device found.
    """
    transport.connect()

    mode_prop = transport.build_mode_prop()
    keys = sdk_device.find_devices(
        api_mode=transport.api_mode,
        mode_prop=mode_prop,
    )

    devices: list[DeviceInfo] = []
    for key in keys:
        family_name = "unknown"
        try:
            family_name = PlxChipFamily(key.PlxFamily).name.lower()
        except ValueError:
            pass

        devices.append(DeviceInfo(
            device_id=key.DeviceId,
            vendor_id=key.VendorId,
            sub_vendor_id=key.SubVendorId,
            sub_device_id=key.SubDeviceId,
            revision=key.Revision,
            domain=key.domain,
            bus=key.bus,
            slot=key.slot,
            function=key.function,
            chip_type=key.PlxChip,
            chip_id=key.ChipID,
            chip_revision=key.PlxRevision,
            chip_family=family_name,
            port_number=key.PlxPort,
        ))

    logger.info("scan_complete", transport=transport.config.mode, found=len(devices))
    return devices


def scan_all_transports(transports: list[Transport]) -> dict[TransportMode, list[DeviceInfo]]:
    """Scan all provided transports for devices.

    Returns:
        Dictionary mapping transport mode to list of devices found.
    """
    results: dict[TransportMode, list[DeviceInfo]] = {}
    for transport in transports:
        try:
            mode = TransportMode(transport.config.mode.value)
            devices = scan_devices(transport)
            results[mode] = devices
        except Exception:
            logger.warning("transport_scan_failed", transport=transport.config.mode)
            continue
    return results
