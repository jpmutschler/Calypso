"""
Navigation sidebar with device tree.

Matches the Serial Cables Phoenix design system with section titles,
active-state highlighting, collapsible category groups, and consistent
nav item styling.
"""

from __future__ import annotations

from typing import NamedTuple

from nicegui import ui

from calypso.ui.theme import COLORS


# ---------------------------------------------------------------------------
# Switch page categories — data-driven nav structure
# ---------------------------------------------------------------------------


class NavPage(NamedTuple):
    label: str
    icon: str
    suffix: str


class NavCategory(NamedTuple):
    label: str
    icon: str
    pages: list[NavPage]


_SWITCH_CATEGORIES: list[NavCategory] = [
    NavCategory("Overview", "dashboard", [
        NavPage("Dashboard", "dashboard", ""),
        NavPage("Ports", "device_hub", "/ports"),
        NavPage("Topology", "account_tree", "/topology"),
    ]),
    NavCategory("Configuration", "settings", [
        NavPage("Configuration", "settings", "/config"),
        NavPage("Registers", "memory", "/registers"),
        NavPage("EEPROM", "storage", "/eeprom"),
    ]),
    NavCategory("Diagnostics", "troubleshoot", [
        NavPage("PHY Monitor", "cable", "/phy"),
        NavPage("Eye Diagram", "visibility", "/eye"),
        NavPage("LTSSM Trace", "timeline", "/ltssm"),
        NavPage("Protocol Trace", "analytics", "/ptrace"),
        NavPage("Packet Exerciser", "send", "/pktexer"),
    ]),
    NavCategory("Monitoring", "monitoring", [
        NavPage("Performance", "speed", "/perf"),
        NavPage("Error Overview", "error_outline", "/errors"),
    ]),
    NavCategory("Validation", "verified", [
        NavPage("Compliance", "verified", "/compliance"),
        NavPage("Recipes", "science", "/workflows"),
        NavPage("Workflow Builder", "build", "/workflow-builder"),
    ]),
]


def _normalize_path(path: str | None) -> str:
    """Strip trailing slashes for consistent path comparison."""
    return path.rstrip("/") if path else ""


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
    norm_path = _normalize_path(current_path)

    with ui.column().classes("w-full q-pa-sm q-gutter-sm"):
        _nav_item("Device Discovery", "search", "/discovery",
                  active=(norm_path == "/discovery"))

        ui.separator().style(f"background-color: {COLORS.border};")

        if device_id:
            ui.label("SWITCH (SDK)").classes("section-title q-px-sm q-pt-sm")

            base = f"/switch/{device_id}"
            categories = _resolve_categories(base)

            for category in categories:
                _render_category(category, base, norm_path)
        else:
            ui.label("SWITCH (SDK)").classes("section-title q-px-sm q-pt-sm")
            ui.label("No switch connected").classes(
                "text-caption q-px-sm"
            ).style(f"color: {COLORS.text_muted};")

        if mcu_port:
            ui.separator().style(f"background-color: {COLORS.border};")
            ui.label("MCU").classes("section-title q-px-sm q-pt-sm")

            _nav_item("Health", "thermostat", "/mcu/health",
                       active=(norm_path == "/mcu/health"))
            _nav_item("Port Status", "device_hub", "/mcu/ports",
                       active=(norm_path == "/mcu/ports"), indent=True)
            _nav_item("Error Counters", "error_outline", "/mcu/errors",
                       active=(norm_path == "/mcu/errors"), indent=True)
            _nav_item("Configuration", "tune", "/mcu/config",
                       active=(norm_path == "/mcu/config"), indent=True)
            _nav_item("Diagnostics", "bug_report", "/mcu/diagnostics",
                       active=(norm_path == "/mcu/diagnostics"), indent=True)
            _nav_item("I2C / I3C Bus", "cable", "/mcu/bus",
                       active=(norm_path == "/mcu/bus"), indent=True)
            _nav_item("NVMe Drives", "storage", "/mcu/nvme",
                       active=(norm_path == "/mcu/nvme"), indent=True)


def _resolve_categories(base: str) -> list[NavCategory]:
    """Return categories with Workloads appended to Validation if available."""
    categories = list(_SWITCH_CATEGORIES)

    try:
        from calypso.workloads import is_any_backend_available
        if is_any_backend_available():
            # Append Workloads page to the Validation category
            validation = categories[-1]
            categories[-1] = NavCategory(
                validation.label,
                validation.icon,
                [*validation.pages, NavPage("Workloads", "rocket_launch", "/workloads")],
            )
    except ImportError:
        pass

    return categories


def _render_category(
    category: NavCategory,
    base: str,
    norm_path: str,
) -> None:
    """Render a collapsible category with its child nav items."""
    has_active = any(
        norm_path == _normalize_path(f"{base}{page.suffix}")
        for page in category.pages
    )

    with ui.expansion(
        text=category.label,
        icon=category.icon,
        value=has_active,
    ).classes("w-full sidebar-category").style(
        f"color: {COLORS.text_secondary}; font-size: 0.8rem;"
    ):
        for page in category.pages:
            href = f"{base}{page.suffix}" if page.suffix else base
            _nav_item(
                page.label, page.icon, href,
                active=(norm_path == _normalize_path(href)),
                indent=True,
            )


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
