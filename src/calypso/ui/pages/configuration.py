"""Switch configuration page."""

from __future__ import annotations

from nicegui import ui

from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS


def configuration_page(device_id: str) -> None:
    """Render the switch configuration page."""

    def content():
        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
        ):
            ui.label("Multi-host, virtual switch, and NT settings.").style(
                f"color: {COLORS.text_muted}"
            )

    page_layout("Switch Configuration", content, device_id=device_id)
