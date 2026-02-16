"""Device discovery service for Atlas3 switches."""

from __future__ import annotations

from calypso.bindings.constants import PlxChipFamily
from calypso.models.device_info import DeviceInfo, TransportMode
from calypso.sdk import device as sdk_device
from calypso.transport.base import Transport
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

# Broadcom vendor ID
BROADCOM_VENDOR_ID = 0x10B5

# Atlas3 chip families (covers both A0 and B0 silicon, all lane variants)
ATLAS3_FAMILIES = {PlxChipFamily.ATLAS_3, PlxChipFamily.ATLAS3_LLC}


def _is_atlas3(key: object) -> bool:
    """Check if a device key belongs to an Atlas3 family."""
    try:
        return PlxChipFamily(key.PlxFamily) in ATLAS3_FAMILIES
    except ValueError:
        return False


def scan_devices(transport: Transport, include_downstream: bool = False) -> list[DeviceInfo]:
    """Scan for Atlas3 devices on the given transport.

    Args:
        transport: Transport to scan on.
        include_downstream: If False (default), only return upstream ports.
                          If True, return all ports including downstream.

    Returns:
        List of DeviceInfo for each device found. Filters to Atlas3 chips only
        and excludes downstream virtual ports by default.
    """
    transport.connect()

    mode_prop = transport.build_mode_prop()
    keys = sdk_device.find_devices(
        api_mode=transport.api_mode,
        mode_prop=mode_prop,
    )

    # Group devices by bus to identify upstream vs downstream ports
    # Upstream ports are on a lower bus number than their downstream ports
    bus_groups: dict[int, list] = {}
    for key in keys:
        if _is_atlas3(key):
            if key.bus not in bus_groups:
                bus_groups[key.bus] = []
            bus_groups[key.bus].append(key)

    devices: list[DeviceInfo] = []
    for key in keys:
        # Filter: Only include Atlas3 switches (A0 and B0/LLC families)
        if not _is_atlas3(key):
            continue

        family_name = "unknown"
        try:
            family_name = PlxChipFamily(key.PlxFamily).name.lower()
        except ValueError:
            pass

        # Filter: Exclude downstream ports unless requested
        # Downstream ports are identified by having the same chip on a higher bus
        if not include_downstream:
            is_downstream = any(
                other_bus < key.bus and len(bus_groups[other_bus]) > 0
                for other_bus in bus_groups.keys()
                if other_bus != key.bus
            )
            if is_downstream:
                continue

        device_info = DeviceInfo(
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
        )

        devices.append(device_info)

    logger.info("scan_complete", transport=transport.config.mode, found=len(devices), total_atlas3=len(bus_groups.get(min(bus_groups.keys()), [])) if bus_groups else 0)
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
