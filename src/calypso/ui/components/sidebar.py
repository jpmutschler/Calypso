"""
Navigation sidebar with device tree.

Matches the Serial Cables Phoenix design system with section titles,
active-state highlighting, and consistent nav item styling.
"""

from __future__ import annotations

from nicegui import ui

from calypso.ui.theme import COLORS


def sidebar_nav(
    device_id: str | None = None,
    mcu_port: str | None = None,
    current_path: str | None = None,
) -> None:
    """Render the navigation sidebar content.

    Args:
        device_id: Connected switch device ID for switch nav links.
        mcu_port: Connected MCU serial port for MCU nav links.
        current_path: Current page path for active link highlighting.
    """
    with ui.column().classes("w-full q-pa-sm q-gutter-sm"):
        _nav_item("Device Discovery", "search", "/discovery",
                  active=(current_path == "/discovery"))

        ui.separator().style(f"background-color: {COLORS.border};")

        if device_id:
            ui.label("SWITCH (SDK)").classes("section-title q-px-sm q-pt-sm")

            base = f"/switch/{device_id}"
            _nav_item("Dashboard", "dashboard", base,
                       active=(current_path == base))
            _nav_item("Ports", "device_hub", f"{base}/ports",
                       active=(current_path == f"{base}/ports"), indent=True)
            _nav_item("Performance", "speed", f"{base}/perf",
                       active=(current_path == f"{base}/perf"), indent=True)
            _nav_item("Configuration", "settings", f"{base}/config",
                       active=(current_path == f"{base}/config"), indent=True)
            _nav_item("Topology", "account_tree", f"{base}/topology",
                       active=(current_path == f"{base}/topology"), indent=True)
            _nav_item("Registers", "memory", f"{base}/registers",
                       active=(current_path == f"{base}/registers"), indent=True)
            _nav_item("EEPROM", "storage", f"{base}/eeprom",
                       active=(current_path == f"{base}/eeprom"), indent=True)
            _nav_item("PHY Monitor", "cable", f"{base}/phy",
                       active=(current_path == f"{base}/phy"), indent=True)
            _nav_item("Eye Diagram", "visibility", f"{base}/eye",
                       active=(current_path == f"{base}/eye"), indent=True)
            _nav_item("LTSSM Trace", "timeline", f"{base}/ltssm",
                       active=(current_path == f"{base}/ltssm"), indent=True)
            _nav_item("Error Overview", "error_outline", f"{base}/errors",
                       active=(current_path == f"{base}/errors"), indent=True)
            _nav_item("Compliance", "verified", f"{base}/compliance",
                       active=(current_path == f"{base}/compliance"), indent=True)

            try:
                from calypso.workloads import is_any_backend_available
                if is_any_backend_available():
                    _nav_item("Workloads", "rocket_launch", f"{base}/workloads",
                               active=(current_path == f"{base}/workloads"),
                               indent=True)
            except ImportError:
                pass
        else:
            ui.label("SWITCH (SDK)").classes("section-title q-px-sm q-pt-sm")
            ui.label("No switch connected").classes(
                "text-caption q-px-sm"
            ).style(f"color: {COLORS.text_muted};")

        if mcu_port:
            ui.separator().style(f"background-color: {COLORS.border};")
            ui.label("MCU").classes("section-title q-px-sm q-pt-sm")

            _nav_item("Health", "thermostat", "/mcu/health",
                       active=(current_path == "/mcu/health"))
            _nav_item("Port Status", "device_hub", "/mcu/ports",
                       active=(current_path == "/mcu/ports"), indent=True)
            _nav_item("Error Counters", "error_outline", "/mcu/errors",
                       active=(current_path == "/mcu/errors"), indent=True)
            _nav_item("Configuration", "tune", "/mcu/config",
                       active=(current_path == "/mcu/config"), indent=True)
            _nav_item("Diagnostics", "bug_report", "/mcu/diagnostics",
                       active=(current_path == "/mcu/diagnostics"), indent=True)
            _nav_item("I2C / I3C Bus", "cable", "/mcu/bus",
                       active=(current_path == "/mcu/bus"), indent=True)
            _nav_item("NVMe Drives", "storage", "/mcu/nvme",
                       active=(current_path == "/mcu/nvme"), indent=True)


def _nav_item(
    label: str,
    icon: str,
    href: str,
    active: bool = False,
    indent: bool = False,
) -> None:
    """Render a single navigation item."""
    bg = COLORS.bg_elevated if active else "transparent"
    text_color = COLORS.cyan if active else COLORS.text_primary
    pad = "q-pl-lg" if indent else ""

    with ui.link(target=href).classes(f"no-decoration w-full {pad}"):
        with ui.row().classes("items-center q-pa-sm q-gutter-sm rounded").style(
            f"background-color: {bg}; width: 100%;"
        ):
            ui.icon(icon).style(f"color: {text_color}; font-size: 1.1rem;")
            ui.label(label).style(f"color: {text_color}; font-size: 0.85rem;")
