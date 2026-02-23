"""PTrace (Protocol Trace) page -- dedicated embedded protocol analyser UI.

Provides full control over the Atlas3 PTrace hardware: capture config,
trigger/filter settings, error triggers, event counters, status readback,
and 600-bit-wide trace buffer display with CSV/hex export.
"""

from __future__ import annotations

import csv
import io
import json
import re

from nicegui import ui

from calypso.hardware.ptrace_regs import PORT_ERR_NAMES
from calypso.ui.layout import page_layout
from calypso.ui.pages._ptrace_flit_tab import build_flit_tab, get_trigger_src_options
from calypso.ui.theme import COLORS


def ptrace_page(device_id: str) -> None:
    """Render the Protocol Trace page."""

    def content():
        _ptrace_content(device_id)

    page_layout("Protocol Trace", content, device_id=device_id)


def _ptrace_content(device_id: str) -> None:
    """Build the PTrace page content."""

    # Sanitize device_id — it is interpolated into JavaScript strings for
    # fetch() calls, so reject anything that could break out of the URL.
    if not re.match(r"^[a-zA-Z0-9_-]+$", device_id):
        ui.label("Invalid device ID").style(f"color: {COLORS.red};")
        return

    state: dict = {
        "port_number": 0,
        "direction": "ingress",
        "auto_poll": False,
    }
    poll_timer: dict = {"status": None}

    # --- API helper ---

    def _api_url(path: str, **params: object) -> str:
        base = f"/api/devices/{device_id}/ptrace/{path}"
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

    # --- Control actions ---

    async def start_capture():
        port = state["port_number"]
        direction = state["direction"]
        url = _api_url("start")
        try:
            resp = await ui.run_javascript(
                _js_post(url, f'{{port_number: {port}, direction: "{direction}"}}'),
                timeout=10.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            ui.notify("Capture started", type="positive")
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def stop_capture():
        port = state["port_number"]
        direction = state["direction"]
        url = _api_url("stop")
        try:
            resp = await ui.run_javascript(
                _js_post(url, f'{{port_number: {port}, direction: "{direction}"}}'),
                timeout=10.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            ui.notify("Capture stopped", type="positive")
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def clear_triggered():
        port = state["port_number"]
        direction = state["direction"]
        url = _api_url("clear")
        try:
            resp = await ui.run_javascript(
                _js_post(url, f'{{port_number: {port}, direction: "{direction}"}}'),
                timeout=10.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            ui.notify("Trigger cleared", type="positive")
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def manual_trigger():
        port = state["port_number"]
        direction = state["direction"]
        url = _api_url("manual-trigger")
        try:
            resp = await ui.run_javascript(
                _js_post(url, f'{{port_number: {port}, direction: "{direction}"}}'),
                timeout=10.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            ui.notify("Manual trigger issued", type="positive")
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def read_status():
        port = state["port_number"]
        direction = state["direction"]
        url = _api_url("status", port_number=port, direction=direction)
        try:
            resp = await ui.run_javascript(_js_get(url), timeout=10.0)
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            _update_status_display(resp)
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    def _update_status_display(data: dict):
        cap = data.get("capture_in_progress", False)
        trig = data.get("triggered", False)
        wrapped = data.get("tbuf_wrapped", False)
        ram = data.get("ram_init_done", False)
        compress = data.get("compress_cnt", 0)

        status_cap_label.set_text(f"{'ACTIVE' if cap else 'IDLE'}")
        status_cap_label.style(
            f"color: {COLORS.green if cap else COLORS.text_muted}; font-weight: bold;"
        )
        status_trig_label.set_text(f"Triggered: {'YES' if trig else 'No'}")
        status_trig_label.style(
            f"color: {COLORS.yellow if trig else COLORS.text_secondary};"
        )
        status_wrap_label.set_text(
            f"Wrapped: {'YES' if wrapped else 'No'}  |  "
            f"RAM Init: {'Done' if ram else 'Pending'}  |  "
            f"Compressed: {compress}"
        )

        # Timestamps (updated field names)
        ts_start = data.get("start_ts", 0)
        ts_trig = data.get("trigger_ts", 0)
        ts_last = data.get("last_ts", 0)
        ts_global = data.get("global_timer", 0)
        trig_row = data.get("trigger_row_addr", 0)
        err_status = data.get("port_err_status", 0)

        status_ts_label.set_text(
            f"Start: {ts_start}  |  Trigger: {ts_trig}  |  "
            f"Last: {ts_last}  |  Global: {ts_global}"
        )
        status_trigrow_label.set_text(
            f"Trigger Row: {trig_row}  |  Port Err Status: 0x{err_status:08X}"
        )

    def toggle_auto_poll(e):
        state["auto_poll"] = e.value
        if e.value:
            poll_timer["status"] = ui.timer(1.0, read_status)
        elif poll_timer["status"] is not None:
            poll_timer["status"].cancel()
            poll_timer["status"] = None

    # --- Capture Config tab ---

    async def apply_full_config():

        port = state["port_number"]
        direction = state["direction"]
        tp = int(cfg_trace_point.value or 0)
        lane = int(cfg_lane.value or 0)

        body = {
            "port_number": port,
            "direction": direction,
            "capture": {
                "direction": direction,
                "port_number": port,
                "lane": lane,
                "trace_point": tp,
                "filter_en": cfg_filter_en.value,
                "compress_en": cfg_compress_en.value,
                "nop_filt": cfg_nop_filt.value,
                "idle_filt": cfg_idle_filt.value,
                "data_cap": cfg_data_cap.value,
                "raw_filt": cfg_raw_filt.value,
                "trig_out_mask": cfg_trig_out_mask.value,
            },
            "trigger": {
                "trigger_src": int(trig_src.value if trig_src.value is not None else 0),
                "rearm_enable": trig_rearm.value,
                "rearm_time": int(trig_rearm_time.value or 0),
                "cond0_enable": int(trig_cond0_en.value or "0", 16),
                "cond0_invert": int(trig_cond0_inv.value or "0", 16),
                "cond1_enable": int(trig_cond1_en.value or "0", 16),
                "cond1_invert": int(trig_cond1_inv.value or "0", 16),
            },
            "post_trigger": {
                "clock_count": int(pt_clock.value or 0),
                "cap_count": int(pt_cap.value or 0),
                "clock_cnt_mult": int(pt_mult.value or 0),
                "count_type": int(pt_type.value or 0),
            },
        }

        url = _api_url("configure")
        body_json = json.dumps(body)
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("{url}", {{'
                f'method: "POST", headers: {{"Content-Type": "application/json"}},'
                f"body: '{body_json}'"
                f"}})).json()",
                timeout=10.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            ui.notify("PTrace configured", type="positive")
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    # --- Filter tab ---

    async def apply_filter(idx: int):

        port = state["port_number"]
        direction = state["direction"]
        match_hex = filt_match_inputs[idx].value or ("0" * 128)
        mask_hex = filt_mask_inputs[idx].value or ("0" * 128)

        body = {
            "filter_idx": idx,
            "match_hex": match_hex.ljust(128, "0")[:128],
            "mask_hex": mask_hex.ljust(128, "0")[:128],
        }
        url = _api_url("filter", port_number=port, direction=direction)
        body_json = json.dumps(body)
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("{url}", {{'
                f'method: "POST", headers: {{"Content-Type": "application/json"}},'
                f"body: '{body_json}'"
                f"}})).json()",
                timeout=10.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            ui.notify(f"Filter {idx} applied", type="positive")
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    # --- Error Triggers tab ---

    async def apply_error_triggers():

        port = state["port_number"]
        direction = state["direction"]
        mask = 0
        for bit, cb in err_checkboxes.items():
            if cb.value:
                mask |= 1 << bit

        body = {
            "port_number": port,
            "direction": direction,
            "error_mask": mask,
        }
        url = _api_url("error-trigger")
        body_json = json.dumps(body)
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("{url}", {{'
                f'method: "POST", headers: {{"Content-Type": "application/json"}},'
                f"body: '{body_json}'"
                f"}})).json()",
                timeout=10.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            ui.notify("Error triggers applied", type="positive")
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    # --- Event Counters tab ---

    async def apply_event_counter(ctr_id: int):

        port = state["port_number"]
        direction = state["direction"]
        src = int(evt_source_inputs[ctr_id].value or 0)
        thresh = int(evt_thresh_inputs[ctr_id].value or 0)

        body = {
            "port_number": port,
            "direction": direction,
            "counter_id": ctr_id,
            "event_source": src,
            "threshold": thresh,
        }
        url = _api_url("event-counter")
        body_json = json.dumps(body)
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("{url}", {{'
                f'method: "POST", headers: {{"Content-Type": "application/json"}},'
                f"body: '{body_json}'"
                f"}})).json()",
                timeout=10.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            ui.notify(f"Counter {ctr_id} configured", type="positive")
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    # --- Buffer tab ---

    async def read_buffer():
        port = state["port_number"]
        direction = state["direction"]
        max_rows = int(buf_max_rows.value or 256)
        url = _api_url(
            "buffer", port_number=port, direction=direction, max_rows=max_rows
        )
        try:
            resp = await ui.run_javascript(_js_get(url), timeout=30.0)
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            _render_buffer(resp)
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    buffer_data: dict = {"rows": [], "direction": "ingress", "port": 0}

    def _render_buffer(data: dict):
        rows = data.get("rows", [])
        buffer_data["rows"] = rows
        buffer_data["direction"] = data.get("direction", "ingress")
        buffer_data["port"] = data.get("port_number", 0)

        buf_summary.set_text(
            f"Rows: {len(rows)} | "
            f"Trigger Row: {data.get('trigger_row_addr', 0)} | "
            f"Triggered: {'Yes' if data.get('triggered') else 'No'} | "
            f"Wrapped: {'Yes' if data.get('tbuf_wrapped') else 'No'}"
        )

        buf_table_container.clear()
        with buf_table_container:
            if not rows:
                ui.label("No buffer data").style(f"color: {COLORS.text_muted};")
                return

            table_rows = []
            for r in rows:
                hex_str = r.get("hex_str", "")
                table_rows.append({
                    "idx": str(r.get("row_index", 0)),
                    "hex": hex_str[:80] + ("..." if len(hex_str) > 80 else ""),
                })

            columns = [
                {"name": "idx", "label": "Row", "field": "idx", "align": "left",
                 "style": "width: 60px"},
                {"name": "hex", "label": "Data (hex)", "field": "hex", "align": "left"},
            ]

            ui.table(
                columns=columns,
                rows=table_rows,
                row_key="idx",
                pagination={"rowsPerPage": 50},
            ).props("dense flat dark").classes("w-full").style(
                "font-family: 'JetBrains Mono', monospace; font-size: 12px;"
            )

    def export_csv():
        rows = buffer_data.get("rows", [])
        if not rows:
            ui.notify("No data to export", type="warning")
            return
        output = io.StringIO()
        writer = csv.writer(output)
        header = ["row_index"] + [f"dword_{i}" for i in range(19)]
        writer.writerow(header)
        for r in rows:
            dwords = r.get("dwords", [])
            writer.writerow([r.get("row_index", 0)] + [f"0x{d:08X}" for d in dwords])
        ui.download(
            output.getvalue().encode("utf-8"),
            f"ptrace_{buffer_data['direction']}_port{buffer_data['port']}.csv",
        )

    def export_hex():
        rows = buffer_data.get("rows", [])
        if not rows:
            ui.notify("No data to export", type="warning")
            return
        lines = []
        for r in rows:
            lines.append(f"Row {r.get('row_index', 0):4d}: {r.get('hex_str', '')}")
        ui.download(
            "\n".join(lines).encode("utf-8"),
            f"ptrace_{buffer_data['direction']}_port{buffer_data['port']}.txt",
        )

    # =====================================================================
    # Page Layout
    # =====================================================================

    # --- Top control bar ---
    with (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    ):
        ui.label("Protocol Trace Controls").classes("text-h6").style(
            f"color: {COLORS.text_primary};"
        )
        with ui.row().classes("items-end gap-4 mt-2"):
            port_input = (
                ui.number("Port Number", value=0, min=0, max=143, step=1)
                .props("dense outlined")
                .classes("w-28")
            )
            port_input.on_value_change(
                lambda e: state.update({"port_number": int(e.value or 0)})
            )

            dir_select = (
                ui.select(
                    {"ingress": "Ingress", "egress": "Egress"},
                    label="Direction",
                    value="ingress",
                )
                .props("dense outlined")
                .classes("w-32")
            )
            dir_select.on_value_change(lambda e: state.update({"direction": e.value}))

            ui.button("Start", on_click=start_capture).props(
                "flat color=positive dense"
            )
            ui.button("Stop", on_click=stop_capture).props(
                "flat color=warning dense"
            )
            ui.button("Clear", on_click=clear_triggered).props(
                "flat color=negative dense"
            )
            ui.button("Trigger", on_click=manual_trigger).props("flat dense")
            ui.button("Read Status", on_click=read_status).props("flat dense")

        with ui.row().classes("items-center gap-2 mt-2"):
            ui.switch("Auto-poll status (1s)").on_value_change(toggle_auto_poll).props(
                "dense"
            )

    # --- Status display ---
    with (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    ):
        ui.label("Status").classes("text-h6").style(f"color: {COLORS.text_primary};")
        with ui.row().classes("items-center gap-6 mt-2"):
            status_cap_label = ui.label("IDLE").style(
                f"color: {COLORS.text_muted}; font-weight: bold; font-size: 14px;"
            )
            status_trig_label = ui.label("Triggered: --").style(
                f"color: {COLORS.text_secondary}; font-size: 13px;"
            )
        status_wrap_label = ui.label(
            "Wrapped: --  |  RAM Init: --  |  Compressed: --"
        ).style(
            f"color: {COLORS.text_secondary}; font-size: 13px; margin-top: 4px;"
        )
        status_ts_label = ui.label(
            "Start: --  |  Trigger: --  |  Last: --  |  Global: --"
        ).style(
            f"color: {COLORS.text_muted}; font-size: 12px; "
            "font-family: monospace; margin-top: 4px;"
        )
        status_trigrow_label = ui.label(
            "Trigger Row: --  |  Port Err Status: --"
        ).style(
            f"color: {COLORS.text_muted}; font-size: 12px; "
            "font-family: monospace; margin-top: 2px;"
        )

    # --- Tabbed configuration ---
    with (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    ):
        with ui.tabs().classes("w-full").props("dense") as tabs:
            tab_capture = ui.tab("Capture Config")
            tab_trigger = ui.tab("Trigger")
            tab_filters = ui.tab("Filters")
            tab_errors = ui.tab("Error Triggers")
            tab_counters = ui.tab("Event Counters")
            tab_buffer = ui.tab("Buffer")
            tab_flit = ui.tab("Flit / Condition")

        with ui.tab_panels(tabs, value=tab_capture).classes("w-full"):
            # --- Capture Config tab ---
            with ui.tab_panel(tab_capture):
                with ui.row().classes("items-end gap-4 flex-wrap"):
                    cfg_trace_point = (
                        ui.select(
                            {0: "Accum/Distrib", 1: "Unscram/OSGen",
                             2: "Deskew/Scram", 3: "Scrambled"},
                            label="Trace Point",
                            value=0,
                        )
                        .props("dense outlined")
                        .classes("w-40")
                    )
                    cfg_lane = (
                        ui.number("Lane", value=0, min=0, max=15, step=1)
                        .props("dense outlined")
                        .classes("w-24")
                    )
                with ui.row().classes("items-center gap-4 mt-2 flex-wrap"):
                    cfg_filter_en = ui.switch("Filter").props("dense")
                    cfg_compress_en = ui.switch("Compress").props("dense")
                    cfg_nop_filt = ui.switch("NOP Filter").props("dense")
                    cfg_idle_filt = ui.switch("IDLE Filter").props("dense")
                    cfg_data_cap = ui.switch("Data Capture").props("dense")
                    cfg_raw_filt = ui.switch("Raw Filter").props("dense")
                    cfg_trig_out_mask = ui.switch("Trig Out Mask").props("dense")

                with ui.row().classes("mt-2"):
                    ui.label("Post-Trigger:").style(
                        f"color: {COLORS.text_secondary}; font-size: 13px;"
                    )
                with ui.row().classes("items-end gap-4 flex-wrap"):
                    pt_clock = (
                        ui.number("Clock Count", value=0, min=0, max=0xFFFF)
                        .props("dense outlined")
                        .classes("w-32")
                    )
                    pt_cap = (
                        ui.number("Cap Count", value=0, min=0, max=0x7FF)
                        .props("dense outlined")
                        .classes("w-32")
                    )
                    pt_mult = (
                        ui.number("Clock Mult", value=0, min=0, max=7)
                        .props("dense outlined")
                        .classes("w-28")
                    )
                    pt_type = (
                        ui.select(
                            {0: "Disabled", 1: "Clock", 2: "Capture", 3: "Both"},
                            label="Count Type",
                            value=0,
                        )
                        .props("dense outlined")
                        .classes("w-32")
                    )

                ui.separator().style(
                    f"background-color: {COLORS.border};"
                ).classes("my-2")

                with ui.row().classes("mt-1"):
                    ui.label("Trigger:").style(
                        f"color: {COLORS.text_secondary}; font-size: 13px;"
                    )
                with ui.row().classes("items-end gap-4 flex-wrap"):
                    trig_src = (
                        ui.select(
                            get_trigger_src_options(),
                            label="Trigger Source",
                            value=0,
                        )
                        .props("dense outlined")
                        .classes("w-52")
                    )
                    trig_rearm = ui.switch("Re-Arm").props("dense")
                    trig_rearm_time = (
                        ui.number("Re-Arm Time", value=0, min=0)
                        .props("dense outlined")
                        .classes("w-32")
                    )
                with ui.row().classes("items-end gap-4 mt-2 flex-wrap"):
                    trig_cond0_en = (
                        ui.input("Cond0 Enable (hex)", value="00000000")
                        .props("dense outlined")
                        .classes("w-36")
                    )
                    trig_cond0_inv = (
                        ui.input("Cond0 Invert (hex)", value="00000000")
                        .props("dense outlined")
                        .classes("w-36")
                    )
                    trig_cond1_en = (
                        ui.input("Cond1 Enable (hex)", value="00000000")
                        .props("dense outlined")
                        .classes("w-36")
                    )
                    trig_cond1_inv = (
                        ui.input("Cond1 Invert (hex)", value="00000000")
                        .props("dense outlined")
                        .classes("w-36")
                    )

                ui.button("Apply Full Config", on_click=apply_full_config).props(
                    "flat color=primary"
                ).classes("mt-3")

            # --- Trigger tab (reference info) ---
            with ui.tab_panel(tab_trigger):
                ui.label(
                    "Trigger settings are integrated into the Capture Config tab's "
                    "'Apply Full Config' action. Use Trigger Source, Re-Arm, and "
                    "Condition Enable/Invert fields above."
                ).style(f"color: {COLORS.text_secondary}; font-size: 13px;")
                ui.label(
                    "Condition bits: [8]=LinkSpeed, [9]=DLLPType, [10]=OSType, "
                    "[11-20]=Symbol0-9, [21]=LTSSM, [22]=LinkWidth"
                ).style(
                    f"color: {COLORS.text_muted}; font-size: 12px; "
                    "font-family: monospace; margin-top: 8px;"
                )
                ui.label(
                    "For Flit mode trigger/condition settings, use the "
                    "'Flit / Condition' tab."
                ).style(
                    f"color: {COLORS.text_muted}; font-size: 12px; margin-top: 4px;"
                )

            # --- Filters tab ---
            with ui.tab_panel(tab_filters):
                filt_match_inputs: dict[int, object] = {}
                filt_mask_inputs: dict[int, object] = {}

                for filt_idx in range(2):
                    ui.label(f"Filter {filt_idx}").style(
                        f"color: {COLORS.text_primary}; font-weight: bold;"
                    ).classes("mt-2" if filt_idx else "")
                    with ui.row().classes("items-end gap-4 flex-wrap"):
                        filt_match_inputs[filt_idx] = (
                            ui.input(
                                "Match (128 hex chars)",
                                value="0" * 128,
                            )
                            .props("dense outlined")
                            .classes("w-full")
                            .style("font-family: monospace; font-size: 11px;")
                        )
                    with ui.row().classes("items-end gap-4 flex-wrap"):
                        filt_mask_inputs[filt_idx] = (
                            ui.input(
                                "Mask (128 hex chars)",
                                value="0" * 128,
                            )
                            .props("dense outlined")
                            .classes("w-full")
                            .style("font-family: monospace; font-size: 11px;")
                        )
                    _idx = filt_idx
                    ui.button(
                        f"Apply Filter {filt_idx}",
                        on_click=lambda _, i=_idx: apply_filter(i),
                    ).props("flat color=primary dense").classes("mt-1")

            # --- Error Triggers tab ---
            with ui.tab_panel(tab_errors):
                ui.label("Enable error conditions as trigger sources:").style(
                    f"color: {COLORS.text_secondary}; font-size: 13px;"
                )
                err_checkboxes: dict[int, object] = {}
                with ui.row().classes("flex-wrap gap-x-6 gap-y-1 mt-2"):
                    for bit in range(28):
                        name = PORT_ERR_NAMES.get(bit, f"Bit {bit}")
                        cb = ui.checkbox(name).props("dense").style("font-size: 12px;")
                        err_checkboxes[bit] = cb

                ui.button(
                    "Apply Error Triggers", on_click=apply_error_triggers
                ).props("flat color=primary").classes("mt-3")

            # --- Event Counters tab ---
            with ui.tab_panel(tab_counters):
                evt_source_inputs: dict[int, object] = {}
                evt_thresh_inputs: dict[int, object] = {}

                for ctr_id in range(2):
                    ui.label(f"Counter {ctr_id}").style(
                        f"color: {COLORS.text_primary}; font-weight: bold;"
                    ).classes("mt-2" if ctr_id else "")
                    with ui.row().classes("items-end gap-4"):
                        evt_source_inputs[ctr_id] = (
                            ui.number(
                                "Event Source (0-63)",
                                value=0,
                                min=0,
                                max=63,
                            )
                            .props("dense outlined")
                            .classes("w-40")
                        )
                        evt_thresh_inputs[ctr_id] = (
                            ui.number(
                                "Threshold (0-65535)",
                                value=0,
                                min=0,
                                max=0xFFFF,
                            )
                            .props("dense outlined")
                            .classes("w-40")
                        )
                        _cid = ctr_id
                        ui.button(
                            "Apply",
                            on_click=lambda _, c=_cid: apply_event_counter(c),
                        ).props("flat color=primary dense")

            # --- Buffer tab ---
            with ui.tab_panel(tab_buffer):
                with ui.row().classes("items-end gap-4"):
                    buf_max_rows = (
                        ui.number("Max Rows", value=256, min=1, max=4096)
                        .props("dense outlined")
                        .classes("w-32")
                    )
                    ui.button("Read Buffer", on_click=read_buffer).props(
                        "flat color=primary"
                    )
                    ui.button("Export CSV", on_click=export_csv).props("flat dense")
                    ui.button("Export Hex", on_click=export_hex).props("flat dense")

                buf_summary = ui.label(
                    "Rows: -- | Trigger Row: -- | Triggered: --"
                ).style(
                    f"color: {COLORS.text_secondary}; font-size: 13px; margin-top: 8px;"
                )
                buf_table_container = ui.column().classes("w-full mt-2")

            # --- Flit / Condition tab ---
            with ui.tab_panel(tab_flit):
                build_flit_tab(device_id, state, _api_url)
