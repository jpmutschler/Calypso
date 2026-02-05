"""MCU port status page - link state for all switch ports."""

from __future__ import annotations

from nicegui import app, run, ui

from calypso.mcu import pool
from calypso.mcu.models import McuPortInfo
from calypso.ui.components.mcu_common import (
    no_mcu_message,
    page_header,
    set_status_error,
    set_status_live,
    status_indicator,
)
from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS

_PORT_COLUMNS = [
    {"name": "station", "label": "Station", "field": "station", "align": "center"},
    {"name": "connector", "label": "Connector", "field": "connector", "align": "left"},
    {"name": "port_number", "label": "Port", "field": "port_number", "align": "center"},
    {"name": "negotiated_speed", "label": "Speed", "field": "negotiated_speed", "align": "center"},
    {"name": "negotiated_width", "label": "Width", "field": "negotiated_width", "align": "center"},
    {"name": "max_speed", "label": "Max Speed", "field": "max_speed", "align": "center"},
    {"name": "max_width", "label": "Max Width", "field": "max_width", "align": "center"},
    {"name": "status", "label": "Status", "field": "status", "align": "center"},
    {"name": "port_type", "label": "Type", "field": "port_type", "align": "left"},
]


def _port_to_row(port: McuPortInfo) -> dict:
    """Convert a port info model to a table row dict."""
    return {
        "station": port.station,
        "connector": port.connector,
        "port_number": port.port_number,
        "negotiated_speed": port.negotiated_speed or "--",
        "negotiated_width": port.negotiated_width or "--",
        "max_speed": port.max_speed or "--",
        "max_width": port.max_width or "--",
        "status": port.status or "Unknown",
        "port_type": port.port_type or "--",
    }


def _port_section(title: str) -> ui.table:
    """Create a labeled port table section. Always creates the table."""
    with ui.card().classes("w-full p-4").style(
        f"background: {COLORS['bg_secondary']}; "
        f"border: 1px solid {COLORS['border']}"
    ):
        ui.label(title).classes("text-subtitle2 mb-2").style(
            f"color: {COLORS['text_primary']}"
        )
        table = ui.table(
            columns=_PORT_COLUMNS,
            rows=[],
            row_key="port_number",
        ).classes("w-full")
    return table


def mcu_ports_page() -> None:
    """Render the MCU port status page."""

    def content():
        mcu_port = app.storage.user.get("mcu_port")
        if not mcu_port:
            no_mcu_message()
            return

        page_header("Port Status", f"MCU: {mcu_port}")

        chip_label = ui.label("Chip: --").classes("text-caption mb-4").style(
            f"color: {COLORS['text_secondary']}"
        )

        tables: dict[str, ui.table] = {}
        sections = [
            ("Upstream Ports", "upstream"),
            ("External MCIO Ports", "ext_mcio"),
            ("Internal MCIO Ports", "int_mcio"),
            ("Straddle Ports", "straddle"),
        ]

        for title, key in sections:
            tables[key] = _port_section(title)

        status = status_indicator()

        async def refresh():
            current_port = app.storage.user.get("mcu_port")
            if not current_port:
                set_status_error(status, Exception("MCU disconnected"))
                return
            try:
                ps = await run.io_bound(
                    lambda: pool.get_client(current_port).get_port_status()
                )

                chip_label.text = f"Chip: {ps.chip_version}" if ps.chip_version else "Chip: --"

                port_groups = {
                    "upstream": ps.upstream_ports,
                    "ext_mcio": ps.ext_mcio_ports,
                    "int_mcio": ps.int_mcio_ports,
                    "straddle": ps.straddle_ports,
                }

                for key, ports in port_groups.items():
                    tables[key].rows = [_port_to_row(p) for p in ports]
                    tables[key].update()

                set_status_live(status)
            except Exception as exc:
                set_status_error(status, exc)

        ui.timer(5.0, refresh)

    page_layout("MCU Port Status", content)
