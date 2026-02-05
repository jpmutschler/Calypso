"""Non-Transparent port operations wrapping PLX SDK NT functions."""

from __future__ import annotations

from ctypes import byref, c_int8, c_uint16, c_uint32

from calypso.bindings.library import get_library
from calypso.bindings.types import PLX_DEVICE_OBJECT
from calypso.exceptions import check_status


def probe_req_id(device: PLX_DEVICE_OBJECT, is_read: bool = True) -> int:
    """Probe the NT port requester ID.

    Args:
        device: Device handle.
        is_read: True for read probe, False for write probe.

    Returns:
        Requester ID value.
    """
    lib = get_library()
    req_id = c_uint16()
    status = lib.PlxPci_Nt_ReqIdProbe(byref(device), c_int8(is_read), byref(req_id))
    check_status(status, "Nt_ReqIdProbe")
    return req_id.value


def get_lut_properties(
    device: PLX_DEVICE_OBJECT, lut_index: int
) -> tuple[int, int, bool]:
    """Get NT LUT entry properties.

    Returns:
        Tuple of (req_id, flags, is_enabled).
    """
    lib = get_library()
    req_id = c_uint16()
    flags = c_uint32()
    enabled = c_int8()
    status = lib.PlxPci_Nt_LutProperties(
        byref(device), lut_index, byref(req_id), byref(flags), byref(enabled)
    )
    check_status(status, f"Nt_LutProperties(index={lut_index})")
    return req_id.value, flags.value, bool(enabled.value)


def add_lut_entry(device: PLX_DEVICE_OBJECT, req_id: int, flags: int) -> int:
    """Add a new NT LUT entry.

    Returns:
        Assigned LUT index.
    """
    lib = get_library()
    lut_index = c_uint16()
    status = lib.PlxPci_Nt_LutAdd(byref(device), byref(lut_index), req_id, flags)
    check_status(status, "Nt_LutAdd")
    return lut_index.value


def disable_lut_entry(device: PLX_DEVICE_OBJECT, lut_index: int) -> None:
    """Disable an NT LUT entry."""
    lib = get_library()
    status = lib.PlxPci_Nt_LutDisable(byref(device), lut_index)
    check_status(status, f"Nt_LutDisable(index={lut_index})")
