"""Status indicator components."""

from __future__ import annotations

from nicegui import ui

from calypso.ui.theme import COLORS


def link_status_badge(is_up: bool) -> ui.label:
    """Create a link up/down status badge."""
    if is_up:
        color = COLORS.green
        bg = COLORS.green_dim
        text = "UP"
    else:
        color = COLORS.red
        bg = COLORS.red_dim
        text = "DOWN"
    label = ui.label(text).classes("px-2 py-1 rounded text-xs font-bold")
    label.style(f"background: {bg}; color: {color}; border: 1px solid {color}")
    return label


def speed_badge(speed: str) -> ui.label:
    """Create a link speed badge."""
    label = ui.label(speed).classes("px-2 py-1 rounded text-xs")
    label.style(
        f"background: {COLORS.cyan_dim}; "
        f"color: {COLORS.cyan}; "
        f"border: 1px solid {COLORS.cyan}"
    )
    return label


def port_role_badge(role: str) -> ui.label:
    """Create a port role badge."""
    color_map = {
        "upstream": COLORS.green,
        "downstream": COLORS.cyan,
        "nt_virtual": COLORS.purple,
        "nt_link": COLORS.purple,
        "fabric": COLORS.orange,
        "host": COLORS.yellow,
    }
    color = color_map.get(role, COLORS.text_muted)
    label = ui.label(role.upper()).classes("px-2 py-1 rounded text-xs font-bold")
    label.style(f"background: {color}20; color: {color}; border: 1px solid {color}")
    return label
