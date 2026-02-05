"""Performance monitor page with live WebSocket streaming and charts."""

from __future__ import annotations

import time

from nicegui import ui

from calypso.ui.theme import COLORS, CSS

_MAX_CHART_POINTS = 60


def performance_page(device_id: str) -> None:
    """Render the performance monitor page with live streaming charts."""
    ui.add_head_html(f"<style>{CSS}</style>")

    snapshot_data: dict = {}
    stream_state: dict = {"active": False, "ws_id": None}
    chart_series: dict[str, list] = {}

    # --- Actions ---

    async def start_monitoring():
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/perf/start", '
                f'{{method:"POST"}})).json()'
            )
            ports = resp.get("ports", "0")
            ui.notify(f"Monitoring started ({ports} ports)", type="positive")
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def stop_monitoring():
        try:
            await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/perf/stop", '
                f'{{method:"POST"}})).json()'
            )
            ui.notify("Monitoring stopped", type="info")
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def take_snapshot():
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/perf/snapshot")).json()'
            )
            _process_snapshot(resp)
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def start_stream():
        if stream_state["active"]:
            return
        # Connect WebSocket via JavaScript and set up message handler
        ws_js = (
            f'(() => {{'
            f'  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";'
            f'  const ws = new WebSocket(`${{proto}}//${{window.location.host}}/api/devices/{device_id}/perf/stream`);'
            f'  window._calypso_perf_ws = ws;'
            f'  ws.onmessage = (e) => {{'
            f'    const data = JSON.parse(e.data);'
            f'    if (data.error) {{ console.error(data.error); return; }}'
            f'    emitEvent("perf_snapshot", data);'
            f'  }};'
            f'  ws.onclose = () => {{ emitEvent("perf_ws_closed", {{}}); }};'
            f'  ws.onerror = () => {{ emitEvent("perf_ws_closed", {{}}); }};'
            f'  return "connected";'
            f'}})()'
        )
        try:
            await ui.run_javascript(ws_js)
            stream_state["active"] = True
            refresh_stream_status()
        except Exception as e:
            ui.notify(f"WebSocket error: {e}", type="negative")

    async def stop_stream():
        if not stream_state["active"]:
            return
        try:
            await ui.run_javascript(
                'if (window._calypso_perf_ws) { window._calypso_perf_ws.close(); '
                'window._calypso_perf_ws = null; }'
            )
        except Exception:
            pass
        stream_state["active"] = False
        refresh_stream_status()

    def on_ws_snapshot(e):
        _process_snapshot(e.args)

    def on_ws_closed(_e):
        stream_state["active"] = False
        refresh_stream_status()

    def _process_snapshot(data: dict):
        snapshot_data.clear()
        snapshot_data.update(data)
        ts = data.get("timestamp_ms", int(time.time() * 1000))
        port_stats = data.get("port_stats", [])

        # Prune series for ports no longer in the snapshot
        current_keys: set[str] = set()
        for ps in port_stats:
            port_num = ps.get("port_number", 0)
            current_keys.add(f"P{port_num} In")
            current_keys.add(f"P{port_num} Out")
        orphaned = [k for k in chart_series if k not in current_keys]
        for k in orphaned:
            del chart_series[k]

        # Update chart series data
        for ps in port_stats:
            port_num = ps.get("port_number", 0)
            in_key = f"P{port_num} In"
            out_key = f"P{port_num} Out"

            in_mbps = ps.get("ingress_payload_byte_rate", 0) / (1024 * 1024)
            out_mbps = ps.get("egress_payload_byte_rate", 0) / (1024 * 1024)

            chart_series.setdefault(in_key, []).append([ts, round(in_mbps, 2)])
            chart_series.setdefault(out_key, []).append([ts, round(out_mbps, 2)])

            # Rolling window
            if len(chart_series[in_key]) > _MAX_CHART_POINTS:
                chart_series[in_key] = chart_series[in_key][-_MAX_CHART_POINTS:]
            if len(chart_series[out_key]) > _MAX_CHART_POINTS:
                chart_series[out_key] = chart_series[out_key][-_MAX_CHART_POINTS:]

        # Push to charts
        bw_chart.options["series"] = [
            {"name": name, "data": points}
            for name, points in chart_series.items()
        ]
        bw_chart.update()

        # Update utilization chart
        if port_stats:
            util_categories = [f"P{ps.get('port_number', 0)}" for ps in port_stats]
            in_util = [round(ps.get("ingress_link_utilization", 0) * 100, 1) for ps in port_stats]
            out_util = [round(ps.get("egress_link_utilization", 0) * 100, 1) for ps in port_stats]

            util_chart.options["xAxis"]["categories"] = util_categories
            util_chart.options["series"] = [
                {"name": "Ingress", "data": in_util, "color": COLORS["accent_blue"]},
                {"name": "Egress", "data": out_util, "color": COLORS["accent_green"]},
            ]
            util_chart.update()

        refresh_summary()
        refresh_stats_table()

    def clear_chart():
        chart_series.clear()
        bw_chart.options["series"] = []
        bw_chart.update()
        util_chart.options["series"] = []
        util_chart.update()

    # --- Page layout ---

    with ui.column().classes("w-full p-4 gap-4"):
        ui.label("Performance Monitor").classes("text-h5").style(
            f"color: {COLORS['text_primary']}"
        )
        ui.label(f"Device: {device_id}").style(f"color: {COLORS['text_secondary']}")

        # Register WebSocket event handlers
        ui.on("perf_snapshot", on_ws_snapshot)
        ui.on("perf_ws_closed", on_ws_closed)

        # Controls card
        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS['bg_secondary']}; border: 1px solid {COLORS['border']}"
        ):
            with ui.row().classes("items-center gap-4"):
                ui.button("Start Monitor", on_click=start_monitoring).props(
                    "flat color=positive"
                )
                ui.button("Stop Monitor", on_click=stop_monitoring).props(
                    "flat color=negative"
                )
                ui.separator().props("vertical").classes("h-8")
                ui.button("Stream", on_click=start_stream).props(
                    "flat color=primary"
                ).tooltip("Connect WebSocket for live 1s updates")
                ui.button("Stop Stream", on_click=stop_stream).props("flat")
                ui.button("Snapshot", on_click=take_snapshot).props("flat color=primary")
                ui.separator().props("vertical").classes("h-8")
                ui.button("Clear Chart", on_click=clear_chart).props("flat")

            stream_status_container = ui.row().classes("items-center gap-2 mt-2")

            @ui.refreshable
            def refresh_stream_status():
                stream_status_container.clear()
                with stream_status_container:
                    if stream_state["active"]:
                        ui.icon("sensors").style(f"color: {COLORS['accent_green']}")
                        ui.label("WebSocket streaming").style(
                            f"color: {COLORS['accent_green']}; font-size: 13px"
                        )
                    else:
                        ui.icon("sensors_off").style(f"color: {COLORS['text_muted']}")
                        ui.label("Not streaming").style(
                            f"color: {COLORS['text_muted']}; font-size: 13px"
                        )

            refresh_stream_status()

        # Aggregate summary
        summary_container = ui.row().classes("w-full gap-4")

        @ui.refreshable
        def refresh_summary():
            summary_container.clear()
            with summary_container:
                port_stats = snapshot_data.get("port_stats", [])
                elapsed = snapshot_data.get("elapsed_ms", 0)
                if not port_stats:
                    return

                total_in = sum(
                    ps.get("ingress_payload_byte_rate", 0) for ps in port_stats
                ) / (1024 * 1024)
                total_out = sum(
                    ps.get("egress_payload_byte_rate", 0) for ps in port_stats
                ) / (1024 * 1024)
                avg_in_util = (
                    sum(ps.get("ingress_link_utilization", 0) for ps in port_stats)
                    / len(port_stats) * 100
                )
                avg_out_util = (
                    sum(ps.get("egress_link_utilization", 0) for ps in port_stats)
                    / len(port_stats) * 100
                )

                with ui.card().classes("flex-1 p-3").style(
                    f"background: {COLORS['bg_secondary']}; border: 1px solid {COLORS['border']}"
                ):
                    with ui.row().classes("justify-between items-center"):
                        _summary_stat(
                            "Total Ingress", f"{total_in:.1f} MB/s",
                            COLORS["accent_blue"],
                        )
                        _summary_stat(
                            "Total Egress", f"{total_out:.1f} MB/s",
                            COLORS["accent_green"],
                        )
                        _summary_stat(
                            "Avg In Util", f"{avg_in_util:.1f}%",
                            COLORS["accent_blue"],
                        )
                        _summary_stat(
                            "Avg Out Util", f"{avg_out_util:.1f}%",
                            COLORS["accent_green"],
                        )
                        _summary_stat(
                            "Ports", str(len(port_stats)),
                            COLORS["text_primary"],
                        )
                        _summary_stat(
                            "Interval", f"{elapsed} ms",
                            COLORS["text_muted"],
                        )

        refresh_summary()

        # Charts row
        with ui.row().classes("w-full gap-4"):
            # Bandwidth chart
            with ui.card().classes("flex-1 p-4").style(
                f"background: {COLORS['bg_secondary']}; border: 1px solid {COLORS['border']}"
            ):
                ui.label("Bandwidth (MB/s)").classes("text-h6").style(
                    f"color: {COLORS['text_primary']}"
                )
                bw_chart = ui.chart({
                    "title": False,
                    "chart": {
                        "type": "line",
                        "backgroundColor": COLORS["bg_secondary"],
                        "animation": False,
                    },
                    "xAxis": {
                        "type": "datetime",
                        "labels": {"style": {"color": COLORS["text_secondary"]}},
                    },
                    "yAxis": {
                        "title": {
                            "text": "MB/s",
                            "style": {"color": COLORS["text_secondary"]},
                        },
                        "labels": {"style": {"color": COLORS["text_secondary"]}},
                        "gridLineColor": COLORS["border"],
                        "min": 0,
                    },
                    "legend": {
                        "itemStyle": {"color": COLORS["text_secondary"]},
                    },
                    "plotOptions": {
                        "line": {"marker": {"enabled": False}},
                    },
                    "series": [],
                }).classes("w-full").style("height: 350px")

            # Utilization chart
            with ui.card().classes("flex-1 p-4").style(
                f"background: {COLORS['bg_secondary']}; border: 1px solid {COLORS['border']}"
            ):
                ui.label("Link Utilization (%)").classes("text-h6").style(
                    f"color: {COLORS['text_primary']}"
                )
                util_chart = ui.chart({
                    "title": False,
                    "chart": {
                        "type": "bar",
                        "backgroundColor": COLORS["bg_secondary"],
                        "animation": False,
                    },
                    "xAxis": {
                        "categories": [],
                        "labels": {"style": {"color": COLORS["text_secondary"]}},
                    },
                    "yAxis": {
                        "title": {
                            "text": "%",
                            "style": {"color": COLORS["text_secondary"]},
                        },
                        "labels": {"style": {"color": COLORS["text_secondary"]}},
                        "gridLineColor": COLORS["border"],
                        "min": 0,
                        "max": 100,
                    },
                    "legend": {
                        "itemStyle": {"color": COLORS["text_secondary"]},
                    },
                    "series": [],
                }).classes("w-full").style("height: 350px")

        # Port statistics table
        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS['bg_secondary']}; border: 1px solid {COLORS['border']}"
        ):
            ui.label("Port Statistics").classes("text-h6").style(
                f"color: {COLORS['text_primary']}"
            )
            stats_container = ui.column().classes("w-full")

            @ui.refreshable
            def refresh_stats_table():
                stats_container.clear()
                with stats_container:
                    port_stats = snapshot_data.get("port_stats", [])
                    if not port_stats:
                        ui.label("Start monitoring and take a snapshot.").style(
                            f"color: {COLORS['text_muted']}"
                        )
                        return
                    rows = []
                    for ps in port_stats:
                        in_bw = ps.get("ingress_payload_byte_rate", 0) / (1024 * 1024)
                        out_bw = ps.get("egress_payload_byte_rate", 0) / (1024 * 1024)
                        in_util = ps.get("ingress_link_utilization", 0) * 100
                        out_util = ps.get("egress_link_utilization", 0) * 100
                        in_total = ps.get("ingress_payload_total_bytes", 0)
                        out_total = ps.get("egress_payload_total_bytes", 0)
                        in_avg_tlp = ps.get("ingress_payload_avg_per_tlp", 0)
                        out_avg_tlp = ps.get("egress_payload_avg_per_tlp", 0)
                        rows.append({
                            "port": ps.get("port_number", 0),
                            "in_mbps": f"{in_bw:.1f}",
                            "in_util": f"{in_util:.1f}%",
                            "in_total": _format_bytes(in_total),
                            "in_avg_tlp": f"{in_avg_tlp:.0f}",
                            "out_mbps": f"{out_bw:.1f}",
                            "out_util": f"{out_util:.1f}%",
                            "out_total": _format_bytes(out_total),
                            "out_avg_tlp": f"{out_avg_tlp:.0f}",
                        })
                    columns = [
                        {"name": "port", "label": "Port", "field": "port", "align": "left"},
                        {"name": "in_mbps", "label": "In MB/s", "field": "in_mbps", "align": "right"},
                        {"name": "in_util", "label": "In Util", "field": "in_util", "align": "right"},
                        {"name": "in_total", "label": "In Total", "field": "in_total", "align": "right"},
                        {"name": "in_avg_tlp", "label": "In Avg/TLP", "field": "in_avg_tlp", "align": "right"},
                        {"name": "out_mbps", "label": "Out MB/s", "field": "out_mbps", "align": "right"},
                        {"name": "out_util", "label": "Out Util", "field": "out_util", "align": "right"},
                        {"name": "out_total", "label": "Out Total", "field": "out_total", "align": "right"},
                        {"name": "out_avg_tlp", "label": "Out Avg/TLP", "field": "out_avg_tlp", "align": "right"},
                    ]
                    ui.table(columns=columns, rows=rows, row_key="port").classes("w-full")

            refresh_stats_table()


def _summary_stat(label: str, value: str, color: str) -> None:
    """Render a summary statistic chip."""
    with ui.column().classes("items-center"):
        ui.label(value).classes("text-subtitle1").style(
            f"color: {color}; font-weight: bold"
        )
        ui.label(label).style(
            f"color: {COLORS['text_muted']}; font-size: 12px"
        )


def _format_bytes(n: int | float) -> str:
    """Format a byte count to a human-readable string."""
    n = float(n)
    if n < 1024:
        return f"{n:.0f} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.2f} GB"
