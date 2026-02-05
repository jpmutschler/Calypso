"""Multi-host switch operations wrapping PLX SDK MH functions."""

from __future__ import annotations

from ctypes import byref, c_int8

from calypso.bindings.library import get_library
from calypso.bindings.types import PLX_DEVICE_OBJECT, PLX_MULTI_HOST_PROP
from calypso.exceptions import check_status


def get_properties(device: PLX_DEVICE_OBJECT) -> PLX_MULTI_HOST_PROP:
    """Get multi-host switch properties.

    Returns:
        Multi-host properties including VS config, management ports.
    """
    lib = get_library()
    props = PLX_MULTI_HOST_PROP()
    status = lib.PlxPci_MH_GetProperties(byref(device), byref(props))
    check_status(status, "MH_GetProperties")
    return props


def migrate_ports(
    device: PLX_DEVICE_OBJECT,
    vs_source: int,
    vs_dest: int,
    ds_port_mask: int,
    reset_source: bool = False,
) -> None:
    """Migrate downstream ports between virtual switches.

    Args:
        device: Device handle.
        vs_source: Source virtual switch index.
        vs_dest: Destination virtual switch index.
        ds_port_mask: Bitmask of downstream ports to migrate.
        reset_source: Whether to reset the source VS after migration.
    """
    lib = get_library()
    status = lib.PlxPci_MH_MigratePorts(
        byref(device), vs_source, vs_dest, ds_port_mask, c_int8(reset_source)
    )
    check_status(status, "MH_MigratePorts")
