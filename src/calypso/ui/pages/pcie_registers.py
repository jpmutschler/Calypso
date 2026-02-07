"""PCIe config space browser page."""

from __future__ import annotations

from nicegui import ui

from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS


def pcie_registers_page(device_id: str) -> None:
    """Render the PCIe registers browser page."""

    def content():
        _pcie_registers_content(device_id)

    page_layout("PCIe Registers", content, device_id=device_id)


def _pcie_registers_content(device_id: str) -> None:
    """Build the PCIe registers page content."""

    config_data = {"registers": [], "capabilities": []}
    device_ctrl = {}
    link_info = {"capabilities": {}, "status": {}}
    aer_data = {"status": None}

    async def load_config_space():
        offset = int(offset_input.value or 0)
        count = int(count_input.value or 64)
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/config-space?offset={offset}&count={count}")).json()'
            )
            config_data["registers"] = resp.get("registers", [])
            config_data["capabilities"] = resp.get("capabilities", [])
            refresh_config_dump()
            refresh_caps_table()
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def load_device_control():
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/device-control")).json()'
            )
            device_ctrl.update(resp)
            refresh_device_ctrl()
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def apply_device_control():
        mps_val = mps_select.value
        mrrs_val = mrrs_select.value
        body = {}
        if mps_val:
            body["mps"] = int(mps_val)
        if mrrs_val:
            body["mrrs"] = int(mrrs_val)
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/device-control", '
                f'{{method:"POST",headers:{{"Content-Type":"application/json"}},'
                f'body:JSON.stringify({body})}})).json()'
            )
            device_ctrl.update(resp)
            refresh_device_ctrl()
            ui.notify("Device control updated", type="positive")
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def load_link():
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/link")).json()'
            )
            link_info["capabilities"] = resp.get("capabilities", {})
            link_info["status"] = resp.get("status", {})
            refresh_link()
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def retrain():
        try:
            await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/link/retrain", '
                f'{{method:"POST"}})).json()'
            )
            ui.notify("Link retraining initiated", type="positive")
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def set_target_speed():
        speed = int(speed_select.value)
        try:
            await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/link/target-speed", '
                f'{{method:"POST",headers:{{"Content-Type":"application/json"}},'
                f'body:JSON.stringify({{speed:{speed}}})}})).json()'
            )
            ui.notify(f"Target speed set to Gen{speed}", type="positive")
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def load_aer():
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/aer")).json()'
            )
            aer_data["status"] = resp
            refresh_aer()
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def clear_aer():
        try:
            await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/aer/clear", '
                f'{{method:"POST"}})).json()'
            )
            ui.notify("AER errors cleared", type="positive")
            await load_aer()
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    # Config Space Dump
    with ui.card().classes("w-full p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    ):
        with ui.row().classes("items-center gap-4 mb-2"):
            ui.label("Config Space Dump").classes("text-h6").style(
                f"color: {COLORS.text_primary}"
            )
            offset_input = ui.number("Offset", value=0, min=0, step=4).classes("w-24")
            count_input = ui.number("Count", value=64, min=1, max=256).classes("w-24")
            ui.button("Read", on_click=load_config_space).props("flat color=primary")

        config_dump_container = ui.column().classes("w-full")

        @ui.refreshable
        def refresh_config_dump():
            config_dump_container.clear()
            with config_dump_container:
                regs = config_data.get("registers", [])
                if not regs:
                    ui.label("No data loaded.").style(f"color: {COLORS.text_muted}")
                    return
                with ui.element("pre").classes("w-full overflow-x-auto").style(
                    f"color: {COLORS.text_primary}; font-family: 'JetBrains Mono', monospace; "
                    f"font-size: 13px; background: {COLORS.bg_primary}; "
                    f"padding: 12px; border-radius: 4px"
                ):
                    lines = []
                    for i in range(0, len(regs), 4):
                        row_offset = regs[i]["offset"]
                        vals = " ".join(
                            f"{r['value']:08X}" for r in regs[i:i+4]
                        )
                        lines.append(f"0x{row_offset:03X}: {vals}")
                    ui.html("<br>".join(lines))

        refresh_config_dump()

    # Capabilities List
    with ui.card().classes("w-full p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    ):
        ui.label("Capabilities").classes("text-h6").style(
            f"color: {COLORS.text_primary}"
        )

        caps_container = ui.column().classes("w-full")

        @ui.refreshable
        def refresh_caps_table():
            caps_container.clear()
            with caps_container:
                caps = config_data.get("capabilities", [])
                if not caps:
                    ui.label("Load config space first.").style(
                        f"color: {COLORS.text_muted}"
                    )
                    return
                rows = [
                    {
                        "id": f"0x{c['cap_id']:02X}",
                        "name": c["cap_name"],
                        "offset": f"0x{c['offset']:03X}",
                        "version": c.get("version", 0),
                    }
                    for c in caps
                ]
                columns = [
                    {"name": "id", "label": "ID", "field": "id", "align": "left"},
                    {"name": "name", "label": "Name", "field": "name", "align": "left"},
                    {"name": "offset", "label": "Offset", "field": "offset", "align": "left"},
                    {"name": "version", "label": "Ver", "field": "version", "align": "left"},
                ]
                ui.table(columns=columns, rows=rows, row_key="offset").classes("w-full")

        refresh_caps_table()

    # Device Control
    with ui.card().classes("w-full p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    ):
        with ui.row().classes("items-center gap-4 mb-2"):
            ui.label("Device Control").classes("text-h6").style(
                f"color: {COLORS.text_primary}"
            )
            ui.button("Refresh", on_click=load_device_control).props("flat color=primary")

        with ui.row().classes("items-end gap-4 mb-2"):
            payload_opts = ["128", "256", "512", "1024", "2048", "4096"]
            mps_select = ui.select(payload_opts, label="MPS (bytes)").classes("w-32")
            mrrs_select = ui.select(payload_opts, label="MRRS (bytes)").classes("w-32")
            ui.button("Apply", on_click=apply_device_control).props("flat color=warning")

        dev_ctrl_container = ui.column().classes("w-full")

        @ui.refreshable
        def refresh_device_ctrl():
            dev_ctrl_container.clear()
            with dev_ctrl_container:
                if not device_ctrl:
                    ui.label("Click Refresh to load.").style(
                        f"color: {COLORS.text_muted}"
                    )
                    return
                with ui.grid(columns=2).classes("gap-2"):
                    for key, val in device_ctrl.items():
                        ui.label(key.replace("_", " ").title()).style(
                            f"color: {COLORS.text_secondary}"
                        )
                        ui.label(str(val)).style(
                            f"color: {COLORS.text_primary}"
                        )

        refresh_device_ctrl()

    # Link Status
    with ui.card().classes("w-full p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    ):
        with ui.row().classes("items-center gap-4 mb-2"):
            ui.label("Link Status").classes("text-h6").style(
                f"color: {COLORS.text_primary}"
            )
            ui.button("Refresh", on_click=load_link).props("flat color=primary")

        with ui.row().classes("items-end gap-4 mb-2"):
            speed_opts = {str(i): f"Gen{i}" for i in range(1, 7)}
            speed_select = ui.select(speed_opts, label="Target Speed", value="4").classes("w-32")
            ui.button("Set Speed", on_click=set_target_speed).props("flat color=warning")
            ui.button("Retrain", on_click=retrain).props("flat color=negative")

        link_container = ui.column().classes("w-full")

        @ui.refreshable
        def refresh_link():
            link_container.clear()
            with link_container:
                caps = link_info.get("capabilities", {})
                status = link_info.get("status", {})
                if not caps and not status:
                    ui.label("Click Refresh to load.").style(
                        f"color: {COLORS.text_muted}"
                    )
                    return
                with ui.grid(columns=2).classes("gap-2"):
                    if status:
                        for key in [
                            "current_speed", "current_width", "target_speed",
                            "aspm_control", "link_training", "dll_link_active",
                        ]:
                            ui.label(key.replace("_", " ").title()).style(
                                f"color: {COLORS.text_secondary}"
                            )
                            val = status.get(key, "")
                            color = COLORS.text_primary
                            if key == "current_width":
                                val = f"x{val}"
                            ui.label(str(val)).style(f"color: {color}")
                    if caps:
                        ui.separator().classes("col-span-2")
                        for key in [
                            "max_link_speed", "max_link_width", "aspm_support",
                            "port_number",
                        ]:
                            ui.label(f"Max {key.replace('_', ' ').title()}").style(
                                f"color: {COLORS.text_secondary}"
                            )
                            val = caps.get(key, "")
                            if key == "max_link_width":
                                val = f"x{val}"
                            ui.label(str(val)).style(
                                f"color: {COLORS.text_primary}"
                            )

        refresh_link()

    # AER Status
    with ui.card().classes("w-full p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    ):
        with ui.row().classes("items-center gap-4 mb-2"):
            ui.label("AER Status").classes("text-h6").style(
                f"color: {COLORS.text_primary}"
            )
            ui.button("Refresh", on_click=load_aer).props("flat color=primary")
            ui.button("Clear Errors", on_click=clear_aer).props("flat color=negative")

        aer_container = ui.column().classes("w-full")

        @ui.refreshable
        def refresh_aer():
            aer_container.clear()
            with aer_container:
                status = aer_data.get("status")
                if status is None:
                    ui.label("Click Refresh to load.").style(
                        f"color: {COLORS.text_muted}"
                    )
                    return

                if not status:
                    ui.label("AER capability not present.").style(
                        f"color: {COLORS.text_muted}"
                    )
                    return

                ui.label(
                    f"AER offset: 0x{status.get('aer_offset', 0):X} | "
                    f"First Error Pointer: {status.get('first_error_pointer', 0)}"
                ).style(f"color: {COLORS.text_secondary}")

                with ui.row().classes("w-full gap-4"):
                    with ui.column().classes("flex-1"):
                        uncorr = status.get("uncorrectable", {})
                        raw = uncorr.get("raw_value", 0)
                        ui.label(f"Uncorrectable (0x{raw:08X})").style(
                            f"color: {COLORS.text_primary}"
                        )
                        for field in [
                            "data_link_protocol", "surprise_down", "poisoned_tlp",
                            "flow_control_protocol", "completion_timeout",
                            "completer_abort", "unexpected_completion",
                            "receiver_overflow", "malformed_tlp", "ecrc_error",
                            "unsupported_request", "acs_violation",
                        ]:
                            val = uncorr.get(field, False)
                            color = COLORS.red if val else COLORS.text_muted
                            ui.label(
                                f"{'!!' if val else '  '} {field.replace('_', ' ')}"
                            ).style(f"color: {color}; font-family: monospace; font-size: 13px")

                    with ui.column().classes("flex-1"):
                        corr = status.get("correctable", {})
                        raw = corr.get("raw_value", 0)
                        ui.label(f"Correctable (0x{raw:08X})").style(
                            f"color: {COLORS.text_primary}"
                        )
                        for field in [
                            "receiver_error", "bad_tlp", "bad_dllp",
                            "replay_num_rollover", "replay_timer_timeout",
                            "advisory_non_fatal",
                        ]:
                            val = corr.get(field, False)
                            color = COLORS.yellow if val else COLORS.text_muted
                            ui.label(
                                f"{'!!' if val else '  '} {field.replace('_', ' ')}"
                            ).style(f"color: {color}; font-family: monospace; font-size: 13px")

                header_log = status.get("header_log", [])
                if header_log:
                    ui.label(
                        "Header Log: " + " ".join(f"0x{h:08X}" for h in header_log)
                    ).style(
                        f"color: {COLORS.text_secondary}; font-family: monospace; font-size: 13px"
                    )

        refresh_aer()
