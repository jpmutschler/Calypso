"""Register decode tables for annotated config space display.

Maps config space offsets to human-readable register names and field descriptions.
Covers the standard PCI header (0x00-0x3C) and PCI Express capability registers.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RegisterField:
    """A named bitfield within a register."""

    name: str
    bit_hi: int
    bit_lo: int


@dataclass(frozen=True)
class RegisterDecode:
    """Decode info for a register at a given offset."""

    offset: int
    name: str
    fields: tuple[RegisterField, ...] = ()


# Standard PCI config space header (Type 0/1 common) — DWORD-aligned offsets.
_HEADER_DECODE: dict[int, RegisterDecode] = {
    0x00: RegisterDecode(0x00, "Vendor/Device ID", (
        RegisterField("Vendor ID", 15, 0),
        RegisterField("Device ID", 31, 16),
    )),
    0x04: RegisterDecode(0x04, "Command/Status", (
        RegisterField("Command", 15, 0),
        RegisterField("Status", 31, 16),
    )),
    0x08: RegisterDecode(0x08, "Rev/Class", (
        RegisterField("Revision ID", 7, 0),
        RegisterField("Prog IF", 15, 8),
        RegisterField("Subclass", 23, 16),
        RegisterField("Class Code", 31, 24),
    )),
    0x0C: RegisterDecode(0x0C, "Cache/Latency/Header/BIST", (
        RegisterField("Cache Line Size", 7, 0),
        RegisterField("Latency Timer", 15, 8),
        RegisterField("Header Type", 23, 16),
        RegisterField("BIST", 31, 24),
    )),
    0x10: RegisterDecode(0x10, "BAR0"),
    0x14: RegisterDecode(0x14, "BAR1"),
    0x18: RegisterDecode(0x18, "Bus Numbers", (
        RegisterField("Primary Bus", 7, 0),
        RegisterField("Secondary Bus", 15, 8),
        RegisterField("Subordinate Bus", 23, 16),
        RegisterField("Sec Latency", 31, 24),
    )),
    0x1C: RegisterDecode(0x1C, "IO Base/Limit"),
    0x20: RegisterDecode(0x20, "Memory Base/Limit"),
    0x24: RegisterDecode(0x24, "Prefetchable Base/Limit"),
    0x28: RegisterDecode(0x28, "Prefetchable Base Upper"),
    0x2C: RegisterDecode(0x2C, "Prefetchable Limit Upper"),
    0x30: RegisterDecode(0x30, "IO Base/Limit Upper"),
    0x34: RegisterDecode(0x34, "Capabilities Ptr", (
        RegisterField("Cap Pointer", 7, 0),
    )),
    0x38: RegisterDecode(0x38, "Expansion ROM Base"),
    0x3C: RegisterDecode(0x3C, "Interrupt Line/Pin", (
        RegisterField("INT Line", 7, 0),
        RegisterField("INT Pin", 15, 8),
        RegisterField("Bridge Ctl", 31, 16),
    )),
}

# PCI Express capability structure — offsets relative to cap base.
_PCIE_CAP_DECODE: dict[int, RegisterDecode] = {
    0x00: RegisterDecode(0x00, "PCIe Cap Header", (
        RegisterField("Cap ID", 7, 0),
        RegisterField("Next Ptr", 15, 8),
        RegisterField("PCIe Caps", 31, 16),
    )),
    0x04: RegisterDecode(0x04, "Device Capabilities", (
        RegisterField("Max Payload", 2, 0),
        RegisterField("Ext Tag", 5, 5),
        RegisterField("FLR", 28, 28),
    )),
    0x08: RegisterDecode(0x08, "Device Ctrl/Status", (
        RegisterField("Device Control", 15, 0),
        RegisterField("Device Status", 31, 16),
    )),
    0x0C: RegisterDecode(0x0C, "Link Capabilities", (
        RegisterField("Max Speed", 3, 0),
        RegisterField("Max Width", 9, 4),
        RegisterField("ASPM", 11, 10),
        RegisterField("Port Number", 31, 24),
    )),
    0x10: RegisterDecode(0x10, "Link Ctrl/Status", (
        RegisterField("Link Control", 15, 0),
        RegisterField("Link Status", 31, 16),
    )),
    0x14: RegisterDecode(0x14, "Slot Capabilities"),
    0x18: RegisterDecode(0x18, "Slot Ctrl/Status"),
    0x1C: RegisterDecode(0x1C, "Root Ctrl/Cap"),
    0x20: RegisterDecode(0x20, "Root Status"),
    0x24: RegisterDecode(0x24, "Device Capabilities 2"),
    0x28: RegisterDecode(0x28, "Device Ctrl 2/Status 2"),
    0x2C: RegisterDecode(0x2C, "Link Capabilities 2", (
        RegisterField("Speeds Vector", 7, 1),
    )),
    0x30: RegisterDecode(0x30, "Link Ctrl 2/Status 2", (
        RegisterField("Target Speed", 3, 0),
        RegisterField("Link Ctrl 2", 15, 4),
        RegisterField("Link Status 2", 31, 16),
    )),
    0x34: RegisterDecode(0x34, "Slot Capabilities 2"),
    0x38: RegisterDecode(0x38, "Slot Ctrl 2/Status 2"),
}


def get_decode_for_offset(
    offset: int, pcie_cap_base: int | None = None
) -> RegisterDecode | None:
    """Look up a register decode for a given config space offset.

    Checks the standard header first (0x00-0x3C), then PCIe capability
    structure if pcie_cap_base is known.

    Args:
        offset: Absolute config space offset (DWORD-aligned).
        pcie_cap_base: Absolute offset of the PCI Express capability, if known.

    Returns:
        RegisterDecode or None if the offset has no decode entry.
    """
    if offset in _HEADER_DECODE:
        return _HEADER_DECODE[offset]

    if pcie_cap_base is not None and offset >= pcie_cap_base:
        relative = offset - pcie_cap_base
        if relative in _PCIE_CAP_DECODE:
            return _PCIE_CAP_DECODE[relative]

    return None
