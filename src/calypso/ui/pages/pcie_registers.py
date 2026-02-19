"""PCIe config space browser page."""

from __future__ import annotations

import asyncio
import json

from nicegui import ui

from calypso.ui.layout import page_layout
from calypso.ui.pages._capability_decode import render_capability
from calypso.ui.pages._register_decode import get_decode_for_offset
from calypso.ui.theme import COLORS


def pcie_registers_page(device_id: str) -> None:
    """Render the PCIe registers browser page."""

    def content():
        _pcie_registers_content(device_id)

    page_layout("PCIe Registers", content, device_id=device_id)


def _pcie_registers_content(device_id: str) -> None:
    """Build the PCIe registers page content."""

    config_data: dict = {"registers": [], "capabilities": []}
    device_ctrl: dict = {}
    link_info: dict = {"capabilities": {}, "status": {}}
    aer_data: dict = {"status": None}

    # --- Port selector helpers ---

    def _selected_port() -> int | None:
        val = port_select.value
        if val is None:
            return None
        return int(val)

    def _port_qs() -> str:
        pn = _selected_port()
        if pn is None:
            return ""
        return f"port_number={pn}"

    def _join_qs(*parts: str) -> str:
        non_empty = [p for p in parts if p]
        return "?" + "&".join(non_empty) if non_empty else ""

    def _pcie_cap_base() -> int | None:
        for c in config_data.get("capabilities", []):
            if c.get("cap_id") == 0x10:
                return c.get("offset")
        return None

    # --- Data loaders ---

    async def load_ports():
        """Fetch all ports and populate the port dropdown."""
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/ports")).json()',
                timeout=15.0,
            )
            options: dict[str, str] = {}
            first_key: str | None = None
            for p in resp:
                pn = p["port_number"]
                role = p.get("role", "unknown")
                is_up = p.get("is_link_up", False)
                if is_up:
                    speed = p.get("link_speed", "?")
                    width = p.get("link_width", 0)
                    label = f"Port {pn} ({role}, x{width} @ {speed})"
                else:
                    label = f"Port {pn} ({role}, DOWN)"
                key = str(pn)
                options[key] = label
                if first_key is None:
                    first_key = key

            port_select.options = options
            port_select.update()

            if first_key is not None:
                port_select.set_value(first_key)
        except Exception as e:
            ui.notify(f"Error loading ports: {e}", type="negative")

    async def on_port_changed(_e=None):
        if port_select.value is not None:
            await load_all()

    async def load_all():
        await asyncio.gather(
            load_config_space(),
            load_device_control(),
            load_link(),
            load_aer(),
        )

    async def load_config_space():
        offset = int(offset_input.value or 0)
        count = int(count_input.value or 64)
        qs = _join_qs(f"offset={offset}", f"count={count}", _port_qs())
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/config-space{qs}")).json()',
                timeout=10.0,
            )
            config_data["registers"] = resp.get("registers", [])
            config_data["capabilities"] = resp.get("capabilities", [])
            refresh_config_dump()
            refresh_caps_list()
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def load_device_control():
        qs = _join_qs(_port_qs())
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/device-control{qs}")).json()',
                timeout=10.0,
            )
            device_ctrl.update(resp)
            refresh_device_ctrl()
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def apply_device_control():
        mps_val = mps_select.value
        mrrs_val = mrrs_select.value
        body: dict = {}
        if mps_val:
            body["mps"] = int(mps_val)
        if mrrs_val:
            body["mrrs"] = int(mrrs_val)
        qs = _join_qs(_port_qs())
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/device-control{qs}", '
                f'{{method:"POST",headers:{{"Content-Type":"application/json"}},'
                f"body:JSON.stringify({json.dumps(body)})}})).json()",
                timeout=10.0,
            )
            device_ctrl.update(resp)
            refresh_device_ctrl()
            ui.notify("Device control updated", type="positive")
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def load_link():
        qs = _join_qs(_port_qs())
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/link{qs}")).json()',
                timeout=10.0,
            )
            link_info["capabilities"] = resp.get("capabilities", {})
            link_info["status"] = resp.get("status", {})
            refresh_link()
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def retrain():
        qs = _join_qs(_port_qs())
        try:
            await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/link/retrain{qs}", '
                f'{{method:"POST"}})).json()',
                timeout=10.0,
            )
            ui.notify("Link retraining initiated", type="positive")
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def set_target_speed():
        speed = int(speed_select.value)
        qs = _join_qs(_port_qs())
        try:
            await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/link/target-speed{qs}", '
                f'{{method:"POST",headers:{{"Content-Type":"application/json"}},'
                f"body:JSON.stringify({{speed:{speed}}})}})).json()",
                timeout=10.0,
            )
            ui.notify(f"Target speed set to Gen{speed}", type="positive")
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def load_aer():
        qs = _join_qs(_port_qs())
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/aer{qs}")).json()',
                timeout=10.0,
            )
            aer_data["status"] = resp
            refresh_aer()
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def clear_aer():
        qs = _join_qs(_port_qs())
        try:
            await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/aer/clear{qs}", '
                f'{{method:"POST"}})).json()',
                timeout=10.0,
            )
            ui.notify("AER errors cleared", type="positive")
            await load_aer()
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    # --- Phase 4: Config write ---

    async def _execute_config_write(offset_val: int, write_val: int):
        """POST the config write and refresh the dump."""
        qs = _join_qs(_port_qs())
        body = {"offset": offset_val, "value": write_val}
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/config-write{qs}", '
                f'{{method:"POST",headers:{{"Content-Type":"application/json"}},'
                f"body:JSON.stringify({json.dumps(body)})}})).json()",
                timeout=10.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
            else:
                ui.notify(
                    f"Written 0x{write_val:08X} at offset 0x{offset_val:03X}",
                    type="positive",
                )
                await load_config_space()
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def write_with_confirm():
        offset_str = write_offset_input.value or "0"
        value_str = write_value_input.value or "0"
        try:
            offset_val = int(offset_str, 16)
        except ValueError:
            ui.notify("Invalid offset. Use hex (e.g. 04).", type="negative")
            return
        try:
            write_val = int(value_str, 16)
        except ValueError:
            ui.notify("Invalid value. Use hex (e.g. DEADBEEF).", type="negative")
            return

        with (
            ui.dialog() as dialog,
            ui.card().style(
                f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
            ),
        ):
            ui.label("Confirm Config Write").classes("text-h6").style(
                f"color: {COLORS.text_primary}"
            )
            ui.label(f"Write 0x{write_val:08X} to offset 0x{offset_val:03X}?").style(
                f"color: {COLORS.text_secondary}"
            )
            pn = _selected_port()
            if pn is not None:
                ui.label(f"Target: Port {pn}").style(
                    f"color: {COLORS.text_secondary}; font-size: 13px"
                )
            ui.label("Config writes can affect device behavior!").style(
                f"color: {COLORS.yellow}; font-size: 13px"
            )
            with ui.row().classes("gap-4 mt-2"):
                ui.button("Cancel", on_click=dialog.close).props("flat")

                async def confirm():
                    dialog.close()
                    await _execute_config_write(offset_val, write_val)

                ui.button("Write", on_click=confirm).props("flat color=warning")
        dialog.open()

    # --- Inject CSS for scroll-highlight animation ---
    ui.add_css("""
        .cfg-highlight {
            background: rgba(0, 212, 255, 0.25) !important;
            transition: background 0.3s ease;
        }
    """)

    # === Port Selector Card ===
    with (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    ):
        with ui.row().classes("items-center gap-4"):
            ui.label("Target Port").classes("text-h6").style(f"color: {COLORS.text_primary}")
            port_select = ui.select(options={}, label="Port", on_change=on_port_changed).classes(
                "w-80"
            )
            ui.button("Refresh All", on_click=load_all).props("flat color=primary")

    # === Config Space Dump Card ===
    with (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    ):
        with ui.row().classes("items-center gap-4 mb-2"):
            ui.label("Config Space Dump").classes("text-h6").style(f"color: {COLORS.text_primary}")
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

                pcap = _pcie_cap_base()

                with (
                    ui.element("div")
                    .classes("w-full overflow-x-auto")
                    .style(
                        f"font-family: 'JetBrains Mono', monospace; "
                        f"font-size: 13px; background: {COLORS.bg_primary}; "
                        f"padding: 12px; border-radius: 4px; line-height: 1.6"
                    )
                ):
                    for i in range(0, len(regs), 4):
                        row_offset = regs[i]["offset"]
                        vals = " ".join(f"{r['value']:08X}" for r in regs[i : i + 4])

                        decode = get_decode_for_offset(row_offset, pcap)
                        annotation = ""
                        if decode is not None:
                            annotation = (
                                f'<span style="color: {COLORS.cyan}"> ; {decode.name}</span>'
                            )

                        html = (
                            f'<span id="cfg-0x{row_offset:03X}" '
                            f'style="display:inline-block; padding: 1px 4px; '
                            f'border-radius: 2px">'
                            f'<span style="color: {COLORS.text_muted}">'
                            f"0x{row_offset:03X}:</span> "
                            f'<span style="color: {COLORS.text_primary}">'
                            f"{vals}</span>"
                            f"{annotation}</span>"
                        )
                        ui.html(html)

        refresh_config_dump()

    # === Capabilities List Card (Phase 3: clickable + expandable) ===
    with (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    ):
        ui.label("Capabilities").classes("text-h6").style(f"color: {COLORS.text_primary}")

        caps_container = ui.column().classes("w-full")

        @ui.refreshable
        def refresh_caps_list():
            caps_container.clear()
            with caps_container:
                caps = config_data.get("capabilities", [])
                if not caps:
                    ui.label("Load config space first.").style(f"color: {COLORS.text_muted}")
                    return

                regs = config_data.get("registers", [])
                reg_map: dict[int, int] = {r["offset"]: r["value"] for r in regs}

                for cap in caps:
                    cap_id = cap["cap_id"]
                    cap_name = cap["cap_name"]
                    cap_offset = cap["offset"]
                    version = cap.get("version", 0)

                    if cap_offset >= 0x100:
                        header = f"0x{cap_id:04X} - {cap_name} @ 0x{cap_offset:03X}"
                        if version:
                            header += f" (v{version})"
                    else:
                        header = f"0x{cap_id:02X} - {cap_name} @ 0x{cap_offset:03X}"

                    with (
                        ui.expansion(header)
                        .classes("w-full")
                        .style(f"color: {COLORS.text_primary}")
                    ):
                        _render_scroll_button(cap_offset)
                        _render_capability_detail(cap, reg_map)

        def _render_scroll_button(offset: int):
            async def scroll_to():
                await ui.run_javascript(
                    f"""
                    (() => {{
                        const el = document.getElementById('cfg-0x{offset:03X}');
                        if (!el) return;
                        el.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
                        el.classList.add('cfg-highlight');
                        setTimeout(() => el.classList.remove('cfg-highlight'), 2000);
                    }})();
                    """,
                    timeout=5.0,
                )

            ui.button(f"Scroll to 0x{offset:03X}", on_click=scroll_to).props(
                "flat dense color=primary size=sm"
            ).classes("mb-2")

        def _render_capability_detail(cap: dict, reg_map: dict[int, int]):
            if not render_capability(cap, reg_map):
                _render_raw_dwords(cap["offset"], reg_map)

        def _render_raw_dwords(base: int, reg_map: dict[int, int]):
            """Show raw DWORDs for capabilities without a specific decoder."""
            with ui.element("pre").style(
                f"color: {COLORS.text_primary}; font-family: 'JetBrains Mono', monospace; "
                f"font-size: 13px"
            ):
                lines = []
                for i in range(4):
                    off = base + (i * 4)
                    val = reg_map.get(off, 0xFFFFFFFF)
                    lines.append(f"0x{off:03X}: {val:08X}")
                ui.html("<br>".join(lines))

        refresh_caps_list()

    # === Device Control Card ===
    with (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    ):
        with ui.row().classes("items-center gap-4 mb-2"):
            ui.label("Device Control").classes("text-h6").style(f"color: {COLORS.text_primary}")
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
                    ui.label("Select a port to load.").style(f"color: {COLORS.text_muted}")
                    return
                with ui.grid(columns=2).classes("gap-2"):
                    for key, val in device_ctrl.items():
                        ui.label(key.replace("_", " ").title()).style(
                            f"color: {COLORS.text_secondary}"
                        )
                        ui.label(str(val)).style(f"color: {COLORS.text_primary}")

        refresh_device_ctrl()

    # === Link Status Card ===
    with (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    ):
        with ui.row().classes("items-center gap-4 mb-2"):
            ui.label("Link Status").classes("text-h6").style(f"color: {COLORS.text_primary}")
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
                    ui.label("Select a port to load.").style(f"color: {COLORS.text_muted}")
                    return
                with ui.grid(columns=2).classes("gap-2"):
                    if status:
                        for key in [
                            "current_speed",
                            "current_width",
                            "target_speed",
                            "aspm_control",
                            "link_training",
                            "dll_link_active",
                        ]:
                            ui.label(key.replace("_", " ").title()).style(
                                f"color: {COLORS.text_secondary}"
                            )
                            val = status.get(key, "")
                            if key == "current_width":
                                val = f"x{val}"
                            ui.label(str(val)).style(f"color: {COLORS.text_primary}")
                    if caps:
                        ui.separator().classes("col-span-2")
                        for key in [
                            "max_link_speed",
                            "max_link_width",
                            "aspm_support",
                            "port_number",
                        ]:
                            ui.label(f"Max {key.replace('_', ' ').title()}").style(
                                f"color: {COLORS.text_secondary}"
                            )
                            val = caps.get(key, "")
                            if key == "max_link_width":
                                val = f"x{val}"
                            ui.label(str(val)).style(f"color: {COLORS.text_primary}")

        refresh_link()

    # === AER Status Card ===
    with (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    ):
        with ui.row().classes("items-center gap-4 mb-2"):
            ui.label("AER Status").classes("text-h6").style(f"color: {COLORS.text_primary}")
            ui.button("Refresh", on_click=load_aer).props("flat color=primary")
            ui.button("Clear Errors", on_click=clear_aer).props("flat color=negative")

        aer_container = ui.column().classes("w-full")

        @ui.refreshable
        def refresh_aer():
            aer_container.clear()
            with aer_container:
                status = aer_data.get("status")
                if status is None:
                    ui.label("Select a port to load.").style(f"color: {COLORS.text_muted}")
                    return

                if not status:
                    ui.label("AER capability not present.").style(f"color: {COLORS.text_muted}")
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
                            "data_link_protocol",
                            "surprise_down",
                            "poisoned_tlp",
                            "flow_control_protocol",
                            "completion_timeout",
                            "completer_abort",
                            "unexpected_completion",
                            "receiver_overflow",
                            "malformed_tlp",
                            "ecrc_error",
                            "unsupported_request",
                            "acs_violation",
                        ]:
                            val = uncorr.get(field, False)
                            color = COLORS.red if val else COLORS.text_muted
                            ui.label(f"{'!!' if val else '  '} {field.replace('_', ' ')}").style(
                                f"color: {color}; font-family: monospace; font-size: 13px"
                            )

                    with ui.column().classes("flex-1"):
                        corr = status.get("correctable", {})
                        raw = corr.get("raw_value", 0)
                        ui.label(f"Correctable (0x{raw:08X})").style(
                            f"color: {COLORS.text_primary}"
                        )
                        for field in [
                            "receiver_error",
                            "bad_tlp",
                            "bad_dllp",
                            "replay_num_rollover",
                            "replay_timer_timeout",
                            "advisory_non_fatal",
                        ]:
                            val = corr.get(field, False)
                            color = COLORS.yellow if val else COLORS.text_muted
                            ui.label(f"{'!!' if val else '  '} {field.replace('_', ' ')}").style(
                                f"color: {color}; font-family: monospace; font-size: 13px"
                            )

                header_log = status.get("header_log", [])
                if header_log:
                    ui.label("Header Log: " + " ".join(f"0x{h:08X}" for h in header_log)).style(
                        f"color: {COLORS.text_secondary}; font-family: monospace; font-size: 13px"
                    )

        refresh_aer()

    # === Register Write Card (Phase 4) ===
    with (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    ):
        with ui.row().classes("items-center gap-2 mb-2"):
            ui.label("Register Write").classes("text-h6").style(f"color: {COLORS.text_primary}")
            ui.icon("warning").style(f"color: {COLORS.yellow}")

        with ui.row().classes("items-end gap-4"):
            write_offset_input = ui.input("Offset (hex)", value="00").classes("w-32")
            write_value_input = ui.input("Value (hex)", value="00000000").classes("w-40")
            ui.button("Write", on_click=write_with_confirm).props("flat color=warning")

    # === Auto-load on page mount ===
    ui.timer(0.1, load_ports, once=True)
