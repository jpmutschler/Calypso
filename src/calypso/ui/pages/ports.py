"""Port status page."""

from __future__ import annotations

from nicegui import ui

from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS


def ports_page(device_id: str) -> None:
    """Render the port status page."""

    def content():
        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
        ):
            ui.label("Port grid showing all switch ports with link status.").style(
                f"color: {COLORS.text_muted}"
            )

    page_layout("Port Status", content, device_id=device_id)
