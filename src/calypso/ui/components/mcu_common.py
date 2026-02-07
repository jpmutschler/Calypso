"""Common MCU UI components shared across MCU pages."""

from __future__ import annotations

from nicegui import ui

from calypso.ui.theme import COLORS


def no_mcu_message() -> None:
    """Display a message when no MCU is connected."""
    with ui.column().classes("items-center justify-center gap-4 mt-8"):
        ui.icon("usb_off").classes("text-6xl").style(
            f"color: {COLORS.text_muted}"
        )
        ui.label("No MCU Connected").classes("text-h6").style(
            f"color: {COLORS.text_secondary}"
        )
        ui.label(
            "Go to Discovery to scan and connect to an Atlas3 MCU."
        ).style(f"color: {COLORS.text_muted}")
        ui.link("Go to Discovery", "/").classes("text-white")


def stat_card(title: str, icon: str) -> ui.label:
    """Create a stat card with title and icon, return the value label.

    The returned label can be updated in timer callbacks to show live data.
    """
    with ui.card().classes("flex-1 p-4 min-w-[200px]"):
        with ui.row().classes("items-center gap-2 mb-2"):
            ui.icon(icon).classes("text-lg").style(
                f"color: {COLORS.cyan}"
            )
            ui.label(title).classes("text-subtitle2").style(
                f"color: {COLORS.text_primary}"
            )
        value_label = ui.label("--").classes("text-h4").style(
            f"color: {COLORS.text_primary}"
        )
    return value_label


def page_header(title: str, subtitle: str) -> None:
    """Render a standard MCU page header."""
    ui.label(title).classes("text-h5 mb-1").style(
        f"color: {COLORS.text_primary}"
    )
    ui.label(subtitle).classes("text-caption mb-4").style(
        f"color: {COLORS.text_secondary}"
    )


def card_style() -> str:
    """Return the standard card style string."""
    return (
        f"background: {COLORS.bg_card}; "
        f"border: 1px solid {COLORS.border}"
    )


def card_header(title: str, icon: str) -> None:
    """Render a card section header with icon."""
    with ui.row().classes("items-center gap-2 mb-3"):
        ui.icon(icon).classes("text-lg").style(
            f"color: {COLORS.cyan}"
        )
        ui.label(title).classes("text-subtitle2").style(
            f"color: {COLORS.text_primary}"
        )


def update_badge(badge: ui.element, enabled: bool) -> None:
    """Update a badge element to reflect enabled/disabled state."""
    badge.text = "Enabled" if enabled else "Disabled"
    badge.props(f'color={"green" if enabled else "grey"}')
    badge.update()


def status_indicator() -> ui.label:
    """Create a status indicator label for live/error state."""
    return ui.label("Fetching...").classes("text-caption mt-2").style(
        f"color: {COLORS.text_muted}"
    )


def set_status_live(label: ui.label) -> None:
    """Set status indicator to live state."""
    label.text = "Live"
    label.style(f"color: {COLORS.green}")


def set_status_error(label: ui.label, error: Exception) -> None:
    """Set status indicator to error state."""
    label.text = f"Error: {str(error)[:200]}"
    label.style(f"color: {COLORS.red}")
