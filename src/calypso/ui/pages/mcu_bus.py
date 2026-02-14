"""MCU I2C/I3C bus explorer page.

Provides connector/channel selector, read/write panels with hex dump,
bus scan table, and I3C ENTDAA tab.
"""

from __future__ import annotations

from nicegui import app, run, ui

from calypso.mcu import pool
from calypso.ui.components.mcu_common import (
    card_header,
    no_mcu_message,
    page_header,
    set_status_error,
    set_status_live,
    status_indicator,
)
from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS


def _mcu_bus_content() -> None:
    """Build the I2C/I3C bus explorer page content."""
    mcu_port = app.storage.user.get("mcu_port")
    if not mcu_port:
        no_mcu_message()
        return

    page_header("I2C / I3C Bus Explorer", f"MCU: {mcu_port}")

    with ui.tabs().classes("w-full") as tabs:
        i2c_tab = ui.tab("I2C")
        i3c_tab = ui.tab("I3C")

    with ui.tab_panels(tabs, value=i2c_tab).classes("w-full"):
        with ui.tab_panel(i2c_tab):
            _i2c_panel(mcu_port)
        with ui.tab_panel(i3c_tab):
            _i3c_panel(mcu_port)


def _i2c_panel(mcu_port: str) -> None:
    """Build the I2C tab content."""
    # Bus selector
    with ui.card().classes("w-full p-4").style(
        f"background: {COLORS.bg_card}; border: 1px solid {COLORS.border}"
    ):
        card_header("Bus Selection", "settings_input_component")
        with ui.row().classes("w-full gap-4 items-end"):
            connector_input = ui.number(
                "Connector", value=0, min=0, max=5, step=1
            ).classes("w-24")
            channel_input = ui.select(
                ["a", "b"], value="a", label="Channel"
            ).classes("w-24")

    # Scan section
    with ui.card().classes("w-full p-4 mt-4").style(
        f"background: {COLORS.bg_card}; border: 1px solid {COLORS.border}"
    ):
        card_header("Bus Scan", "radar")

        scan_table = ui.table(
            columns=[
                {"name": "address", "label": "Address", "field": "address", "align": "left"},
                {"name": "hex", "label": "Hex", "field": "hex", "align": "left"},
            ],
            rows=[],
        ).classes("w-full")

        scan_status = status_indicator()

        async def do_scan():
            try:
                cn = int(connector_input.value)
                ch = channel_input.value
                result = await run.io_bound(
                    lambda: pool.get_client(mcu_port).i2c_scan(connector=cn, channel=ch)
                )
                scan_table.rows = [
                    {"address": f"0x{addr:02X}", "hex": f"{addr}"}
                    for addr in result.devices
                ]
                scan_table.update()
                set_status_live(scan_status)
                scan_status.text = f"Found {result.device_count} device(s)"
            except Exception as exc:
                set_status_error(scan_status, exc)

        ui.button("Scan Bus", on_click=do_scan, icon="search").props("color=primary")

    # Read section
    with ui.card().classes("w-full p-4 mt-4").style(
        f"background: {COLORS.bg_card}; border: 1px solid {COLORS.border}"
    ):
        card_header("I2C Read", "download")
        with ui.row().classes("w-full gap-4 items-end"):
            read_addr = ui.input("Address (hex)", value="0x50").classes("w-32")
            read_reg = ui.input("Register (hex)", value="0x00").classes("w-32")
            read_count = ui.number("Count", value=16, min=1, max=256, step=1).classes("w-24")

        read_output = ui.textarea("Data").classes("w-full mt-2 font-mono").props("readonly outlined")
        read_status = status_indicator()

        async def do_read():
            try:
                cn = int(connector_input.value)
                ch = channel_input.value
                addr = int(read_addr.value, 0)
                reg = int(read_reg.value, 0)
                cnt = int(read_count.value)
                data = await run.io_bound(
                    lambda: pool.get_client(mcu_port).i2c_read(
                        address=addr, connector=cn, channel=ch,
                        read_bytes=cnt, register=reg,
                    )
                )
                # Format as hex dump with offset
                lines = []
                for i in range(0, len(data), 16):
                    chunk = data[i:i + 16]
                    hex_str = " ".join(f"{b:02X}" for b in chunk)
                    ascii_str = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
                    lines.append(f"{reg + i:04X}  {hex_str:<48}  {ascii_str}")
                read_output.value = "\n".join(lines)
                set_status_live(read_status)
            except Exception as exc:
                set_status_error(read_status, exc)

        ui.button("Read", on_click=do_read, icon="download").props("color=primary")

    # Write section
    with ui.card().classes("w-full p-4 mt-4").style(
        f"background: {COLORS.bg_card}; border: 1px solid {COLORS.border}"
    ):
        card_header("I2C Write", "upload")
        with ui.row().classes("w-full gap-4 items-end"):
            write_addr = ui.input("Address (hex)", value="0x50").classes("w-32")
            write_data = ui.input(
                "Data (hex, comma-sep)", value="0x00,0x01"
            ).classes("flex-1")

        write_status = status_indicator()

        async def do_write():
            try:
                cn = int(connector_input.value)
                ch = channel_input.value
                addr = int(write_addr.value, 0)
                payload = [int(p.strip(), 0) for p in write_data.value.split(",")]
                success = await run.io_bound(
                    lambda: pool.get_client(mcu_port).i2c_write(
                        address=addr, connector=cn, channel=ch, data=payload,
                    )
                )
                write_status.text = "Write OK" if success else "Write FAILED"
                write_status.style(
                    f"color: {COLORS.green if success else COLORS.red}"
                )
            except Exception as exc:
                set_status_error(write_status, exc)

        ui.button("Write", on_click=do_write, icon="upload").props("color=warning")


