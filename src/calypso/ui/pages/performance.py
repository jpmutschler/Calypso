"""Performance monitor page with live streaming and charts."""

from __future__ import annotations

import asyncio
import time

from nicegui import ui
from nicegui_highcharts import highchart

from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

_MAX_CHART_POINTS = 60


def performance_page(device_id: str) -> None:
    """Render the performance monitor page with live streaming charts."""

    def content():
        _performance_content(device_id)

    page_layout("Performance Monitor", content, device_id=device_id)


def _performance_content(device_id: str) -> None:
    """Build the performance page content inside page_layout."""
    from calypso.api.app import get_device_registry

    registry = get_device_registry()
    device = registry.get(device_id)

    if device is None:
        ui.label("Device not found. Please reconnect.").style(f"color: {COLORS.red}")
        return

    # --- State ---
    snapshot_data: dict = {}
    monitor_state: dict = {"monitor": None}
    stream_state: dict = {"active": False}
    chart_series: dict[str, list] = {}

    # --- Loading state ---
    loading_container = ui.column().classes("w-full items-center py-8")
    with loading_container:
        ui.spinner("dots", size="xl").style(f"color: {COLORS.cyan}")
        ui.label("Initializing performance monitoring...").style(
            f"color: {COLORS.text_secondary}"
        )

    # --- Main content (hidden until init completes) ---
    main_container = ui.column().classes("w-full gap-4")
    main_container.visible = False

    # --- Error container (hidden unless init fails) ---
    error_container = ui.column().classes("w-full")
    error_container.visible = False

    # Build the main content structure (hidden until loaded)
    with main_container:
        # Controls card
        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
        ):
            with ui.row().classes("items-center gap-4"):
                stream_btn = ui.button("Start Stream", icon="play_arrow").props(
                    "flat color=positive"
                )
                snapshot_btn = ui.button("Snapshot", icon="camera").props(
                    "flat color=primary"
                )
                ui.separator().props("vertical").classes("h-8")
                reset_btn = ui.button("Reset Counters", icon="restart_alt").props(
                    "flat"
                )
                clear_btn = ui.button("Clear Chart", icon="delete_sweep").props("flat")

            stream_status_container = ui.row().classes("items-center gap-2 mt-2")

        # Summary row
        summary_container = ui.row().classes("w-full gap-4")

        # Charts row
        with ui.row().classes("w-full gap-4"):
            # Bandwidth chart
            with ui.card().classes("flex-1 p-4").style(
                f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
            ):
                ui.label("Bandwidth (MB/s)").classes("text-h6").style(
                    f"color: {COLORS.text_primary}"
                )
                bw_chart = highchart({
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
                            "text": "MB/s",
                            "style": {"color": COLORS.text_secondary},
                        },
                        "labels": {"style": {"color": COLORS.text_secondary}},
                        "gridLineColor": COLORS.border,
                        "min": 0,
                    },
                    "legend": {
                        "itemStyle": {"color": COLORS.text_secondary},
                    },
                    "plotOptions": {
                        "line": {"marker": {"enabled": False}},
                    },
                    "series": [],
                }).classes("w-full").style("height: 350px")

            # Utilization chart
            with ui.card().classes("flex-1 p-4").style(
                f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
            ):
                ui.label("Link Utilization (%)").classes("text-h6").style(
                    f"color: {COLORS.text_primary}"
                )
                util_chart = highchart({
                    "title": False,
                    "chart": {
                        "type": "bar",
                        "backgroundColor": COLORS.bg_secondary,
                        "animation": False,
                    },
                    "xAxis": {
                        "categories": [],
                        "labels": {"style": {"color": COLORS.text_secondary}},
                    },
                    "yAxis": {
                        "title": {
                            "text": "%",
                            "style": {"color": COLORS.text_secondary},
                        },
                        "labels": {"style": {"color": COLORS.text_secondary}},
                        "gridLineColor": COLORS.border,
                        "min": 0,
                        "max": 100,
                    },
                    "legend": {
                        "itemStyle": {"color": COLORS.text_secondary},
                    },
                    "series": [],
                }).classes("w-full").style("height: 350px")

        # Port statistics table
        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
        ):
            ui.label("Port Statistics").classes("text-h6").style(
                f"color: {COLORS.text_primary}"
            )
            stats_container = ui.column().classes("w-full")

    # --- Actions ---

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
            in_util = [
                round(ps.get("ingress_link_utilization", 0) * 100, 1) for ps in port_stats
            ]
            out_util = [
                round(ps.get("egress_link_utilization", 0) * 100, 1) for ps in port_stats
            ]

            util_chart.options["xAxis"]["categories"] = util_categories
            util_chart.options["series"] = [
                {"name": "Ingress", "data": in_util, "color": COLORS.blue},
                {"name": "Egress", "data": out_util, "color": COLORS.green},
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

    async def toggle_stream():
        if stream_state["active"]:
            stream_state["active"] = False
            stream_btn.props("color=positive")
            stream_btn.text = "Start Stream"
            stream_btn.props(remove="icon=stop")
            stream_btn.props(add="icon=play_arrow")
            refresh_stream_status()
            ui.notify("Stream stopped", type="info")
        else:
            monitor = monitor_state["monitor"]
            if monitor is None:
                ui.notify("Monitoring not initialized", type="warning")
                return
            stream_state["active"] = True
            stream_btn.props("color=negative")
            stream_btn.text = "Stop Stream"
            stream_btn.props(remove="icon=play_arrow")
            stream_btn.props(add="icon=stop")
            refresh_stream_status()

            async def _stream_loop():
                while stream_state["active"]:
                    try:
                        snapshot = await asyncio.to_thread(monitor.read_snapshot)
                        _process_snapshot(snapshot.model_dump())
                        await asyncio.sleep(1.0)
                    except Exception as e:
                        ui.notify(f"Stream error: {e}", type="negative")
                        break

                stream_state["active"] = False
                stream_btn.props("color=positive")
                stream_btn.text = "Start Stream"
                stream_btn.props(remove="icon=stop")
                stream_btn.props(add="icon=play_arrow")
                refresh_stream_status()

            asyncio.create_task(_stream_loop())
            ui.notify("Streaming started", type="positive")

    async def take_snapshot():
        monitor = monitor_state["monitor"]
        if monitor is None:
            ui.notify("Monitoring not initialized", type="warning")
            return
        try:
            snapshot = await asyncio.to_thread(monitor.read_snapshot)
            _process_snapshot(snapshot.model_dump())
        except Exception as e:
            ui.notify(f"Snapshot error: {e}", type="negative")

    async def reset_counters():
        monitor = monitor_state["monitor"]
        if monitor is None:
            return
        try:
            await asyncio.to_thread(monitor.reset)
            ui.notify("Counters reset", type="info")
        except Exception as e:
            ui.notify(f"Reset error: {e}", type="negative")

    # Wire up button handlers
    stream_btn.on_click(toggle_stream)
    snapshot_btn.on_click(take_snapshot)
    reset_btn.on_click(reset_counters)
    clear_btn.on_click(clear_chart)

    # --- Refreshable sections ---

    @ui.refreshable
    def refresh_stream_status():
        stream_status_container.clear()
        with stream_status_container:
            if stream_state["active"]:
                ui.icon("sensors").style(f"color: {COLORS.green}")
                ui.label("Streaming (1s interval)").style(
                    f"color: {COLORS.green}; font-size: 13px"
                )
            else:
                ui.icon("sensors_off").style(f"color: {COLORS.text_muted}")
                ui.label("Not streaming").style(
                    f"color: {COLORS.text_muted}; font-size: 13px"
                )

    refresh_stream_status()

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
                f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
            ):
                with ui.row().classes("justify-between items-center"):
                    _summary_stat("Total Ingress", f"{total_in:.1f} MB/s", COLORS.blue)
                    _summary_stat("Total Egress", f"{total_out:.1f} MB/s", COLORS.green)
                    _summary_stat("Avg In Util", f"{avg_in_util:.1f}%", COLORS.blue)
                    _summary_stat("Avg Out Util", f"{avg_out_util:.1f}%", COLORS.green)
                    _summary_stat("Ports", str(len(port_stats)), COLORS.text_primary)
                    _summary_stat("Interval", f"{elapsed} ms", COLORS.text_muted)

    refresh_summary()

    @ui.refreshable
    def refresh_stats_table():
        stats_container.clear()
        with stats_container:
            port_stats = snapshot_data.get("port_stats", [])
            if not port_stats:
                ui.label("Waiting for data...").style(f"color: {COLORS.text_muted}")
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
                {
                    "name": "in_avg_tlp", "label": "In Avg/TLP",
                    "field": "in_avg_tlp", "align": "right",
                },
                {"name": "out_mbps", "label": "Out MB/s", "field": "out_mbps", "align": "right"},
                {
                    "name": "out_util", "label": "Out Util",
                    "field": "out_util", "align": "right",
                },
                {
                    "name": "out_total", "label": "Out Total",
                    "field": "out_total", "align": "right",
                },
                {
                    "name": "out_avg_tlp", "label": "Out Avg/TLP",
                    "field": "out_avg_tlp", "align": "right",
                },
            ]
            ui.table(columns=columns, rows=rows, row_key="port").classes("w-full")

    refresh_stats_table()

    # --- Async init + auto-start ---

    async def _init_and_start():
        """Initialize perf monitoring in background thread, then auto-start."""
        from calypso.core.perf_monitor import PerfMonitor

        try:
            def _setup():
                monitor = PerfMonitor(device._device_obj, device._device_key)
                num_ports = monitor.initialize()
                monitor.start()
                first_snapshot = monitor.read_snapshot()
                return monitor, num_ports, first_snapshot

            monitor, num_ports, first_snapshot = await asyncio.to_thread(_setup)

            monitor_state["monitor"] = monitor
            loading_container.visible = False
            main_container.visible = True

            _process_snapshot(first_snapshot.model_dump())
            ui.notify(f"Monitoring active ({num_ports} ports)", type="positive")

        except Exception as e:
            logger.warning("perf_init_failed", error=str(e))
            loading_container.visible = False
            error_container.visible = True
            error_container.clear()
            with error_container:
                with ui.card().classes("w-full p-6").style(
                    f"background: {COLORS.bg_secondary}; "
                    f"border: 1px solid {COLORS.yellow}"
                ):
                    with ui.row().classes("items-center gap-4"):
                        ui.icon("warning").style(
                            f"color: {COLORS.yellow}; font-size: 2rem;"
                        )
                        with ui.column().classes("gap-2"):
                            ui.label("Performance Monitoring Initialization Failed").style(
                                f"color: {COLORS.text_primary}; "
                                f"font-weight: 600; font-size: 1.1rem;"
                            )
                            ui.label(
                                "Could not initialize performance counters. "
                                "This may be a limitation of the current PCIe enumeration."
                            ).style(f"color: {COLORS.text_secondary};")

                            with ui.expansion("Error Details", icon="code").classes("w-full"):
                                ui.label(f"Error: {e}").style(
                                    f"color: {COLORS.text_muted}; "
                                    f"font-family: monospace; font-size: 0.85rem;"
                                )

                    ui.separator().classes("my-4")

                    ui.label("Alternative Options:").style(
                        f"color: {COLORS.text_primary}; font-weight: 600;"
                    )
                    with ui.column().classes("gap-2 ml-4"):
                        ui.label(
                            "Use the MCU interface for thermal and power monitoring"
                        ).style(f"color: {COLORS.text_secondary};")
                        ui.label(
                            "Check Port Status page for link statistics"
                        ).style(f"color: {COLORS.text_secondary};")
                        ui.label(
                            "Use PCIe Registers page to read raw counter values"
                        ).style(f"color: {COLORS.text_secondary};")

    ui.timer(0.1, _init_and_start, once=True)


def _summary_stat(label: str, value: str, color: str) -> None:
    """Render a summary statistic chip."""
    with ui.column().classes("items-center"):
        ui.label(value).classes("text-subtitle1").style(
            f"color: {color}; font-weight: bold"
        )
        ui.label(label).style(
            f"color: {COLORS.text_muted}; font-size: 12px"
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
