"""Status indicator components."""

from __future__ import annotations

from nicegui import ui

from calypso.ui.theme import COLORS


def link_status_badge(is_up: bool) -> ui.label:
    """Create a link up/down status badge."""
    color = COLORS["link_up"] if is_up else COLORS["link_down"]
    text = "UP" if is_up else "DOWN"
    label = ui.label(text).classes("px-2 py-1 rounded text-xs font-bold")
    label.style(f"background: {color}20; color: {color}; border: 1px solid {color}40")
    return label


def speed_badge(speed: str) -> ui.label:
    """Create a link speed badge."""
    label = ui.label(speed).classes("px-2 py-1 rounded text-xs")
    label.style(
        f"background: {COLORS['accent_blue']}20; "
        f"color: {COLORS['accent_blue']}; "
        f"border: 1px solid {COLORS['accent_blue']}40"
    )
    return label


def port_role_badge(role: str) -> ui.label:
    """Create a port role badge."""
    color_map = {
        "upstream": COLORS["accent_green"],
        "downstream": COLORS["accent_blue"],
        "nt_virtual": COLORS["accent_purple"],
        "nt_link": COLORS["accent_purple"],
        "fabric": COLORS["accent_orange"],
        "host": COLORS["accent_yellow"],
    }
    color = color_map.get(role, COLORS["text_muted"])
    label = ui.label(role.upper()).classes("px-2 py-1 rounded text-xs")
    label.style(f"background: {color}20; color: {color}; border: 1px solid {color}40")
    return label
