"""MCU error counters page - per-port error tracking."""

from __future__ import annotations

from nicegui import app, run, ui

from calypso.mcu import pool
from calypso.mcu.models import McuErrorCounters
from calypso.ui.components.mcu_common import (
    no_mcu_message,
    page_header,
    set_status_error,
    set_status_live,
    status_indicator,
)
from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS

_ERROR_COLUMNS = [
    {"name": "port_number", "label": "Port", "field": "port_number", "align": "center"},
    {"name": "port_rx", "label": "Port RX", "field": "port_rx", "align": "right"},
    {"name": "bad_tlp", "label": "Bad TLP", "field": "bad_tlp", "align": "right"},
    {"name": "bad_dllp", "label": "Bad DLLP", "field": "bad_dllp", "align": "right"},
    {"name": "rec_diag", "label": "Rec Diag", "field": "rec_diag", "align": "right"},
    {"name": "link_down", "label": "Link Down", "field": "link_down", "align": "right"},
    {"name": "flit_error", "label": "FLIT Error", "field": "flit_error", "align": "right"},
    {"name": "total", "label": "Total", "field": "total", "align": "right"},
]


def _counter_to_row(c: McuErrorCounters) -> dict:
    """Convert error counters model to a table row."""
    return {
        "port_number": c.port_number,
        "port_rx": c.port_rx,
        "bad_tlp": c.bad_tlp,
        "bad_dllp": c.bad_dllp,
        "rec_diag": c.rec_diag,
        "link_down": c.link_down,
        "flit_error": c.flit_error,
        "total": c.total_errors,
    }


def mcu_errors_page() -> None:
    """Render the MCU error counters page."""

    def content():
        mcu_port = app.storage.user.get("mcu_port")
        if not mcu_port:
            no_mcu_message()
            return

        page_header("Error Counters", f"MCU: {mcu_port}")

        with ui.row().classes("gap-2 mb-4"):
            async def clear_errors():
                current_port = app.storage.user.get("mcu_port")
                if not current_port:
                    return
                try:
                    await run.io_bound(
                        lambda: pool.get_client(current_port).clear_error_counters()
                    )
                    ui.notify("Error counters cleared", type="positive")
                    await refresh()
                except Exception as exc:
                    ui.notify(f"Clear failed: {exc}", type="negative")

            ui.button("Clear Counters", icon="delete_sweep", on_click=clear_errors).style(
                f"background: {COLORS['accent_red']}"
            )

        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS['bg_secondary']}; "
            f"border: 1px solid {COLORS['border']}"
        ):
            table = ui.table(
                columns=_ERROR_COLUMNS,
                rows=[],
                row_key="port_number",
            ).classes("w-full")

        # Summary counters
        with ui.row().classes("w-full gap-4 flex-wrap mt-4"):
            total_errors_label = ui.label("Total Errors: --").classes("text-h6").style(
                f"color: {COLORS['text_primary']}"
            )
            ports_with_errors_label = ui.label("Ports with Errors: --").classes(
                "text-h6"
            ).style(f"color: {COLORS['text_primary']}")

        status = status_indicator()

        async def refresh():
            current_port = app.storage.user.get("mcu_port")
            if not current_port:
                set_status_error(status, Exception("MCU disconnected"))
                return
            try:
                snapshot = await run.io_bound(
                    lambda: pool.get_client(current_port).get_error_counters()
                )

                rows = [_counter_to_row(c) for c in snapshot.counters]
                table.rows = rows
                table.update()

                total = sum(c.total_errors for c in snapshot.counters)
                with_errors = sum(1 for c in snapshot.counters if c.total_errors > 0)

                color = COLORS["accent_green"] if total == 0 else COLORS["accent_red"]
                total_errors_label.text = f"Total Errors: {total}"
                total_errors_label.style(f"color: {color}")

                ports_with_errors_label.text = f"Ports with Errors: {with_errors}"
                ports_with_errors_label.style(f"color: {color}")

                set_status_live(status)
            except Exception as exc:
                set_status_error(status, exc)

        ui.timer(3.0, refresh)

    page_layout("MCU Error Counters", content)
