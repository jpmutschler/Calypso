"""Device information card component."""

from __future__ import annotations

from nicegui import ui

from calypso.models.device_info import DeviceInfo
from calypso.ui.theme import COLORS


def device_card(info: DeviceInfo) -> None:
    """Render a device information summary card."""
    with ui.card().classes("w-full p-4").style(
        f"background: {COLORS['bg_secondary']}; border: 1px solid {COLORS['border']}"
    ):
        ui.label("Device Information").classes("text-subtitle1 mb-2").style(
            f"color: {COLORS['text_primary']}"
        )

        grid_data = [
            ("Vendor:Device", f"0x{info.vendor_id:04X}:0x{info.device_id:04X}"),
            ("Location", f"{info.bus:02X}:{info.slot:02X}.{info.function}"),
            ("Chip Type", f"0x{info.chip_type:04X} rev {info.chip_revision}"),
            ("Family", info.chip_family.upper()),
            ("Port", str(info.port_number)),
        ]

        for label, value in grid_data:
            with ui.row().classes("w-full justify-between items-center py-1"):
                ui.label(label).classes("text-xs").style(f"color: {COLORS['text_secondary']}")
                ui.label(value).classes("text-xs font-mono").style(
                    f"color: {COLORS['text_primary']}"
                )
