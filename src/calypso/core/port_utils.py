"""Shared port discovery utilities for per-port config access."""

from __future__ import annotations

from calypso.bindings.types import PLX_DEVICE_KEY
from calypso.sdk import device as sdk_device
from calypso.utils.logging import get_logger

logger = get_logger(__name__)


def find_port_key(
    mgmt_key: PLX_DEVICE_KEY, port_number: int
) -> PLX_DEVICE_KEY | None:
    """Find a device key whose hardware PortNumber matches.

    PlxPort (SDK index) does not always equal the hardware PortNumber,
    so we open each candidate and check get_port_properties().PortNumber.
    This mirrors the pattern used by PortManager.get_all_port_statuses().

    Candidates are filtered by domain and DeviceId to avoid matching
    ports on a different switch in multi-switch systems.
    """
    from calypso.bindings.constants import PlxApiMode

    all_keys = sdk_device.find_devices(api_mode=PlxApiMode(mgmt_key.ApiMode))
    for key in all_keys:
        if key.domain != mgmt_key.domain or key.DeviceId != mgmt_key.DeviceId:
            continue
        try:
            dev = sdk_device.open_device(key)
            try:
                props = sdk_device.get_port_properties(dev)
                found = props.PortNumber == port_number
            finally:
                sdk_device.close_device(dev)
            if found:
                return key
        except Exception:
            continue
    return None
