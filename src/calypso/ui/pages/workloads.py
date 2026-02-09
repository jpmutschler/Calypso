"""Workload generation page with configuration, live progress, and results."""

from __future__ import annotations

import json
import time

from nicegui import ui

from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS

_MAX_CHART_POINTS = 120


def workloads_page(device_id: str) -> None:
    """Render the NVMe workload generation page."""

    def content():
        _workloads_content(device_id)

    page_layout("NVMe Workloads", content, device_id=device_id)


def _workloads_content(device_id: str) -> None:
    """Build the workloads page content inside page_layout."""

    # Local state
    state: dict = {
        "workload_id": None,
        "running": False,
        "result": None,
        "backends": [],
    }
    form: dict = {
        "backend": "spdk",
        "bdf": "",
        "workload_type": "randread",
        "io_size": 4096,
        "queue_depth": 128,
        "duration": 30,
        "read_pct": 100,
        "workers": 1,
        "core_mask": "",
    }
    smart_chart_series: dict[str, list] = {}

    # --- Actions ---

    async def load_backends():
        try:
            resp = await ui.run_javascript(
                'return await (await fetch("/api/workloads/backends")).json()'
            )
            state["backends"] = resp.get("available", [])
            refresh_backend_status()
        except Exception as e:
            ui.notify(f"Failed to load backends: {e}", type="negative")

    async def start_workload():
        config = {
            "backend": form["backend"],
            "target_bdf": form["bdf"],
            "workload_type": form["workload_type"],
            "io_size_bytes": form["io_size"],
            "queue_depth": form["queue_depth"],
            "duration_seconds": form["duration"],
            "read_percentage": form["read_pct"],
            "num_workers": form["workers"],
        }
        if form["core_mask"]:
            config["core_mask"] = form["core_mask"]

        body = json.dumps(config)
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/workloads/start", '
                f'{{method:"POST", headers:{{"Content-Type":"application/json"}}, '
                f"body: {json.dumps(body)}}})).json()"
            )
            if "detail" in resp:
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            state["workload_id"] = resp.get("workload_id")
            state["running"] = True
            state["result"] = None
            smart_chart_series.clear()
            ui.notify(f"Workload started: {state['workload_id']}", type="positive")
            refresh_progress()
            _start_ws_stream(state["workload_id"])
        except Exception as e:
            ui.notify(f"Failed to start workload: {e}", type="negative")

    async def stop_workload():
        wl_id = state.get("workload_id")
        if not wl_id:
            return
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/workloads/{wl_id}/stop", '
                f'{{method:"POST"}})).json()'
            )
            state["running"] = False
            state["result"] = resp
            ui.notify("Workload stopped", type="info")
            refresh_progress()
            refresh_results()
        except Exception as e:
            ui.notify(f"Error stopping workload: {e}", type="negative")

    async def _start_ws_stream(workload_id: str):
        ws_js = (
            f"(() => {{"
            f'  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";'
            f"  const ws = new WebSocket("
            f"    `${{proto}}//${{window.location.host}}/api/workloads/{workload_id}/stream`"
            f"  );"
            f"  window._calypso_wl_ws = ws;"
            f"  ws.onmessage = (e) => {{"
            f"    const data = JSON.parse(e.data);"
            f"    if (data.error) {{ console.error(data.error); return; }}"
            f'    emitEvent("wl_progress", data);'
            f"  }};"
            f'  ws.onclose = () => {{ emitEvent("wl_ws_closed", {{}}); }};'
            f'  ws.onerror = () => {{ emitEvent("wl_ws_closed", {{}}); }};'
            f'  return "connected";'
            f"}})()"
        )
        try:
            await ui.run_javascript(ws_js)
        except Exception:
            pass

    def on_wl_progress(e):
        data = e.args
        s = data.get("state", "")
        if s not in ("pending", "running"):
            state["running"] = False
            state["result"] = data
            refresh_results()
        refresh_progress_data(data)
        _update_smart_from_progress(data)

    def on_wl_closed(_e):
        state["running"] = False
        refresh_progress()

    def _update_smart_from_progress(data: dict):
        """Extract SMART data from a WS progress tick and update cards + chart."""
        prog = data.get("progress") or {}
        smart = prog.get("smart")
        if smart is None:
            return
        refresh_smart_cards(smart)
        _append_smart_chart_point(smart)

    def _append_smart_chart_point(smart: dict):
        ts = smart.get("timestamp_ms", int(time.time() * 1000))

        composite = smart.get("composite_temp_celsius", 0)
        key = "Composite"
        smart_chart_series.setdefault(key, []).append([ts, round(composite, 1)])
        if len(smart_chart_series[key]) > _MAX_CHART_POINTS:
            smart_chart_series[key] = smart_chart_series[key][-_MAX_CHART_POINTS:]

        for i, temp in enumerate(smart.get("temp_sensors_celsius", [])):
            skey = f"Sensor {i + 1}"
            smart_chart_series.setdefault(skey, []).append([ts, round(temp, 1)])
            if len(smart_chart_series[skey]) > _MAX_CHART_POINTS:
                smart_chart_series[skey] = smart_chart_series[skey][-_MAX_CHART_POINTS:]

        temp_chart.options["series"] = [
            {"name": name, "data": points} for name, points in smart_chart_series.items()
        ]
        temp_chart.update()

    # --- Page content ---

    # Register WS event handlers
    ui.on("wl_progress", on_wl_progress)
    ui.on("wl_ws_closed", on_wl_closed)

    # --- Backend Status ---
    with (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    ):
        ui.label("Backend Status").classes("text-h6 mb-2").style(f"color: {COLORS.text_primary}")
        backend_container = ui.row().classes("items-center gap-4")

        @ui.refreshable
        def refresh_backend_status():
            backend_container.clear()
            with backend_container:
                avail = state.get("backends", [])
                for name in ["spdk", "pynvme"]:
                    ok = name in avail
                    color = COLORS.green if ok else COLORS.red
                    icon_name = "check_circle" if ok else "cancel"
                    with ui.row().classes("items-center gap-1"):
                        ui.icon(icon_name).style(f"color: {color}")
                        ui.label(name.upper()).style(f"color: {COLORS.text_primary}")
                if not avail:
                    ui.label("No backends available").style(f"color: {COLORS.text_muted}")

        refresh_backend_status()

    # --- Configuration ---
    with (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    ):
        ui.label("Configuration").classes("text-h6 mb-2").style(f"color: {COLORS.text_primary}")
        with ui.row().classes("w-full gap-4 flex-wrap"):
            ui.select(
                options=["spdk", "pynvme"],
                label="Backend",
                value=form["backend"],
                on_change=lambda e: form.update({"backend": e.value}),
            ).classes("w-32")
            ui.input(
                label="Target BDF",
                value=form["bdf"],
                placeholder="0000:01:00.0",
                on_change=lambda e: form.update({"bdf": e.value}),
            ).classes("w-48")
            ui.select(
                options=["randread", "randwrite", "read", "write", "randrw", "rw"],
                label="Workload Type",
                value=form["workload_type"],
                on_change=lambda e: form.update({"workload_type": e.value}),
            ).classes("w-36")
            ui.number(
                label="IO Size (bytes)",
                value=form["io_size"],
                min=512,
                step=512,
                on_change=lambda e: form.update({"io_size": int(e.value)}),
            ).classes("w-36")
            ui.number(
                label="Queue Depth",
                value=form["queue_depth"],
                min=1,
                on_change=lambda e: form.update({"queue_depth": int(e.value)}),
            ).classes("w-28")
            ui.number(
                label="Duration (s)",
                value=form["duration"],
                min=1,
                on_change=lambda e: form.update({"duration": int(e.value)}),
            ).classes("w-28")
            ui.number(
                label="Read %",
                value=form["read_pct"],
                min=0,
                max=100,
                on_change=lambda e: form.update({"read_pct": int(e.value)}),
            ).classes("w-24")
            ui.number(
                label="Workers",
                value=form["workers"],
                min=1,
                on_change=lambda e: form.update({"workers": int(e.value)}),
            ).classes("w-24")
            ui.input(
                label="Core Mask",
                value=form["core_mask"],
                placeholder="0xFF",
                on_change=lambda e: form.update({"core_mask": e.value}),
            ).classes("w-28")

        with ui.row().classes("gap-2 mt-2"):
            ui.button("Start Workload", on_click=start_workload).props("flat color=positive")
            ui.button("Stop Workload", on_click=stop_workload).props("flat color=negative")

    # --- Progress ---
    with (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    ):
        ui.label("Progress").classes("text-h6 mb-2").style(f"color: {COLORS.text_primary}")
        progress_container = ui.column().classes("w-full")

        @ui.refreshable
        def refresh_progress():
            progress_container.clear()
            with progress_container:
                if not state.get("workload_id"):
                    ui.label("No workload running.").style(f"color: {COLORS.text_muted}")
                    return
                if state.get("running"):
                    ui.spinner("dots", size="lg").style(f"color: {COLORS.blue}")
                    ui.label(f"Workload {state['workload_id']} is running...").style(
                        f"color: {COLORS.blue}"
                    )
                else:
                    ui.label(f"Workload {state['workload_id']} finished.").style(
                        f"color: {COLORS.text_secondary}"
                    )

        progress_bar = ui.linear_progress(value=0, show_value=False).classes("w-full")
        progress_label = ui.label("").style(f"color: {COLORS.text_secondary}")

        def refresh_progress_data(data: dict):
            prog = data.get("progress")
            if prog is not None:
                elapsed = prog.get("elapsed_seconds", 0)
                total = prog.get("total_seconds", 1)
                pct = elapsed / total if total > 0 else 0
                progress_bar.set_value(pct)
                iops = prog.get("current_iops", 0)
                bw = prog.get("current_bandwidth_mbps", 0)
                progress_label.set_text(
                    f"{elapsed:.0f}/{total:.0f}s  IOPS: {iops:,.0f}  BW: {bw:,.1f} MB/s"
                )

        refresh_progress()

    # --- SMART Health ---
    with (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    ):
        ui.label("DUT SMART Health").classes("text-h6 mb-2").style(f"color: {COLORS.text_primary}")
        smart_cards_container = ui.row().classes("w-full gap-4")

        @ui.refreshable
        def refresh_smart_cards(smart: dict | None = None):
            smart_cards_container.clear()
            with smart_cards_container:
                if smart is None:
                    ui.label("No SMART data (pynvme backend only)").style(
                        f"color: {COLORS.text_muted}"
                    )
                    return

                temp = smart.get("composite_temp_celsius", 0)
                ps = smart.get("power_state", 0)
                poh = smart.get("power_on_hours", 0)
                spare = smart.get("available_spare_pct", 100)

                _smart_stat(
                    "Temperature",
                    f"{temp:.0f} C",
                    _temp_color(temp),
                    "thermostat",
                )
                _smart_stat(
                    "Power State",
                    f"PS{ps}",
                    COLORS.blue,
                    "power_settings_new",
                )
                _smart_stat(
                    "Power-On Hours",
                    f"{poh:,}",
                    COLORS.text_primary,
                    "schedule",
                )
                spare_color = COLORS.green if spare > 10 else COLORS.red
                _smart_stat(
                    "Available Spare",
                    f"{spare}%",
                    spare_color,
                    "battery_std",
                )

        refresh_smart_cards()

    # --- Temperature Chart ---
    with (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    ):
        ui.label("DUT Temperature").classes("text-h6 mb-2").style(f"color: {COLORS.text_primary}")
        temp_chart = (
            ui.chart(
                {
                    "title": False,
                    "chart": {
                        "type": "line",
                        "backgroundColor": COLORS.bg_secondary,
                        "animation": False,
                    },
                    "xAxis": {
                        "type": "datetime",
                        "labels": {"style": {"color": COLORS.text_secondary}},
                    },
                    "yAxis": {
                        "title": {
                            "text": "Temperature (C)",
                            "style": {"color": COLORS.text_secondary},
                        },
                        "labels": {"style": {"color": COLORS.text_secondary}},
                        "gridLineColor": COLORS.border,
                        "min": 0,
                        "plotBands": [
                            {
                                "from": 0,
                                "to": 60,
                                "color": "rgba(63,185,80,0.08)",
                                "label": {
                                    "text": "Normal",
                                    "style": {"color": COLORS.green, "fontSize": "10px"},
                                },
                            },
                            {
                                "from": 60,
                                "to": 80,
                                "color": "rgba(210,153,34,0.08)",
                                "label": {
                                    "text": "Warm",
                                    "style": {"color": COLORS.yellow, "fontSize": "10px"},
                                },
                            },
                            {
                                "from": 80,
                                "to": 120,
                                "color": "rgba(248,81,73,0.08)",
                                "label": {
                                    "text": "Critical",
                                    "style": {"color": COLORS.red, "fontSize": "10px"},
                                },
                            },
                        ],
                    },
                    "legend": {
                        "itemStyle": {"color": COLORS.text_secondary},
                    },
                    "plotOptions": {
                        "line": {"marker": {"enabled": False}},
                    },
                    "series": [],
                }
            )
            .classes("w-full")
            .style("height: 300px")
        )

    # --- Results ---
    with (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    ):
        ui.label("Results").classes("text-h6 mb-2").style(f"color: {COLORS.text_primary}")
        results_container = ui.column().classes("w-full")

        @ui.refreshable
        def refresh_results():
            results_container.clear()
            with results_container:
                r = state.get("result")
                if r is None:
                    ui.label("No results yet.").style(f"color: {COLORS.text_muted}")
                    return

                result_data = r.get("result") or {}
                s = result_data.get("stats")
                if s is None:
                    err = result_data.get("error")
                    if err:
                        ui.label(f"Error: {err}").style(f"color: {COLORS.red}")
                    else:
                        ui.label("No stats available.").style(f"color: {COLORS.text_muted}")
                    return

                rows = [
                    {"metric": "IOPS Total", "value": f"{s.get('iops_total', 0):,.0f}"},
                    {"metric": "IOPS Read", "value": f"{s.get('iops_read', 0):,.0f}"},
                    {"metric": "IOPS Write", "value": f"{s.get('iops_write', 0):,.0f}"},
                    {
                        "metric": "BW Total (MB/s)",
                        "value": f"{s.get('bandwidth_total_mbps', 0):,.1f}",
                    },
                    {
                        "metric": "BW Read (MB/s)",
                        "value": f"{s.get('bandwidth_read_mbps', 0):,.1f}",
                    },
                    {
                        "metric": "BW Write (MB/s)",
                        "value": f"{s.get('bandwidth_write_mbps', 0):,.1f}",
                    },
                    {"metric": "Latency Avg (us)", "value": f"{s.get('latency_avg_us', 0):.1f}"},
                    {"metric": "Latency Max (us)", "value": f"{s.get('latency_max_us', 0):.1f}"},
                    {"metric": "Latency p50 (us)", "value": f"{s.get('latency_p50_us', 0):.1f}"},
                    {"metric": "Latency p99 (us)", "value": f"{s.get('latency_p99_us', 0):.1f}"},
                    {"metric": "Latency p999 (us)", "value": f"{s.get('latency_p999_us', 0):.1f}"},
                    {"metric": "CPU Usage (%)", "value": f"{s.get('cpu_usage_percent', 0):.1f}"},
                ]
                columns = [
                    {"name": "metric", "label": "Metric", "field": "metric", "align": "left"},
                    {"name": "value", "label": "Value", "field": "value", "align": "right"},
                ]
                ui.table(columns=columns, rows=rows, row_key="metric").classes("w-full")

                # SMART summary after I/O stats
                sh = result_data.get("smart_history")
                if sh and sh.get("snapshots"):
                    ui.label("SMART Summary").classes("text-subtitle1 mt-4").style(
                        f"color: {COLORS.cyan}"
                    )
                    smart_rows = [
                        {
                            "metric": "Peak Temperature",
                            "value": f"{sh.get('peak_temp_celsius', 0):.1f} C",
                        },
                        {
                            "metric": "Avg Temperature",
                            "value": f"{sh.get('avg_temp_celsius', 0):.1f} C",
                        },
                    ]
                    latest = sh.get("latest") or {}
                    if latest:
                        smart_rows.extend(
                            [
                                {
                                    "metric": "Final Power State",
                                    "value": f"PS{latest.get('power_state', 0)}",
                                },
                                {
                                    "metric": "Power-On Hours",
                                    "value": f"{latest.get('power_on_hours', 0):,}",
                                },
                                {
                                    "metric": "Available Spare",
                                    "value": f"{latest.get('available_spare_pct', 100)}%",
                                },
                            ]
                        )
                    smart_rows.append(
                        {"metric": "Samples Collected", "value": str(len(sh.get("snapshots", [])))}
                    )
                    smart_cols = [
                        {"name": "metric", "label": "Metric", "field": "metric", "align": "left"},
                        {"name": "value", "label": "Value", "field": "value", "align": "right"},
                    ]
                    ui.table(
                        columns=smart_cols,
                        rows=smart_rows,
                        row_key="metric",
                    ).classes("w-full")

        refresh_results()

    # --- Combined View (host + switch) ---
    with (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    ):
        ui.label("Combined View (Host + Switch)").classes("text-h6 mb-2").style(
            f"color: {COLORS.text_primary}"
        )
        combined_container = ui.row().classes("w-full gap-4")

        async def load_combined():
            wl_id = state.get("workload_id")
            if not wl_id:
                ui.notify("No workload to show combined view for", type="warning")
                return
            try:
                resp = await ui.run_javascript(
                    f"return await (await fetch("
                    f'"/api/workloads/{wl_id}/combined/{device_id}"'
                    f")).json()"
                )
                _render_combined(resp)
            except Exception as e:
                ui.notify(f"Error: {e}", type="negative")

        def _render_combined(data: dict):
            combined_container.clear()
            with combined_container:
                # Left: Host workload
                with (
                    ui.card()
                    .classes("flex-1 p-3")
                    .style(f"background: {COLORS.bg_card}; border: 1px solid {COLORS.border}")
                ):
                    ui.label("Host Workload").classes("text-subtitle1").style(
                        f"color: {COLORS.blue}"
                    )
                    ws = data.get("workload_stats")
                    if ws:
                        ui.label(f"IOPS: {ws.get('iops_total', 0):,.0f}").style(
                            f"color: {COLORS.text_primary}"
                        )
                        ui.label(f"BW: {ws.get('bandwidth_total_mbps', 0):,.1f} MB/s").style(
                            f"color: {COLORS.text_primary}"
                        )
                        ui.label(f"Lat avg: {ws.get('latency_avg_us', 0):.1f} us").style(
                            f"color: {COLORS.text_secondary}"
                        )
                    else:
                        ui.label("No stats").style(f"color: {COLORS.text_muted}")

                # Right: Switch perf
                with (
                    ui.card()
                    .classes("flex-1 p-3")
                    .style(f"background: {COLORS.bg_card}; border: 1px solid {COLORS.border}")
                ):
                    ui.label("Switch Performance").classes("text-subtitle1").style(
                        f"color: {COLORS.green}"
                    )
                    snap = data.get("switch_snapshot")
                    if snap:
                        port_stats = snap.get("port_stats", [])
                        total_in = sum(
                            ps.get("ingress_payload_byte_rate", 0) for ps in port_stats
                        ) / (1024 * 1024)
                        total_out = sum(
                            ps.get("egress_payload_byte_rate", 0) for ps in port_stats
                        ) / (1024 * 1024)
                        ui.label(f"Ingress: {total_in:.1f} MB/s").style(
                            f"color: {COLORS.text_primary}"
                        )
                        ui.label(f"Egress: {total_out:.1f} MB/s").style(
                            f"color: {COLORS.text_primary}"
                        )
                        ui.label(f"Ports: {len(port_stats)}").style(
                            f"color: {COLORS.text_secondary}"
                        )
                    else:
                        ui.label("No switch perf data (start perf monitor first)").style(
                            f"color: {COLORS.text_muted}"
                        )

        ui.button("Refresh Combined View", on_click=load_combined).props("flat color=primary")

    # --- History ---
    with (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    ):
        ui.label("Workload History").classes("text-h6 mb-2").style(f"color: {COLORS.text_primary}")
        history_container = ui.column().classes("w-full")

        async def load_history():
            try:
                resp = await ui.run_javascript(
                    'return await (await fetch("/api/workloads")).json()'
                )
                _render_history(resp)
            except Exception as e:
                ui.notify(f"Error: {e}", type="negative")

        def _render_history(data):
            history_container.clear()
            with history_container:
                if not data:
                    ui.label("No workload history.").style(f"color: {COLORS.text_muted}")
                    return
                rows = []
                for wl in data:
                    r = wl.get("result") or {}
                    s = r.get("stats") or {}
                    rows.append(
                        {
                            "id": wl.get("workload_id", ""),
                            "backend": wl.get("backend", ""),
                            "bdf": wl.get("target_bdf", ""),
                            "state": wl.get("state", ""),
                            "iops": f"{s.get('iops_total', 0):,.0f}" if s else "-",
                            "bw": f"{s.get('bandwidth_total_mbps', 0):,.1f}" if s else "-",
                        }
                    )
                columns = [
                    {"name": "id", "label": "ID", "field": "id", "align": "left"},
                    {"name": "backend", "label": "Backend", "field": "backend", "align": "left"},
                    {"name": "bdf", "label": "BDF", "field": "bdf", "align": "left"},
                    {"name": "state", "label": "State", "field": "state", "align": "left"},
                    {"name": "iops", "label": "IOPS", "field": "iops", "align": "right"},
                    {"name": "bw", "label": "BW (MB/s)", "field": "bw", "align": "right"},
                ]
                ui.table(columns=columns, rows=rows, row_key="id").classes("w-full")

        ui.button("Refresh History", on_click=load_history).props("flat color=primary")

    # Auto-load backends on page open
    ui.timer(0.1, load_backends, once=True)


def _smart_stat(label: str, value: str, color: str, icon: str) -> None:
    """Render a SMART health stat card."""
    with (
        ui.card()
        .classes("flex-1 p-3")
        .style(f"background: {COLORS.bg_card}; border: 1px solid {COLORS.border}; min-width: 140px")
    ):
        with ui.row().classes("items-center gap-2"):
            ui.icon(icon).style(f"color: {color}; font-size: 20px")
            ui.label(value).classes("text-subtitle1").style(f"color: {color}; font-weight: bold")
        ui.label(label).style(f"color: {COLORS.text_muted}; font-size: 12px")


def _temp_color(temp_c: float) -> str:
    """Return color based on temperature threshold."""
    if temp_c >= 80:
        return COLORS.red
    if temp_c >= 60:
        return COLORS.yellow
    return COLORS.green
