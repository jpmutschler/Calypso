"""LTSSM Trace page - LTSSM state polling, retrain visualization, and Ptrace capture."""

from __future__ import annotations

from nicegui import ui

from calypso.models.ltssm import LtssmTopState, ltssm_state_name, ltssm_top_state
from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS


def ltssm_trace_page(device_id: str) -> None:
    """Render the LTSSM Trace page."""

    def content():
        _ltssm_trace_content(device_id)

    page_layout("LTSSM Trace", content, device_id=device_id)


_TOP_STATE_COLORS: dict[int, str] = {
    LtssmTopState.DETECT: COLORS.red,
    LtssmTopState.POLLING: COLORS.orange,
    LtssmTopState.CONFIGURATION: COLORS.yellow,
    LtssmTopState.L0: COLORS.green,
    LtssmTopState.RECOVERY: COLORS.blue,
    LtssmTopState.LOOPBACK: COLORS.orange,
    LtssmTopState.HOT_RESET: COLORS.red,
    LtssmTopState.DISABLED: COLORS.red,
}


def _state_color(state_code: int) -> str:
    """Return a display color for a 12-bit LTSSM state code."""
    top = ltssm_top_state(state_code)
    return _TOP_STATE_COLORS.get(top, COLORS.text_secondary)


def _ltssm_trace_content(device_id: str) -> None:
    """Build the LTSSM trace page content."""

    state: dict = {
        "port_number": 0,
        "auto_refresh": False,
        "retrain_polling": False,
    }
    poll_timer: dict = {"snapshot": None, "retrain": None}

    # --- Snapshot actions ---

    async def read_snapshot():
        port = state["port_number"]
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}'
                f'/ltssm/snapshot?port_number={port}")).json()',
                timeout=10.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            _update_snapshot_display(resp)
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def clear_counters():
        port = state["port_number"]
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}'
                f'/ltssm/clear-counters", {{'
                f'method: "POST", headers: {{"Content-Type": "application/json"}},'
                f"body: JSON.stringify({{port_number: {port}}})"
                f"}})).json()",
                timeout=10.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            ui.notify("Counters cleared", type="positive")
            await read_snapshot()
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    def toggle_auto_refresh(e):
        state["auto_refresh"] = e.value
        if e.value:
            poll_timer["snapshot"] = ui.timer(1.0, read_snapshot)
        elif poll_timer["snapshot"] is not None:
            poll_timer["snapshot"].cancel()
            poll_timer["snapshot"] = None

    def _update_snapshot_display(data: dict):
        snapshot_card.set_visibility(True)
        snapshot_container.clear()
        with snapshot_container:
            ltssm_code = data.get("ltssm_state", 0)
            ltssm_name = data.get("ltssm_state_name", "UNKNOWN")
            speed_name = data.get("link_speed_name", "Unknown")
            port_sel = data.get("port_select", 0)
            port_num = data.get("port_number", 0)
            color = _state_color(ltssm_code)

            with ui.row().classes("w-full gap-8 items-start flex-wrap"):
                _snapshot_stat(
                    "LTSSM State",
                    ltssm_name,
                    f"0x{ltssm_code:03X}",
                    color,
                )
                _snapshot_stat(
                    "Link Speed",
                    speed_name,
                    "",
                    COLORS.cyan,
                )
                _snapshot_stat(
                    "Station Port",
                    f"Stn {port_num // 16} / Port {port_sel}",
                    f"port_select={port_sel}",
                    COLORS.text_secondary,
                )
                _snapshot_stat(
                    "Recovery Count",
                    str(data.get("recovery_count", 0)),
                    "",
                    COLORS.yellow,
                )
                _snapshot_stat(
                    "Link Down Count",
                    str(data.get("link_down_count", 0)),
                    "",
                    COLORS.orange,
                )
                _snapshot_stat(
                    "Lane Reversal",
                    "Yes" if data.get("lane_reversal") else "No",
                    "",
                    COLORS.text_secondary,
                )
                _snapshot_stat(
                    "Rx Eval Count",
                    str(data.get("rx_eval_count", 0)),
                    "",
                    COLORS.text_secondary,
                )

            # Diagnostic raw register dump
            reg_base = data.get("diag_reg_base", "")
            raw_pre = data.get("diag_raw_recovery_prewrite", "")
            raw_diag = data.get("diag_raw_recovery_diag", "")
            raw_phy = data.get("diag_raw_phy_status", "")
            raw_cmd = data.get("diag_raw_phy_cmd_status", "")
            if reg_base:
                with (
                    ui.expansion("Register Diagnostics")
                    .classes("w-full mt-2")
                    .props("dense header-class=text-caption")
                    .style(f"color: {COLORS.text_muted};")
                ):
                    ui.label(
                        f"Reg base: {reg_base}  |  "
                        f"PHY Cmd/Status (0x321C): {raw_cmd}  |  "
                        f"Recovery Diag pre-write: {raw_pre}  |  "
                        f"Recovery Diag post-write: {raw_diag}  |  "
                        f"PHY Additional Status: {raw_phy}"
                    ).style(
                        f"color: {COLORS.text_muted}; font-size: 12px; "
                        "font-family: monospace; word-break: break-all;"
                    )

    # --- Retrain-and-Watch actions ---

    async def start_retrain():
        port = state["port_number"]
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}'
                f'/ltssm/retrain", {{'
                f'method: "POST", headers: {{"Content-Type": "application/json"}},'
                f"body: JSON.stringify({{port_number: {port}, timeout_s: 10.0}})"
                f"}})).json()",
                timeout=10.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            ui.notify("Retrain started, watching LTSSM transitions...", type="positive")
            state["retrain_polling"] = True
            retrain_progress_card.set_visibility(True)
            _start_retrain_polling()
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    def _start_retrain_polling():
        if poll_timer["retrain"] is not None:
            return
        poll_timer["retrain"] = ui.timer(0.3, poll_retrain_progress)

    async def poll_retrain_progress():
        port = state["port_number"]
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}'
                f'/ltssm/retrain/progress?port_number={port}")).json()',
                timeout=10.0,
            )
        except Exception:
            return

        status = resp.get("status", "idle")
        elapsed = resp.get("elapsed_ms", 0)
        transitions = resp.get("transition_count", 0)

        retrain_progress_label.set_text(
            f"{status.upper()} - {elapsed:.0f}ms elapsed, {transitions} transitions"
        )

        if status == "complete":
            _stop_retrain_polling()
            state["retrain_polling"] = False
            ui.notify("Retrain complete!", type="positive")
            await fetch_retrain_result()
        elif status == "error":
            _stop_retrain_polling()
            state["retrain_polling"] = False
            error_msg = resp.get("error", "Unknown error")
            ui.notify(f"Retrain error: {error_msg}", type="negative")

    def _stop_retrain_polling():
        if poll_timer["retrain"] is not None:
            poll_timer["retrain"].cancel()
            poll_timer["retrain"] = None

    async def fetch_retrain_result():
        port = state["port_number"]
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}'
                f'/ltssm/retrain/result?port_number={port}")).json()',
                timeout=10.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            _render_retrain_chart(resp)
            _render_transition_table(resp)
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    def _render_retrain_chart(data: dict):
        transitions = data.get("transitions", [])
        if not transitions:
            return

        # Build category labels ordered by state code
        all_states = sorted({t["state"] for t in transitions})
        state_names = [_get_state_label(s) for s in all_states]

        # Build data points with per-point state coloring
        echart_data = []
        for t in transitions:
            echart_data.append(
                {
                    "value": [t["timestamp_ms"], _get_state_label(t["state"])],
                    "itemStyle": {"color": _state_color(t["state"])},
                }
            )

        retrain_chart.options["yAxis"]["data"] = state_names
        retrain_chart.options["series"] = [
            {
                "name": "LTSSM State",
                "type": "line",
                "step": "start",
                "data": echart_data,
                "lineStyle": {"color": COLORS.cyan, "width": 3},
                "symbolSize": 10,
            },
        ]
        retrain_chart.update()
        retrain_chart_card.set_visibility(True)

        # Summary row
        retrain_summary.clear()
        with retrain_summary:
            with ui.row().classes("w-full gap-8 items-start flex-wrap"):
                _snapshot_stat(
                    "Final State",
                    data.get("final_state_name", "?"),
                    f"0x{data.get('final_state', 0):03X}",
                    _state_color(data.get("final_state", 0)),
                )
                _snapshot_stat(
                    "Final Speed",
                    data.get("final_speed_name", "?"),
                    "",
                    COLORS.cyan,
                )
                _snapshot_stat(
                    "Transitions",
                    str(len(transitions)),
                    "",
                    COLORS.text_primary,
                )
                _snapshot_stat(
                    "Duration",
                    f"{data.get('duration_ms', 0):.0f} ms",
                    "",
                    COLORS.text_secondary,
                )
                settled = data.get("settled", False)
                _snapshot_stat(
                    "Settled (L0)",
                    "Yes" if settled else "No",
                    "",
                    COLORS.green if settled else COLORS.red,
                )

    def _render_transition_table(data: dict):
        transitions = data.get("transitions", [])
        if not transitions:
            return

        transition_table_card.set_visibility(True)
        transition_table_container.clear()
        with transition_table_container:
            rows = [
                {
                    "timestamp_ms": f"{t['timestamp_ms']:.2f}",
                    "state_code": f"0x{t['state']:03X}",
                    "state_name": t["state_name"],
                }
                for t in transitions
            ]
            columns = [
                {
                    "name": "timestamp_ms",
                    "label": "Timestamp (ms)",
                    "field": "timestamp_ms",
                    "align": "left",
                },
                {
                    "name": "state_code",
                    "label": "State Code",
                    "field": "state_code",
                    "align": "left",
                },
                {
                    "name": "state_name",
                    "label": "State Name",
                    "field": "state_name",
                    "align": "left",
                },
            ]
            ui.table(
                columns=columns,
                rows=rows,
                row_key="timestamp_ms",
            ).props("dense flat dark").classes("w-full")

    # --- Ptrace actions ---

    async def configure_ptrace():
        port = state["port_number"]
        tp = int(ptrace_trace_point.value or 0)
        lane = int(ptrace_lane.value or 0)
        trigger_ltssm = ptrace_trigger_toggle.value
        trigger_state = int(ptrace_trigger_state.value) if trigger_ltssm else None
        try:
            body = {
                "port_number": port,
                "trace_point": tp,
                "lane_select": lane,
                "trigger_on_ltssm": trigger_ltssm,
            }
            if trigger_state is not None:
                body["ltssm_trigger_state"] = trigger_state
            import json

            body_json = json.dumps(body)
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}'
                f'/ltssm/ptrace/configure", {{'
                f'method: "POST", headers: {{"Content-Type": "application/json"}},'
                f"body: '{body_json}'"
                f"}})).json()",
                timeout=10.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            ui.notify("Ptrace configured", type="positive")
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def start_ptrace_capture():
        port = state["port_number"]
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}'
                f'/ltssm/ptrace/start", {{'
                f'method: "POST", headers: {{"Content-Type": "application/json"}},'
                f"body: JSON.stringify({{port_number: {port}}})"
                f"}})).json()",
                timeout=10.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            ui.notify("Ptrace capture started", type="positive")
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def stop_ptrace_capture():
        port = state["port_number"]
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}'
                f'/ltssm/ptrace/stop", {{'
                f'method: "POST", headers: {{"Content-Type": "application/json"}},'
                f"body: JSON.stringify({{port_number: {port}}})"
                f"}})).json()",
                timeout=10.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            ui.notify("Ptrace capture stopped", type="positive")
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def read_ptrace_status():
        port = state["port_number"]
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}'
                f'/ltssm/ptrace/status?port_number={port}")).json()',
                timeout=10.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            active = resp.get("capture_active", False)
            triggered = resp.get("trigger_hit", False)
            entries = resp.get("entries_captured", 0)
            ptrace_status_label.set_text(
                f"Active: {'Yes' if active else 'No'} | "
                f"Trigger Hit: {'Yes' if triggered else 'No'} | "
                f"Entries: {entries}"
            )
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def read_ptrace_buffer():
        port = state["port_number"]
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}'
                f'/ltssm/ptrace/buffer?port_number={port}&max_entries=256")).json()',
                timeout=10.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            _render_ptrace_data(resp)
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    def _render_ptrace_data(data: dict):
        entries = data.get("entries", [])
        ptrace_data_card.set_visibility(True)
        ptrace_data_container.clear()
        with ptrace_data_container:
            if not entries:
                ui.label("No captured data").style(f"color: {COLORS.text_muted};")
                return
            rows = [{"index": str(e["index"]), "raw_data": e["raw_data"]} for e in entries]
            columns = [
                {"name": "index", "label": "Index", "field": "index", "align": "left"},
                {
                    "name": "raw_data",
                    "label": "Raw Data (hex)",
                    "field": "raw_data",
                    "align": "left",
                },
            ]
            with ui.row().classes("w-full items-center gap-4 mb-2"):
                ui.label(
                    f"Total captured: {data.get('total_captured', 0)} | "
                    f"Trigger hit: {'Yes' if data.get('trigger_hit') else 'No'}"
                ).style(f"color: {COLORS.text_secondary}; font-size: 13px;")
            ui.table(
                columns=columns,
                rows=rows,
                row_key="index",
            ).props("dense flat dark").classes("w-full")

    # =====================================================================
    # Page Layout
    # =====================================================================

    # --- Controls card ---
    with (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    ):
        ui.label("LTSSM Trace Controls").classes("text-h6").style(f"color: {COLORS.text_primary};")
        with ui.row().classes("items-end gap-4 mt-2"):
            port_input = (
                ui.number(
                    "Port Number",
                    value=0,
                    min=0,
                    max=143,
                    step=1,
                )
                .props("dense outlined")
                .classes("w-28")
            )
            port_input.on_value_change(lambda e: state.update({"port_number": int(e.value or 0)}))

            ui.button("Read Snapshot", on_click=read_snapshot).props("flat color=primary")
            ui.button("Retrain & Watch", on_click=start_retrain).props("flat color=warning")
            ui.button("Clear Counters", on_click=clear_counters).props("flat color=negative")

        with ui.row().classes("items-center gap-2 mt-2"):
            ui.switch("Auto-refresh (1s)").on_value_change(toggle_auto_refresh).props("dense")

    # --- Snapshot display card ---
    snapshot_card = (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    )
    snapshot_card.set_visibility(False)
    with snapshot_card:
        ui.label("Current State").classes("text-h6").style(f"color: {COLORS.text_primary};")
        snapshot_container = ui.row().classes("w-full mt-2")

    # --- Retrain progress card ---
    retrain_progress_card = (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    )
    retrain_progress_card.set_visibility(False)
    with retrain_progress_card:
        ui.label("Retrain-and-Watch Progress").classes("text-h6").style(
            f"color: {COLORS.text_primary};"
        )
        retrain_progress_label = ui.label("IDLE").style(
            f"color: {COLORS.text_secondary}; font-size: 13px;"
        )

    # --- Retrain chart card ---
    retrain_chart_card = (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    )
    retrain_chart_card.set_visibility(False)
    with retrain_chart_card:
        ui.label("LTSSM State Transitions").classes("text-h6").style(
            f"color: {COLORS.text_primary};"
        )
        retrain_chart = (
            ui.echart(
                {
                    "animation": False,
                    "backgroundColor": "transparent",
                    "grid": {"containLabel": True, "left": 120},
                    "tooltip": {"trigger": "axis"},
                    "legend": {"textStyle": {"color": COLORS.text_secondary}},
                    "xAxis": {
                        "type": "value",
                        "name": "Time (ms)",
                        "nameTextStyle": {"color": COLORS.text_secondary},
                        "axisLabel": {"color": COLORS.text_secondary},
                        "axisLine": {"lineStyle": {"color": COLORS.border}},
                        "splitLine": {"lineStyle": {"color": COLORS.border}},
                    },
                    "yAxis": {
                        "type": "category",
                        "name": "LTSSM State",
                        "nameTextStyle": {"color": COLORS.text_secondary},
                        "data": [],
                        "axisLabel": {"color": COLORS.text_secondary},
                        "axisLine": {"lineStyle": {"color": COLORS.border}},
                    },
                    "series": [],
                }
            )
            .classes("w-full")
            .style("height: 350px")
        )

        retrain_summary = ui.row().classes("w-full mt-2")

    # --- Transition log table ---
    transition_table_card = (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    )
    transition_table_card.set_visibility(False)
    with transition_table_card:
        ui.label("Transition Log").classes("text-h6").style(f"color: {COLORS.text_primary};")
        transition_table_container = ui.column().classes("w-full mt-2")

    # --- Ptrace Configuration card ---
    with (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    ):
        ui.label("Ptrace Capture").classes("text-h6").style(f"color: {COLORS.text_primary};")
        with ui.row().classes("items-end gap-4 mt-2"):
            ptrace_trace_point = (
                ui.number(
                    "Trace Point",
                    value=0,
                    min=0,
                    max=15,
                    step=1,
                )
                .props("dense outlined")
                .classes("w-28")
            )

            ptrace_lane = (
                ui.number(
                    "Lane Select",
                    value=0,
                    min=0,
                    max=15,
                    step=1,
                )
                .props("dense outlined")
                .classes("w-28")
            )

            ptrace_trigger_toggle = ui.switch("LTSSM Trigger").props("dense")

            # Build LTSSM top-state options for dropdown
            ltssm_options = {s.value: s.name for s in LtssmTopState}
            ptrace_trigger_state = (
                ui.select(
                    ltssm_options,
                    label="Trigger State",
                    value=LtssmTopState.L0,
                )
                .props("dense outlined")
                .classes("w-48")
            )

        with ui.row().classes("items-center gap-4 mt-2"):
            ui.button("Configure", on_click=configure_ptrace).props("flat color=primary")
            ui.button("Start", on_click=start_ptrace_capture).props("flat color=positive")
            ui.button("Stop", on_click=stop_ptrace_capture).props("flat color=warning")
            ui.button("Read Status", on_click=read_ptrace_status).props("flat")
            ui.button("Read Buffer", on_click=read_ptrace_buffer).props("flat color=info")

        ptrace_status_label = ui.label("Status: --").style(
            f"color: {COLORS.text_secondary}; font-size: 13px; margin-top: 8px;"
        )

    # --- Ptrace data card ---
    ptrace_data_card = (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    )
    ptrace_data_card.set_visibility(False)
    with ptrace_data_card:
        ui.label("Ptrace Captured Data").classes("text-h6").style(f"color: {COLORS.text_primary};")
        ptrace_data_container = ui.column().classes("w-full mt-2")


def _snapshot_stat(label: str, value: str, subtitle: str, color: str) -> None:
    """Render a snapshot statistic."""
    with ui.column().classes("items-center"):
        ui.label(value).classes("text-subtitle1 mono").style(f"color: {color}; font-weight: bold;")
        if subtitle:
            ui.label(subtitle).style(f"color: {COLORS.text_secondary}; font-size: 12px;")
        ui.label(label).style(f"color: {COLORS.text_muted}; font-size: 11px;")


def _get_state_label(code: int) -> str:
    """Get a short label for a 12-bit LTSSM state code."""
    return ltssm_state_name(code)
