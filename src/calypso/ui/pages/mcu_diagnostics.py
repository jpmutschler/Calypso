"""MCU diagnostics page - BIST, version info, register access, resets."""

from __future__ import annotations

from nicegui import app, run, ui

from calypso.mcu import pool
from calypso.ui.components.mcu_common import (
    card_header,
    card_style,
    no_mcu_message,
    page_header,
)
from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS


def mcu_diagnostics_page() -> None:
    """Render the MCU diagnostics page."""

    def content():
        mcu_port = app.storage.user.get("mcu_port")
        if not mcu_port:
            no_mcu_message()
            return

        page_header("Diagnostics", f"MCU: {mcu_port}")

        # Version Info
        with ui.card().classes("w-full p-4").style(card_style()):
            card_header("Version Info", "info")
            version_grid = ui.column().classes("gap-1")

            async def load_version():
                current_port = app.storage.user.get("mcu_port")
                if not current_port:
                    return
                try:
                    v = await run.io_bound(
                        lambda: pool.get_client(current_port).get_version()
                    )
                    version_grid.clear()
                    with version_grid:
                        for label, value in [
                            ("Company", v.company),
                            ("Model", v.model),
                            ("Serial Number", v.serial_number),
                            ("MCU Version", v.mcu_version),
                            ("MCU Build Time", v.mcu_build_time),
                            ("SBR Version", v.sbr_version),
                        ]:
                            with ui.row().classes("gap-2"):
                                ui.label(f"{label}:").classes("text-caption w-32").style(
                                    f"color: {COLORS['text_muted']}"
                                )
                                ui.label(value or "--").classes("text-body2").style(
                                    f"color: {COLORS['text_primary']}"
                                )
                except Exception as exc:
                    version_grid.clear()
                    with version_grid:
                        ui.label(f"Error: {str(exc)[:200]}").style(
                            f"color: {COLORS['accent_red']}"
                        )

            ui.button("Refresh", icon="refresh", on_click=load_version).classes("mt-2").style(
                f"background: {COLORS['accent_blue']}"
            )

        # BIST
        with ui.card().classes("w-full p-4 mt-4").style(card_style()):
            card_header("Built-In Self Test", "bug_report")
            bist_container = ui.column().classes("w-full gap-2")

            with bist_container:
                ui.label("Click Run BIST to test all devices.").style(
                    f"color: {COLORS['text_muted']}"
                )

            async def run_bist():
                current_port = app.storage.user.get("mcu_port")
                if not current_port:
                    return
                bist_container.clear()
                with bist_container:
                    ui.label("Running BIST...").style(
                        f"color: {COLORS['accent_yellow']}"
                    )
                try:
                    result = await run.io_bound(
                        lambda: pool.get_client(current_port).run_bist()
                    )
                    bist_container.clear()
                    with bist_container:
                        all_ok = result.all_passed
                        summary_color = COLORS["accent_green"] if all_ok else COLORS["accent_red"]
                        ui.label(
                            "All Passed" if all_ok else "Some Failures Detected"
                        ).classes("text-subtitle2").style(f"color: {summary_color}")

                        if result.devices:
                            columns = [
                                {"name": "device_id", "label": "Device", "field": "device_id", "align": "left"},
                                {"name": "status", "label": "Status", "field": "status", "align": "center"},
                            ]
                            rows = [
                                {"device_id": d.device_id, "status": d.status}
                                for d in result.devices
                            ]
                            ui.table(columns=columns, rows=rows, row_key="device_id").classes(
                                "w-full"
                            )
                except Exception as exc:
                    bist_container.clear()
                    with bist_container:
                        ui.label(f"BIST failed: {str(exc)[:200]}").style(
                            f"color: {COLORS['accent_red']}"
                        )

            ui.button("Run BIST", icon="play_arrow", on_click=run_bist).style(
                f"background: {COLORS['accent_blue']}"
            )

        # Register Read
        with ui.card().classes("w-full p-4 mt-4").style(card_style()):
            card_header("Register Read", "memory")
            with ui.row().classes("items-end gap-4"):
                addr_input = ui.input(
                    "Address (hex)", value="0x0", placeholder="0x0"
                ).classes("w-40")
                count_input = ui.number("Count", value=16, min=1, max=256).classes("w-32")

            reg_output = ui.column().classes("w-full gap-1 mt-2 font-mono")

            async def read_registers():
                current_port = app.storage.user.get("mcu_port")
                if not current_port:
                    return
                reg_output.clear()
                try:
                    addr_str = (addr_input.value or "0x0").strip()
                    address = int(addr_str, 0)
                    if not (0 <= address <= 0xFFFFFFFF):
                        with reg_output:
                            ui.label("Address must be 0x0 - 0xFFFFFFFF").style(
                                f"color: {COLORS['accent_yellow']}"
                            )
                        return

                    count = int(count_input.value or 16)
                    if not (1 <= count <= 256):
                        with reg_output:
                            ui.label("Count must be 1 - 256").style(
                                f"color: {COLORS['accent_yellow']}"
                            )
                        return

                    regs = await run.io_bound(
                        lambda: pool.get_client(current_port).read_register(address, count)
                    )
                    with reg_output:
                        for addr, val in sorted(regs.items()):
                            ui.label(f"0x{addr:08X}: 0x{val:08X}").style(
                                f"color: {COLORS['text_primary']}"
                            )
                except ValueError:
                    with reg_output:
                        ui.label("Invalid address or count format").style(
                            f"color: {COLORS['accent_yellow']}"
                        )
                except Exception as exc:
                    with reg_output:
                        ui.label(f"Error: {str(exc)[:200]}").style(
                            f"color: {COLORS['accent_red']}"
                        )

            ui.button("Read", icon="download", on_click=read_registers).classes("mt-2").style(
                f"background: {COLORS['accent_blue']}"
            )

        # Resets
        with ui.card().classes("w-full p-4 mt-4").style(card_style()):
            card_header("Reset", "restart_alt")
            ui.label(
                "Warning: Reset operations will interrupt active connections."
            ).classes("text-caption mb-3").style(
                f"color: {COLORS['accent_yellow']}"
            )
            with ui.row().classes("gap-4"):
                async def reset_mcu():
                    current_port = app.storage.user.get("mcu_port")
                    if not current_port:
                        return
                    try:
                        await run.io_bound(
                            lambda: pool.get_client(current_port).reset_mcu()
                        )
                        pool.disconnect(current_port)
                        ui.notify("MCU reset initiated", type="warning")
                    except Exception as exc:
                        ui.notify(f"Reset failed: {exc}", type="negative")

                ui.button("Reset MCU", icon="restart_alt", on_click=reset_mcu).props(
                    "color=negative"
                )

        # Load version info on page load
        ui.timer(0.1, load_version, once=True)

    page_layout("MCU Diagnostics", content)
