"""Port status grid component for displaying all switch ports."""

from __future__ import annotations

from nicegui import ui

from calypso.models.port import PortStatus
from calypso.ui.theme import COLORS


def port_grid(statuses: list[PortStatus]) -> None:
    """Render a grid of port status tiles."""
    if not statuses:
        ui.label("No ports found").style(f"color: {COLORS.text_muted}")
        return

    with ui.row().classes("flex-wrap gap-2"):
        for status in statuses:
            color = COLORS.green if status.is_link_up else COLORS.text_muted
            border_color = color if status.is_link_up else COLORS.border

            with ui.card().classes("p-2").style(
                f"min-width: 100px; border: 1px solid {border_color}; "
                f"background: {COLORS.bg_card}"
            ):
                with ui.row().classes("items-center gap-1"):
                    ui.label(f"P{status.port_number}").classes(
                        "text-xs font-bold"
                    ).style(f"color: {color}")
                    dot_color = COLORS.green if status.is_link_up else COLORS.red
                    ui.html(
                        f'<span style="color:{dot_color}; font-size:8px">\u25cf</span>'
                    )

                if status.is_link_up:
                    ui.label(f"x{status.link_width} {status.link_speed}").classes(
                        "text-xs hex-value"
                    )
                else:
                    ui.label("No Link").classes("text-xs").style(
                        f"color: {COLORS.text_muted}"
                    )
