"""Shared UI helpers for switch pages."""

from __future__ import annotations

from nicegui import ui

from calypso.ui.theme import COLORS

# Switch mode decode per PLX SDK
SWITCH_MODE_NAMES: dict[int, str] = {
    0: "Standard (Single Host)",
    1: "vSwitch Basic",
    2: "vSwitch with NT",
    3: "Shared-I/O",
    4: "MR-IOV",
}


def kv_pair(label: str, value: str, value_color: str | None = None) -> None:
    """Render a compact key-value pair."""
    with ui.row().classes("items-center gap-2"):
        ui.label(f"{label}:").style(
            f"color: {COLORS.text_secondary}; font-size: 0.85rem;"
        )
        ui.label(value).style(
            f"color: {value_color or COLORS.text_primary}; font-weight: 600;"
            f" font-size: 0.85rem;"
        )


def bitmask_to_ports(mask: int) -> list[int]:
    """Convert a 32-bit port bitmask to a sorted list of port numbers."""
    return [bit for bit in range(32) if mask & (1 << bit)]
