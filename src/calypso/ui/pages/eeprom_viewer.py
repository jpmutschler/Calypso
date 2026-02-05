"""EEPROM viewer page."""

from __future__ import annotations

from nicegui import ui

from calypso.ui.theme import COLORS, CSS


def eeprom_viewer_page(device_id: str) -> None:
    """Render the EEPROM viewer page."""
    ui.add_head_html(f"<style>{CSS}</style>")

    eeprom_info: dict = {}
    eeprom_data: dict = {"values": [], "offset": 0}
    crc_data: dict = {}

    # --- Data loaders ---

    async def load_info():
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/eeprom/info")).json()'
            )
            eeprom_info.clear()
            eeprom_info.update(resp)
            refresh_info()
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def load_data():
        offset = int(read_offset_input.value or 0)
        count = int(read_count_input.value or 16)
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/eeprom/read?offset={offset}&count={count}")).json()'
            )
            eeprom_data.clear()
            eeprom_data.update(resp)
            refresh_data()
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def do_write():
        offset = int(write_offset_input.value or 0)
        value_str = write_value_input.value or "0"
        try:
            value = int(value_str, 0)
        except ValueError:
            ui.notify("Invalid value. Use hex (0x...) or decimal.", type="negative")
            return
        try:
            await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/eeprom/write", '
                f'{{method:"POST",headers:{{"Content-Type":"application/json"}},'
                f'body:JSON.stringify({{offset:{offset},value:{value}}})}})).json()'
            )
            ui.notify(f"Written 0x{value:08X} at offset 0x{offset:04X}", type="positive")
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def write_with_confirm():
        offset = int(write_offset_input.value or 0)
        value_str = write_value_input.value or "0"
        try:
            value = int(value_str, 0)
        except ValueError:
            ui.notify("Invalid value. Use hex (0x...) or decimal.", type="negative")
            return

        with ui.dialog() as dialog, ui.card().style(
            f"background: {COLORS['bg_secondary']}; border: 1px solid {COLORS['border']}"
        ):
            ui.label("Confirm EEPROM Write").classes("text-h6").style(
                f"color: {COLORS['text_primary']}"
            )
            ui.label(
                f"Write 0x{value:08X} to offset 0x{offset:04X}?"
            ).style(f"color: {COLORS['text_secondary']}")
            ui.label(
                "EEPROM writes are persistent and may affect device behavior."
            ).style(f"color: {COLORS['accent_yellow']}; font-size: 13px")
            with ui.row().classes("gap-4 mt-2"):
                ui.button("Cancel", on_click=dialog.close).props("flat")

                async def confirm():
                    dialog.close()
                    await do_write()

                ui.button("Write", on_click=confirm).props("flat color=warning")
        dialog.open()

    async def load_crc():
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/eeprom/crc")).json()'
            )
            crc_data.clear()
            crc_data.update(resp)
            refresh_crc()
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def update_crc():
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/eeprom/crc/update", '
                f'{{method:"POST"}})).json()'
            )
            crc_val = resp.get("crc_value") or 0
            ui.notify(f"CRC updated: 0x{crc_val:08X}", type="positive")
            await load_crc()
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    # --- Page layout ---

    with ui.column().classes("w-full p-4 gap-4"):
        ui.label("EEPROM Viewer").classes("text-h5").style(
            f"color: {COLORS['text_primary']}"
        )
        ui.label(f"Device: {device_id}").style(f"color: {COLORS['text_secondary']}")

        # Info card
        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS['bg_secondary']}; border: 1px solid {COLORS['border']}"
        ):
            with ui.row().classes("items-center gap-4 mb-2"):
                ui.label("EEPROM Status").classes("text-h6").style(
                    f"color: {COLORS['text_primary']}"
                )
                ui.button("Probe", on_click=load_info).props("flat color=primary")

            info_container = ui.column().classes("w-full")

            @ui.refreshable
            def refresh_info():
                info_container.clear()
                with info_container:
                    if not eeprom_info:
                        ui.label("Click Probe to check EEPROM.").style(
                            f"color: {COLORS['text_muted']}"
                        )
                        return

                    present = eeprom_info.get("present", False)
                    status = eeprom_info.get("status", "unknown")
                    crc_value = eeprom_info.get("crc_value") or 0
                    crc_status = eeprom_info.get("crc_status", "unknown")

                    with ui.row().classes("gap-6"):
                        _status_indicator(
                            "Present",
                            str(present),
                            COLORS["accent_green"] if present else COLORS["accent_red"],
                        )
                        _status_indicator(
                            "Status",
                            status,
                            COLORS["accent_green"] if status == "valid"
                            else COLORS["accent_red"] if status == "invalid"
                            else COLORS["text_primary"],
                        )
                        _status_indicator(
                            "CRC",
                            f"0x{crc_value:08X}",
                            COLORS["text_primary"],
                        )
                        _status_indicator(
                            "CRC Status",
                            crc_status,
                            COLORS["accent_green"] if crc_status == "valid"
                            else COLORS["accent_red"] if crc_status == "invalid"
                            else COLORS["text_muted"],
                        )

            refresh_info()

        # Read card
        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS['bg_secondary']}; border: 1px solid {COLORS['border']}"
        ):
            with ui.row().classes("items-end gap-4 mb-2"):
                ui.label("Read EEPROM").classes("text-h6").style(
                    f"color: {COLORS['text_primary']}"
                )
                read_offset_input = ui.number(
                    "Offset", value=0, min=0, step=4
                ).classes("w-28")
                read_count_input = ui.number(
                    "Count (DWORDs)", value=16, min=1, max=256
                ).classes("w-32")
                ui.button("Read", on_click=load_data).props("flat color=primary")

            data_container = ui.column().classes("w-full")

            @ui.refreshable
            def refresh_data():
                data_container.clear()
                with data_container:
                    values = eeprom_data.get("values", [])
                    if not values:
                        ui.label("No data loaded.").style(
                            f"color: {COLORS['text_muted']}"
                        )
                        return
                    base_offset = eeprom_data.get("offset") or 0
                    with ui.element("pre").classes("w-full overflow-x-auto").style(
                        f"color: {COLORS['text_primary']}; font-family: 'JetBrains Mono', monospace; "
                        f"font-size: 13px; background: {COLORS['bg_primary']}; "
                        f"padding: 12px; border-radius: 4px"
                    ):
                        lines = []
                        for i in range(0, len(values), 4):
                            row_offset = base_offset + (i * 4)
                            row_vals = " ".join(
                                f"{v:08X}" for v in values[i:i + 4]
                            )
                            lines.append(f"0x{row_offset:04X}: {row_vals}")
                        ui.html("<br>".join(lines))

                    # Summary
                    total_bytes = len(values) * 4
                    ui.label(
                        f"{len(values)} DWORDs ({total_bytes} bytes) "
                        f"from offset 0x{base_offset:04X}"
                    ).style(
                        f"color: {COLORS['text_muted']}; font-size: 12px; margin-top: 4px"
                    )

            refresh_data()

        # Write card
        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS['bg_secondary']}; border: 1px solid {COLORS['border']}"
        ):
            with ui.row().classes("items-center gap-2 mb-2"):
                ui.label("Write EEPROM").classes("text-h6").style(
                    f"color: {COLORS['text_primary']}"
                )
                ui.icon("warning").style(f"color: {COLORS['accent_yellow']}")

            with ui.row().classes("items-end gap-4"):
                write_offset_input = ui.number(
                    "Offset", value=0, min=0, step=4
                ).classes("w-32")
                write_value_input = ui.input(
                    "Value (hex)", value="0x00000000"
                ).classes("w-40")
                ui.button("Write", on_click=write_with_confirm).props(
                    "flat color=warning"
                )

        # CRC Management card
        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS['bg_secondary']}; border: 1px solid {COLORS['border']}"
        ):
            with ui.row().classes("items-center gap-4 mb-2"):
                ui.label("CRC Management").classes("text-h6").style(
                    f"color: {COLORS['text_primary']}"
                )
                ui.button("Verify", on_click=load_crc).props("flat color=primary")
                ui.button("Recalculate & Write", on_click=update_crc).props(
                    "flat color=warning"
                )

            crc_container = ui.column().classes("w-full")

            @ui.refreshable
            def refresh_crc():
                crc_container.clear()
                with crc_container:
                    if not crc_data:
                        ui.label("Click Verify to check CRC.").style(
                            f"color: {COLORS['text_muted']}"
                        )
                        return
                    crc_val = crc_data.get("crc_value") or 0
                    crc_status = crc_data.get("status", "unknown")

                    status_color = (
                        COLORS["accent_green"] if crc_status == "valid"
                        else COLORS["accent_red"] if crc_status == "invalid"
                        else COLORS["accent_yellow"]
                    )

                    with ui.row().classes("items-center gap-4"):
                        icon = (
                            "check_circle" if crc_status == "valid"
                            else "error" if crc_status == "invalid"
                            else "help_outline"
                        )
                        ui.icon(icon).classes("text-xl").style(
                            f"color: {status_color}"
                        )
                        ui.label(f"CRC: 0x{crc_val:08X}").style(
                            f"color: {COLORS['text_primary']}; "
                            f"font-family: 'JetBrains Mono', monospace"
                        )
                        ui.label(crc_status.upper()).style(
                            f"color: {status_color}; font-weight: bold"
                        )

            refresh_crc()


def _status_indicator(label: str, value: str, color: str) -> None:
    """Render a labeled status value."""
    with ui.column().classes("items-center"):
        ui.label(value).classes("text-subtitle1").style(
            f"color: {color}; font-weight: bold"
        )
        ui.label(label).style(
            f"color: {COLORS['text_muted']}; font-size: 12px"
        )
