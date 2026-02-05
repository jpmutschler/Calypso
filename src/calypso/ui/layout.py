"""Shared page layout with header and sidebar."""

from __future__ import annotations

from typing import Callable

from nicegui import app, ui

from calypso.ui.components.sidebar import sidebar_nav
from calypso.ui.theme import COLORS, CSS


def page_layout(
    title: str,
    content_fn: Callable,
    device_id: str | None = None,
) -> None:
    """Create the standard page layout with header and sidebar.

    Args:
        title: Page title displayed in the header.
        content_fn: Callable that builds the page content.
        device_id: Connected switch device ID for sidebar navigation.
    """
    ui.add_head_html(f"<style>{CSS}</style>")
    ui.add_head_html(
        '<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">'
    )

    mcu_port = app.storage.user.get("mcu_port")

    with ui.header().classes("items-center justify-between px-4"):
        with ui.row().classes("items-center gap-2"):
            ui.label("CALYPSO").classes("text-h6 text-bold").style(
                f"color: {COLORS['accent_blue']}"
            )
            ui.label("|").classes("text-h6").style(f"color: {COLORS['text_muted']}")
            ui.label("Atlas3 Switch Manager").classes("text-subtitle1").style(
                f"color: {COLORS['text_secondary']}"
            )
        ui.label(title).classes("text-subtitle1").style(
            f"color: {COLORS['text_primary']}"
        )

    with ui.left_drawer(value=True).classes("p-4"):
        sidebar_nav(device_id=device_id, mcu_port=mcu_port)

    with ui.column().classes("w-full p-4"):
        content_fn()
