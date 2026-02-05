"""Safe register access operations wrapping PLX SDK register functions."""

from __future__ import annotations

from ctypes import byref, c_int, c_uint32

from calypso.bindings.library import get_library
from calypso.bindings.types import PLX_DEVICE_OBJECT
from calypso.exceptions import check_status


def read_pci_register(bus: int, slot: int, function: int, offset: int) -> int:
    """Read a PCI configuration register by BDF address.

    Args:
        bus: PCI bus number.
        slot: PCI slot/device number.
        function: PCI function number.
        offset: Register offset (must be DWORD aligned).

    Returns:
        32-bit register value.
    """
    lib = get_library()
    status = c_int()
    value = lib.PlxPci_PciRegisterRead(bus, slot, function, offset, byref(status))
    check_status(status.value, f"PciRegisterRead(offset=0x{offset:X})")
    return value


def write_pci_register(bus: int, slot: int, function: int, offset: int, value: int) -> None:
    """Write a PCI configuration register by BDF address."""
    lib = get_library()
    status = lib.PlxPci_PciRegisterWrite(bus, slot, function, offset, value)
    check_status(status, f"PciRegisterWrite(offset=0x{offset:X})")


def read_pci_register_fast(device: PLX_DEVICE_OBJECT, offset: int) -> int:
    """Read a PCI register using an open device handle (faster)."""
    lib = get_library()
    status = c_int()
    value = lib.PlxPci_PciRegisterReadFast(byref(device), offset, byref(status))
    check_status(status.value, f"PciRegisterReadFast(offset=0x{offset:X})")
    return value


def write_pci_register_fast(device: PLX_DEVICE_OBJECT, offset: int, value: int) -> None:
    """Write a PCI register using an open device handle (faster)."""
    lib = get_library()
    status = lib.PlxPci_PciRegisterWriteFast(byref(device), offset, value)
    check_status(status, f"PciRegisterWriteFast(offset=0x{offset:X})")


def read_plx_register(device: PLX_DEVICE_OBJECT, offset: int) -> int:
    """Read a device-specific PLX register."""
    lib = get_library()
    status = c_int()
    value = lib.PlxPci_PlxRegisterRead(byref(device), offset, byref(status))
    check_status(status.value, f"PlxRegisterRead(offset=0x{offset:X})")
    return value


def write_plx_register(device: PLX_DEVICE_OBJECT, offset: int, value: int) -> None:
    """Write a device-specific PLX register."""
    lib = get_library()
    status = lib.PlxPci_PlxRegisterWrite(byref(device), offset, value)
    check_status(status, f"PlxRegisterWrite(offset=0x{offset:X})")


def read_mapped_register(device: PLX_DEVICE_OBJECT, offset: int) -> int:
    """Read a mapped PLX register."""
    lib = get_library()
    status = c_int()
    value = lib.PlxPci_PlxMappedRegisterRead(byref(device), offset, byref(status))
    check_status(status.value, f"PlxMappedRegisterRead(offset=0x{offset:X})")
    return value


def write_mapped_register(device: PLX_DEVICE_OBJECT, offset: int, value: int) -> None:
    """Write a mapped PLX register."""
    lib = get_library()
    status = lib.PlxPci_PlxMappedRegisterWrite(byref(device), offset, value)
    check_status(status, f"PlxMappedRegisterWrite(offset=0x{offset:X})")


def read_mailbox(device: PLX_DEVICE_OBJECT, mailbox: int) -> int:
    """Read a PLX mailbox register."""
    lib = get_library()
    status = c_int()
    value = lib.PlxPci_PlxMailboxRead(byref(device), mailbox, byref(status))
    check_status(status.value, f"PlxMailboxRead(mailbox={mailbox})")
    return value


def write_mailbox(device: PLX_DEVICE_OBJECT, mailbox: int, value: int) -> None:
    """Write a PLX mailbox register."""
    lib = get_library()
    status = lib.PlxPci_PlxMailboxWrite(byref(device), mailbox, value)
    check_status(status, f"PlxMailboxWrite(mailbox={mailbox})")
