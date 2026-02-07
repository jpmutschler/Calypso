"""Switch dashboard page - overview of device status."""

from __future__ import annotations

from nicegui import ui

from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS


def dashboard_page(device_id: str) -> None:
    """Render the switch dashboard page."""

    def content():
        with ui.row().classes("w-full gap-4"):
            # Device info card
            with ui.card().classes("flex-1 p-4").style(
                f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
            ):
                ui.label("Device Info").classes("text-subtitle2 mb-2").style(
                    f"color: {COLORS.text_primary}"
                )
                ui.label("Connect to a device to view details.").style(
                    f"color: {COLORS.text_muted}"
                )

            # Quick status
            with ui.card().classes("flex-1 p-4").style(
                f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
            ):
                ui.label("Port Summary").classes("text-subtitle2 mb-2").style(
                    f"color: {COLORS.text_primary}"
                )
                ui.label("Port status will appear here.").style(
                    f"color: {COLORS.text_muted}"
                )

        # Performance overview
        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
        ):
            ui.label("Performance Overview").classes("text-subtitle2 mb-2").style(
                f"color: {COLORS.text_primary}"
            )
            ui.label("Start performance monitoring to see bandwidth data.").style(
                f"color: {COLORS.text_muted}"
            )

    page_layout("Switch Dashboard", content, device_id=device_id)
