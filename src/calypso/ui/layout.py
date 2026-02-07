"""
Shared page layout with header, sidebar, and content area.

Every page uses page_layout() to get consistent nav and structure,
matching the Serial Cables Phoenix design system.
"""

from __future__ import annotations

from typing import Callable

from nicegui import app, ui

from calypso.ui.components.sidebar import sidebar_nav
from calypso.ui.theme import COLORS, GLOBAL_CSS


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
    ui.add_css(GLOBAL_CSS)
    ui.add_head_html(
        '<link href="https://fonts.googleapis.com/css2?'
        'family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">'
    )

    ui.dark_mode(True)
    ui.colors(primary=COLORS.cyan, secondary=COLORS.blue, accent=COLORS.purple)

    mcu_port = app.storage.user.get("mcu_port")

    with ui.header(elevated=True).classes("q-pa-sm"):
        with ui.row().classes("w-full items-center no-wrap q-gutter-md"):
            ui.image("/static/logo.png").style(
                "width: 32px; height: 32px;"
            )
            ui.label("CALYPSO").classes("text-h6 text-bold").style(
                f"color: {COLORS.cyan}; letter-spacing: 0.15em;"
            )
            ui.label("|").style(f"color: {COLORS.text_muted};")
            ui.label("Serial Cables Atlas3 PCIe Switch Manager").classes(
                "text-subtitle2"
            ).style(f"color: {COLORS.text_secondary};")

            ui.space()

            ui.label(title).classes("text-subtitle1").style(
                f"color: {COLORS.text_primary};"
            )

            ui.space()

            # Connection badge
            if device_id:
                with ui.row().classes("items-center q-gutter-xs"):
                    ui.icon("link").style(
                        f"color: {COLORS.green}; font-size: 1rem;"
                    )
                    ui.label("connected").classes("text-caption").style(
                        f"color: {COLORS.green};"
                    )
            else:
                with ui.row().classes("items-center q-gutter-xs"):
                    ui.icon("link_off").style(
                        f"color: {COLORS.text_muted}; font-size: 1rem;"
                    )
                    ui.label("No devices").classes("text-caption").style(
                        f"color: {COLORS.text_muted};"
                    )

    with ui.left_drawer(value=True, bordered=True).classes("q-pa-none").style(
        f"width: 240px; background-color: {COLORS.bg_secondary};"
    ):
        sidebar_nav(device_id=device_id, mcu_port=mcu_port)

    with ui.column().classes("q-pa-md w-full").style(
        f"background-color: {COLORS.bg_primary};"
    ):
        content_fn()
