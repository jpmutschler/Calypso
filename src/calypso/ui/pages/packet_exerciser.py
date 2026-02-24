"""PCIe Packet Exerciser page -- traffic generation and PTrace integration.

Provides UI control for the Atlas3 PCIe Packet Exerciser hardware:
- Tab 1: Direct TLP generation with all 15 PCIe TLP types
- Tab 2: Integrated PTrace + Exerciser workflow for Gen6 validation
- Tab 3: Datapath BIST factory test
"""

from __future__ import annotations

import json
import re

from nicegui import ui

from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS


def packet_exerciser_page(device_id: str) -> None:
    """Render the Packet Exerciser page."""

    def content():
        _packet_exerciser_content(device_id)

    page_layout("Packet Exerciser", content, device_id=device_id)


# TLP type groups for dropdown
_TLP_TYPE_OPTIONS = {
    "mr32": "MR32 - 32-bit Memory Read",
    "mw32": "MW32 - 32-bit Memory Write",
    "mr64": "MR64 - 64-bit Memory Read",
    "mw64": "MW64 - 64-bit Memory Write",
    "cfrd0": "CfgRd0 - Type 0 Config Read",
    "cfwr0": "CfgWr0 - Type 0 Config Write",
    "cfrd1": "CfgRd1 - Type 1 Config Read",
    "cfwr1": "CfgWr1 - Type 1 Config Write",
    "PMNak": "PM NAK",
    "PME": "PME",
    "PMEOff": "PME Turn Off",
    "PMEAck": "PME Acknowledge",
    "ERRCor": "Correctable Error",
    "ERRNF": "Non-Fatal Error",
    "ERRF": "Fatal Error",
}

_CONFIG_TYPES = {"cfrd0", "cfwr0", "cfrd1", "cfwr1"}
_WRITE_TYPES = {"mw32", "mw64", "cfwr0", "cfwr1"}


