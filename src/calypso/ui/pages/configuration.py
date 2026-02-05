"""Switch configuration page."""

from __future__ import annotations

from nicegui import ui

from calypso.ui.theme import COLORS, CSS


def configuration_page(device_id: str) -> None:
    """Render the switch configuration page."""
    ui.add_head_html(f"<style>{CSS}</style>")

    with ui.column().classes("w-full p-4 gap-4"):
        ui.label("Switch Configuration").classes("text-h5").style(
            f"color: {COLORS['text_primary']}"
        )
        ui.label(f"Device: {device_id}").style(f"color: {COLORS['text_secondary']}")

        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS['bg_secondary']}; border: 1px solid {COLORS['border']}"
        ):
            ui.label("Multi-host, virtual switch, and NT settings.").style(
                f"color: {COLORS['text_muted']}"
            )
