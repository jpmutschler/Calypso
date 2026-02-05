"""Navigation sidebar component."""

from __future__ import annotations

from nicegui import ui

from calypso.ui.theme import COLORS


def sidebar_nav(device_id: str | None = None, mcu_port: str | None = None) -> None:
    """Render the navigation sidebar content."""
    ui.label("CALYPSO").classes("text-h6 text-bold mb-1").style(
        f"color: {COLORS['accent_blue']}"
    )
    ui.label("Atlas3 Switch Manager").classes("text-caption mb-4").style(
        f"color: {COLORS['text_muted']}"
    )

    ui.separator().style(f"background: {COLORS['border']}")

    with ui.column().classes("gap-1 w-full mt-2"):
        _nav_link("Discovery", "/", "search")

        if device_id:
            ui.separator().style(f"background: {COLORS['border']}")
            ui.label("Switch (SDK)").classes("text-caption mt-1").style(
                f"color: {COLORS['text_muted']}"
            )
            base = f"/switch/{device_id}"
            _nav_link("Dashboard", base, "dashboard")
            _nav_link("Ports", f"{base}/ports", "device_hub")
            _nav_link("Performance", f"{base}/perf", "speed")
            _nav_link("Configuration", f"{base}/config", "settings")
            _nav_link("Topology", f"{base}/topology", "account_tree")
            _nav_link("Registers", f"{base}/registers", "memory")
            _nav_link("EEPROM", f"{base}/eeprom", "storage")
            _nav_link("PHY Monitor", f"{base}/phy", "cable")

            try:
                from calypso.workloads import is_any_backend_available
                if is_any_backend_available():
                    _nav_link("Workloads", f"{base}/workloads", "rocket_launch")
            except ImportError:
                pass

        if mcu_port:
            ui.separator().style(f"background: {COLORS['border']}")
            ui.label("MCU").classes("text-caption mt-1").style(
                f"color: {COLORS['text_muted']}"
            )
            _nav_link("Health", "/mcu/health", "thermostat")
            _nav_link("Port Status", "/mcu/ports", "device_hub")
            _nav_link("Error Counters", "/mcu/errors", "error_outline")
            _nav_link("Configuration", "/mcu/config", "tune")
            _nav_link("Diagnostics", "/mcu/diagnostics", "bug_report")


def _nav_link(label: str, href: str, icon: str) -> None:
    """Create a navigation link with icon."""
    with ui.link(target=href).classes("no-underline w-full"):
        with ui.row().classes("items-center gap-2 px-2 py-1 rounded hover:bg-gray-800"):
            ui.icon(icon).classes("text-sm").style(f"color: {COLORS['text_secondary']}")
            ui.label(label).classes("text-sm").style(f"color: {COLORS['text_primary']}")