def _i3c_panel(mcu_port: str) -> None:
    """Build the I3C tab content."""
    with ui.card().classes("w-full p-4").style(
        f"background: {COLORS.bg_card}; border: 1px solid {COLORS.border}"
    ):
        card_header("Bus Selection", "settings_input_component")
        with ui.row().classes("w-full gap-4 items-end"):
            connector_input = ui.number(
                "Connector", value=0, min=0, max=5, step=1
            ).classes("w-24")
            channel_input = ui.select(
                ["a", "b"], value="a", label="Channel"
            ).classes("w-24")

    # ENTDAA scan
    with ui.card().classes("w-full p-4 mt-4").style(
        f"background: {COLORS.bg_card}; border: 1px solid {COLORS.border}"
    ):
        card_header("I3C ENTDAA Discovery", "radar")

        entdaa_table = ui.table(
            columns=[
                {"name": "addr", "label": "Address", "field": "addr", "align": "left"},
                {"name": "pid", "label": "Provisional ID", "field": "pid", "align": "left"},
                {"name": "bcr", "label": "BCR", "field": "bcr", "align": "left"},
                {"name": "dcr", "label": "DCR", "field": "dcr", "align": "left"},
                {"name": "mctp", "label": "MCTP", "field": "mctp", "align": "center"},
            ],
            rows=[],
        ).classes("w-full")

        entdaa_status = status_indicator()

        async def do_entdaa():
            try:
                cn = int(connector_input.value)
                ch = channel_input.value
                result = await run.io_bound(
                    lambda: pool.get_client(mcu_port).i3c_entdaa(connector=cn, channel=ch)
                )
                entdaa_table.rows = [
                    {
                        "addr": f"0x{dev.dynamic_address:02X}",
                        "pid": dev.pid_hex,
                        "bcr": f"0x{dev.bcr:02X}",
                        "dcr": f"0x{dev.dcr:02X}",
                        "mctp": "Yes" if dev.supports_mctp else "No",
                    }
                    for dev in result.devices
                ]
                entdaa_table.update()
                set_status_live(entdaa_status)
                entdaa_status.text = f"Found {result.device_count} device(s)"
            except Exception as exc:
                set_status_error(entdaa_status, exc)

        ui.button("Run ENTDAA", on_click=do_entdaa, icon="search").props("color=primary")

    # I3C Read
    with ui.card().classes("w-full p-4 mt-4").style(
        f"background: {COLORS.bg_card}; border: 1px solid {COLORS.border}"
    ):
        card_header("I3C Read", "download")
        with ui.row().classes("w-full gap-4 items-end"):
            i3c_read_addr = ui.input("Address (hex)", value="0x08").classes("w-32")
            i3c_read_reg = ui.input("Register (hex)", value="0x0000").classes("w-32")
            i3c_read_count = ui.number("Count", value=16, min=1, max=256, step=1).classes("w-24")

        i3c_read_output = ui.textarea("Data").classes("w-full mt-2 font-mono").props("readonly outlined")
        i3c_read_status = status_indicator()

        async def do_i3c_read():
            try:
                cn = int(connector_input.value)
                ch = channel_input.value
                addr = int(i3c_read_addr.value, 0)
                reg = int(i3c_read_reg.value, 0)
                cnt = int(i3c_read_count.value)
                result = await run.io_bound(
                    lambda: pool.get_client(mcu_port).i3c_read(
                        address=addr, connector=cn, channel=ch,
                        read_bytes=cnt, register=reg,
                    )
                )
                lines = []
                for i in range(0, len(result.data), 16):
                    chunk = result.data[i:i + 16]
                    hex_str = " ".join(f"{b:02X}" for b in chunk)
                    ascii_str = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
                    lines.append(f"{reg + i:04X}  {hex_str:<48}  {ascii_str}")
                i3c_read_output.value = "\n".join(lines)
                set_status_live(i3c_read_status)
            except Exception as exc:
                set_status_error(i3c_read_status, exc)

        ui.button("Read", on_click=do_i3c_read, icon="download").props("color=primary")

    # I3C Write
    with ui.card().classes("w-full p-4 mt-4").style(
        f"background: {COLORS.bg_card}; border: 1px solid {COLORS.border}"
    ):
        card_header("I3C Write", "upload")
        with ui.row().classes("w-full gap-4 items-end"):
            i3c_write_addr = ui.input("Address (hex)", value="0x08").classes("w-32")
            i3c_write_reg = ui.input("Register (hex)", value="0x0000").classes("w-32")
            i3c_write_data = ui.input(
                "Data (hex, comma-sep)", value="0x00,0x01"
            ).classes("flex-1")

        i3c_write_status = status_indicator()

        async def do_i3c_write():
            try:
                cn = int(connector_input.value)
                ch = channel_input.value
                addr = int(i3c_write_addr.value, 0)
                reg = int(i3c_write_reg.value, 0)
                payload = [int(p.strip(), 0) for p in i3c_write_data.value.split(",")]
                success = await run.io_bound(
                    lambda: pool.get_client(mcu_port).i3c_write(
                        address=addr, connector=cn, channel=ch,
                        data=payload, register=reg,
                    )
                )
                i3c_write_status.text = "Write OK" if success else "Write FAILED"
                i3c_write_status.style(
                    f"color: {COLORS.green if success else COLORS.red}"
                )
            except Exception as exc:
                set_status_error(i3c_write_status, exc)

        ui.button("Write", on_click=do_i3c_write, icon="upload").props("color=warning")


def mcu_bus_page() -> None:
    """Render the I2C/I3C bus explorer page."""
    page_layout("I2C / I3C Bus", _mcu_bus_content)