def _packet_exerciser_content(device_id: str) -> None:  # noqa: C901
    """Build the Packet Exerciser page content."""

    if not re.match(r"^[a-zA-Z0-9_-]+$", device_id):
        ui.label("Invalid device ID").style(f"color: {COLORS.red};")
        return

    state: dict = {"port_number": 0}

    # --- API helpers ---

    def _exer_url(path: str, **params: object) -> str:
        base = f"/api/devices/{device_id}/exerciser/{path}"
        if params:
            qs = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
            return f"{base}?{qs}"
        return base

    def _js_post(url: str, body_js: str) -> str:
        return (
            f'return await (await fetch("{url}", {{'
            f'method: "POST", headers: {{"Content-Type": "application/json"}},'
            f"body: JSON.stringify({body_js})"
            f"}})).json()"
        )

    def _js_get(url: str) -> str:
        return f'return await (await fetch("{url}")).json()'

    # --- Port selector ---

    def _selected_port() -> int:
        val = port_select.value
        if val is None:
            return 0
        return int(val)

    async def load_ports():
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/ports")).json()',
                timeout=15.0,
            )
            active = [p for p in resp if p.get("is_link_up")]
            options: dict[str, str] = {}
            for p in active:
                pn = p["port_number"]
                role = p.get("role", "unknown")
                spd = p.get("link_speed", "unknown")
                width = p.get("link_width", 0)
                options[str(pn)] = f"Port {pn} ({role}, x{width} @ {spd})"
            port_select.options = options
            port_select.update()
            if active:
                port_select.set_value(str(active[0]["port_number"]))
        except Exception as e:
            ui.notify(f"Error loading ports: {e}", type="negative")

    def on_port_changed(_e=None):
        if port_select.value is not None:
            state["port_number"] = int(port_select.value)

    # --- Tab 1: Packet Exerciser actions ---

    async def send_tlps():
        port = _selected_port()
        tlp_type = tlp_type_select.value or "mr32"
        addr_str = addr_input.value or "0"
        length = int(length_input.value or 1)
        req_id_str = req_id_input.value or "0"
        infinite = infinite_toggle.value or False
        max_np = int(max_np_input.value or 8)

        tlp_cfg = {"tlp_type": tlp_type, "length_dw": length}
        try:
            tlp_cfg["address"] = int(addr_str, 16) if addr_str else 0
        except ValueError:
            try:
                tlp_cfg["address"] = int(addr_str) if addr_str else 0
            except ValueError:
                ui.notify(f"Invalid address: {addr_str}", type="negative")
                return
        try:
            tlp_cfg["requester_id"] = int(req_id_str, 16) if req_id_str else 0
        except ValueError:
            try:
                tlp_cfg["requester_id"] = int(req_id_str) if req_id_str else 0
            except ValueError:
                ui.notify(f"Invalid requester ID: {req_id_str}", type="negative")
                return

        if tlp_type in _CONFIG_TYPES:
            tgt_str = target_id_input.value or "0"
            try:
                tlp_cfg["target_id"] = int(tgt_str, 16)
            except ValueError:
                tlp_cfg["target_id"] = int(tgt_str) if tgt_str else 0

        if tlp_type in _WRITE_TYPES:
            data_str = data_input.value or None
            if data_str:
                tlp_cfg["data"] = data_str

        body = json.dumps({
            "port_number": port,
            "tlps": [tlp_cfg],
            "infinite_loop": infinite,
            "max_outstanding_np": max_np,
        })

        url = _exer_url("send")
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("{url}", {{'
                f'method: "POST", headers: {{"Content-Type": "application/json"}},'
                f"body: {json.dumps(body)}"
                f"}})).json()",
                timeout=15.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
            else:
                ui.notify("TLPs sent", type="positive")
                await refresh_status()
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def stop_exerciser():
        port = _selected_port()
        url = _exer_url("stop", port_number=port)
        try:
            resp = await ui.run_javascript(
                _js_post(url, "{}"),
                timeout=10.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
            else:
                ui.notify("Exerciser stopped", type="positive")
                await refresh_status()
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def refresh_status():
        port = _selected_port()
        url = _exer_url("status", port_number=port)
        try:
            resp = await ui.run_javascript(_js_get(url), timeout=10.0)
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            _update_status(resp)
        except Exception as e:
            ui.notify(f"Error reading status: {e}", type="negative")

    def _update_status(data: dict):
        enabled = data.get("enabled", False)
        status_enabled_label.set_text(f"Enabled: {'YES' if enabled else 'No'}")
        status_enabled_label.style(
            f"color: {COLORS.green if enabled else COLORS.text_muted};"
        )
        np_pending = data.get("np_pending", False)
        status_np_label.set_text(f"NP Pending: {'YES' if np_pending else 'No'}")

        cpl_recv = data.get("completion_received", False)
        cpl_status = data.get("completion_status", 0)
        cpl_data = data.get("completion_data", 0)
        status_cpl_label.set_text(
            f"Completion: {'Received' if cpl_recv else 'None'}"
            f" | Status: {cpl_status} | Data: 0x{cpl_data:08X}"
        )

        threads = data.get("threads", [])
        thread_lines = []
        for t in threads:
            tid = t.get("thread_id", 0)
            running = t.get("running", False)
            done = t.get("done", False)
            s = "RUNNING" if running else ("DONE" if done else "IDLE")
            thread_lines.append(f"T{tid}: {s}")
        status_threads_label.set_text("  ".join(thread_lines))

    def on_tlp_type_changed(_e=None):
        tlp_type = tlp_type_select.value or "mr32"
        target_id_input.set_visibility(tlp_type in _CONFIG_TYPES)
        data_input.set_visibility(tlp_type in _WRITE_TYPES)

    # --- Tab 2: PTrace + Exerciser actions ---

    async def capture_and_send():
        port = _selected_port()
        tlp_type = pt_tlp_type_select.value or "mr32"
        addr_str = pt_addr_input.value or "0"
        length = int(pt_length_input.value or 1)

        tlp_cfg = {"tlp_type": tlp_type, "length_dw": length}
        try:
            tlp_cfg["address"] = int(addr_str, 16) if addr_str else 0
        except ValueError:
            tlp_cfg["address"] = int(addr_str) if addr_str else 0

        if tlp_type in _WRITE_TYPES:
            data_str = pt_data_input.value or None
            if data_str:
                tlp_cfg["data"] = data_str

        body = json.dumps({
            "port_number": port,
            "ptrace_direction": "egress",
            "exerciser": {
                "port_number": port,
                "tlps": [tlp_cfg],
                "infinite_loop": False,
                "max_outstanding_np": 8,
            },
            "read_buffer": True,
            "post_trigger_wait_ms": int(pt_wait_input.value or 100),
        })

        url = _exer_url("capture-and-send")
        pt_status_label.set_text("Running capture + send...")
        pt_status_label.style(f"color: {COLORS.cyan};")

        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("{url}", {{'
                f'method: "POST", headers: {{"Content-Type": "application/json"}},'
                f"body: {json.dumps(body)}"
                f"}})).json()",
                timeout=30.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                pt_status_label.set_text("Error")
                pt_status_label.style(f"color: {COLORS.red};")
                return

            pt_status_label.set_text("Complete")
            pt_status_label.style(f"color: {COLORS.green};")
            ui.notify("Capture + Send complete", type="positive")

            # Display PTrace buffer results
            buffer_data = resp.get("ptrace_buffer")
            if buffer_data:
                _display_ptrace_buffer(buffer_data)

            exer_status = resp.get("exerciser_status")
            if exer_status:
                _update_status(exer_status)

        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")
            pt_status_label.set_text("Error")
            pt_status_label.style(f"color: {COLORS.red};")

    def _display_ptrace_buffer(buffer_data: dict):
        rows = buffer_data.get("rows", [])
        pt_buffer_container.clear()
        with pt_buffer_container:
            if not rows:
                ui.label("No trace data captured").style(
                    f"color: {COLORS.text_muted};"
                )
                return

            trig_row = buffer_data.get("trigger_row_addr", 0)
            ui.label(
                f"Captured {len(rows)} rows | "
                f"Trigger row: {trig_row} | "
                f"Wrapped: {buffer_data.get('tbuf_wrapped', False)}"
            ).classes("text-caption").style(f"color: {COLORS.text_secondary};")

            columns = [
                {"name": "row", "label": "Row", "field": "row", "align": "left"},
                {"name": "hex", "label": "Data (hex)", "field": "hex", "align": "left"},
            ]
            table_rows = []
            for r in rows[:64]:
                hex_str = r.get("hex_str", "")
                if hex_str and hex_str != "0" * len(hex_str):
                    table_rows.append({
                        "row": r.get("row_index", 0),
                        "hex": hex_str[:64] + ("..." if len(hex_str) > 64 else ""),
                    })

            if table_rows:
                ui.table(
                    columns=columns,
                    rows=table_rows,
                    row_key="row",
                ).classes("w-full").style(
                    f"background-color: {COLORS.bg_card};"
                )
            else:
                ui.label("All captured rows are empty").style(
                    f"color: {COLORS.text_muted};"
                )

    # --- Tab 3: DP BIST actions ---

    async def start_bist():
        port = _selected_port()
        loops = int(bist_loop_input.value or 1)
        inner = int(bist_inner_input.value or 1)
        delay = int(bist_delay_input.value or 0)
        infinite = bist_infinite_toggle.value or False

        body_obj = {
            "loop_count": loops,
            "inner_loop_count": inner,
            "delay_count": delay,
            "infinite": infinite,
        }
        url = _exer_url("dp-bist/start", port_number=port)
        try:
            resp = await ui.run_javascript(
                _js_post(url, json.dumps(body_obj)),
                timeout=10.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
            else:
                ui.notify("DP BIST started", type="positive")
                await refresh_bist_status()
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def stop_bist():
        port = _selected_port()
        url = _exer_url("dp-bist/stop", port_number=port)
        try:
            resp = await ui.run_javascript(_js_post(url, "{}"), timeout=10.0)
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
            else:
                ui.notify("DP BIST stopped", type="positive")
                await refresh_bist_status()
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def refresh_bist_status():
        port = _selected_port()
        url = _exer_url("dp-bist/status", port_number=port)
        try:
            resp = await ui.run_javascript(_js_get(url), timeout=10.0)
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            tx = resp.get("tx_done", False)
            rx = resp.get("rx_done", False)
            passed = resp.get("passed", True)
            bist_tx_label.set_text(f"TX Done: {'YES' if tx else 'No'}")
            bist_rx_label.set_text(f"RX Done: {'YES' if rx else 'No'}")
            bist_result_label.set_text(f"Result: {'PASS' if passed else 'FAIL'}")
            bist_result_label.style(
                f"color: {COLORS.green if passed else COLORS.red}; font-weight: bold;"
            )
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    # =====================================================================
    # UI Layout
    # =====================================================================

    # Port selector
    with ui.card().classes("w-full q-mb-md").style(
        f"background-color: {COLORS.bg_card}; border: 1px solid {COLORS.border};"
    ):
        with ui.row().classes("items-center q-gutter-md w-full"):
            ui.label("Port").style(
                f"color: {COLORS.text_primary}; font-weight: 500;"
            )
            port_select = ui.select(
                options={},
                on_change=on_port_changed,
            ).classes("min-w-[300px]").style(
                f"color: {COLORS.text_primary};"
            )
            ui.button("Refresh Ports", on_click=load_ports).props("flat dense")

    # Tabs
    with ui.tabs().classes("w-full").style(
        f"color: {COLORS.text_primary};"
    ) as tabs:
        tab_exerciser = ui.tab("Packet Exerciser").style(
            f"color: {COLORS.cyan};"
        )
        tab_ptrace = ui.tab("PTrace + Exerciser").style(
            f"color: {COLORS.cyan};"
        )
        tab_bist = ui.tab("DP BIST").style(
            f"color: {COLORS.cyan};"
        )

    with ui.tab_panels(tabs, value=tab_exerciser).classes("w-full"):

        # =================================================================
        # Tab 1: Packet Exerciser
        # =================================================================
        with ui.tab_panel(tab_exerciser):
            with ui.row().classes("w-full q-gutter-md"):
                # Left: TLP config
                with ui.card().classes("col q-pa-md").style(
                    f"background-color: {COLORS.bg_card};"
                    f" border: 1px solid {COLORS.border};"
                ):
                    ui.label("TLP Configuration").style(
                        f"color: {COLORS.cyan}; font-size: 1rem; font-weight: 600;"
                    )

                    tlp_type_select = ui.select(
                        options=_TLP_TYPE_OPTIONS,
                        value="mr32",
                        label="TLP Type",
                        on_change=on_tlp_type_changed,
                    ).classes("w-full")

                    with ui.row().classes("w-full q-gutter-sm"):
                        addr_input = ui.input(
                            label="Address (hex)", value="0"
                        ).classes("col")
                        length_input = ui.number(
                            label="Length (DWORDs)", value=1, min=1, max=1024
                        ).classes("col")

                    with ui.row().classes("w-full q-gutter-sm"):
                        req_id_input = ui.input(
                            label="Requester ID (hex)", value="0"
                        ).classes("col")
                        target_id_input = ui.input(
                            label="Target ID (hex)", value="0"
                        ).classes("col")
                        target_id_input.set_visibility(False)

                    data_input = ui.input(
                        label="Write Data (hex)", value=""
                    ).classes("w-full")
                    data_input.set_visibility(False)

                    ui.separator().style(f"background-color: {COLORS.border};")

                    with ui.row().classes("w-full q-gutter-sm"):
                        max_np_input = ui.number(
                            label="Max Outstanding NP", value=8, min=1, max=255
                        ).classes("col")

                    infinite_toggle = ui.switch("Infinite Loop").style(
                        f"color: {COLORS.text_primary};"
                    )

                    with ui.row().classes("q-gutter-sm q-mt-md"):
                        ui.button("Send", on_click=send_tlps).props(
                            "color=positive"
                        )
                        ui.button("Stop", on_click=stop_exerciser).props(
                            "color=negative"
                        )
                        ui.button(
                            "Refresh Status", on_click=refresh_status
                        ).props("flat")

                # Right: Status
                with ui.card().classes("col q-pa-md").style(
                    f"background-color: {COLORS.bg_card};"
                    f" border: 1px solid {COLORS.border};"
                ):
                    ui.label("Exerciser Status").style(
                        f"color: {COLORS.cyan}; font-size: 1rem; font-weight: 600;"
                    )
                    status_enabled_label = ui.label("Enabled: No").style(
                        f"color: {COLORS.text_muted};"
                    )
                    status_np_label = ui.label("NP Pending: No").style(
                        f"color: {COLORS.text_secondary};"
                    )
                    status_cpl_label = ui.label(
                        "Completion: None | Status: 0 | Data: 0x00000000"
                    ).style(f"color: {COLORS.text_secondary};")
                    ui.separator().style(f"background-color: {COLORS.border};")
                    ui.label("Threads").style(
                        f"color: {COLORS.text_primary}; font-weight: 500;"
                    )
                    status_threads_label = ui.label(
                        "T0: IDLE  T1: IDLE  T2: IDLE  T3: IDLE"
                    ).style(
                        f"color: {COLORS.text_secondary};"
                        " font-family: 'JetBrains Mono', monospace;"
                    )

        # =================================================================
        # Tab 2: PTrace + Exerciser
        # =================================================================
        with ui.tab_panel(tab_ptrace):
            with ui.row().classes("w-full q-gutter-md"):
                with ui.card().classes("col q-pa-md").style(
                    f"background-color: {COLORS.bg_card};"
                    f" border: 1px solid {COLORS.border};"
                ):
                    ui.label("TLP to Generate").style(
                        f"color: {COLORS.cyan}; font-size: 1rem; font-weight: 600;"
                    )
                    pt_tlp_type_select = ui.select(
                        options=_TLP_TYPE_OPTIONS,
                        value="mr32",
                        label="TLP Type",
                    ).classes("w-full")

                    with ui.row().classes("w-full q-gutter-sm"):
                        pt_addr_input = ui.input(
                            label="Address (hex)", value="0"
                        ).classes("col")
                        pt_length_input = ui.number(
                            label="Length (DWORDs)", value=1, min=1, max=1024
                        ).classes("col")

                    pt_data_input = ui.input(
                        label="Write Data (hex)", value=""
                    ).classes("w-full")

                    ui.separator().style(f"background-color: {COLORS.border};")

                    ui.label("Capture Settings").style(
                        f"color: {COLORS.text_primary}; font-weight: 500;"
                    )
                    with ui.row().classes("w-full q-gutter-sm"):
                        pt_wait_input = ui.number(
                            label="Post-trigger wait (ms)",
                            value=100, min=10, max=5000,
                        ).classes("col")

                    with ui.row().classes("q-gutter-sm q-mt-md items-center"):
                        ui.button(
                            "Capture & Send", on_click=capture_and_send
                        ).props("color=positive")
                        pt_status_label = ui.label("Ready").style(
                            f"color: {COLORS.text_muted};"
                        )

                with ui.card().classes("col q-pa-md").style(
                    f"background-color: {COLORS.bg_card};"
                    f" border: 1px solid {COLORS.border};"
                ):
                    ui.label("PTrace Buffer").style(
                        f"color: {COLORS.cyan}; font-size: 1rem; font-weight: 600;"
                    )
                    pt_buffer_container = ui.column().classes("w-full")
                    with pt_buffer_container:
                        ui.label("No capture yet").style(
                            f"color: {COLORS.text_muted};"
                        )

        # =================================================================
        # Tab 3: DP BIST
        # =================================================================
        with ui.tab_panel(tab_bist):
            with ui.row().classes("w-full q-gutter-md"):
                with ui.card().classes("col q-pa-md").style(
                    f"background-color: {COLORS.bg_card};"
                    f" border: 1px solid {COLORS.border};"
                ):
                    ui.label("Datapath BIST").style(
                        f"color: {COLORS.cyan}; font-size: 1rem; font-weight: 600;"
                    )

                    with ui.row().classes("w-full q-gutter-sm"):
                        bist_loop_input = ui.number(
                            label="Loop Count", value=1, min=1, max=65535
                        ).classes("col")
                        bist_inner_input = ui.number(
                            label="Inner Loop Count", value=1, min=1, max=32767
                        ).classes("col")
                        bist_delay_input = ui.number(
                            label="Delay Count", value=0, min=0, max=65535
                        ).classes("col")

                    bist_infinite_toggle = ui.switch("Infinite Loop").style(
                        f"color: {COLORS.text_primary};"
                    )

                    with ui.row().classes("q-gutter-sm q-mt-md"):
                        ui.button("Start BIST", on_click=start_bist).props(
                            "color=positive"
                        )
                        ui.button("Stop BIST", on_click=stop_bist).props(
                            "color=negative"
                        )
                        ui.button(
                            "Refresh Status", on_click=refresh_bist_status
                        ).props("flat")

                with ui.card().classes("col q-pa-md").style(
                    f"background-color: {COLORS.bg_card};"
                    f" border: 1px solid {COLORS.border};"
                ):
                    ui.label("BIST Status").style(
                        f"color: {COLORS.cyan}; font-size: 1rem; font-weight: 600;"
                    )
                    bist_tx_label = ui.label("TX Done: No").style(
                        f"color: {COLORS.text_secondary};"
                    )
                    bist_rx_label = ui.label("RX Done: No").style(
                        f"color: {COLORS.text_secondary};"
                    )
                    bist_result_label = ui.label("Result: --").style(
                        f"color: {COLORS.text_muted}; font-weight: bold;"
                    )

    # Auto-load ports on page load
    ui.timer(0.5, load_ports, once=True)
