"""Eye Diagram page - PCIe Lane Margining sweep visualization.

Supports NRZ (single eye, Gen1-5) and PAM4 (3 stacked eyes, Gen6).
"""

from __future__ import annotations

from nicegui import ui

from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS

# Per-eye accent colors for PAM4 3-eye display
_PAM4_COLORS = {
    "upper": COLORS.cyan,
    "middle": "#448AFF",  # blue
    "lower": "#AA66FF",  # purple
}

# Map eye labels to PCIe receiver designations (Spec Section 7.7.8.4)
_EYE_TO_RECEIVER = {"upper": "A", "middle": "B", "lower": "C"}


def eye_diagram_page(device_id: str) -> None:
    """Render the Eye Diagram page."""

    def content():
        _eye_diagram_content(device_id)

    page_layout("Eye Diagram", content, device_id=device_id)


def _eye_diagram_content(device_id: str) -> None:
    """Build the eye diagram page content inside page_layout."""

    state: dict = {
        "port_number": 0,
        "lane": 0,
        "capabilities": None,
        "polling": False,
        "is_pam4": False,
        "modulation": "NRZ",
    }
    poll_timer: dict = {"ref": None}

    # --- Actions ---

    async def check_capabilities():
        port = state["port_number"]
        lane = state["lane"]
        try:
            resp = await ui.run_javascript(
                "return (async () => {"
                f'  const r = await fetch("/api/devices/{device_id}'
                f'/phy/margining/capabilities?port_number={port}&lane={lane}");'
                "  if (!r.ok) { const t = await r.text(); return {detail: t || r.statusText}; }"
                "  return await r.json();"
                "})()",
                timeout=15.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            state["capabilities"] = resp

            # Modulation is now included in the capabilities response
            # (read from the target port, not the management port)
            modulation = resp.get("modulation", "NRZ")
            is_pam4 = modulation == "PAM4"
            state["is_pam4"] = is_pam4
            state["modulation"] = modulation

            refresh_capabilities()
            mod_label = "PAM4 (3 Eyes)" if is_pam4 else "NRZ (Single Eye)"
            ui.notify(f"Capabilities loaded - {mod_label}", type="positive")
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def start_sweep():
        port = state["port_number"]
        lane = state["lane"]

        if state["is_pam4"]:
            await _start_pam4_sweep(lane, port)
        else:
            await _start_nrz_sweep(lane, port)

    async def _start_nrz_sweep(lane: int, port: int):
        try:
            resp = await ui.run_javascript(
                "return (async () => {"
                f'  const r = await fetch("/api/devices/{device_id}'
                f'/phy/margining/sweep", {{'
                f'    method: "POST", headers: {{"Content-Type": "application/json"}},'
                f"    body: JSON.stringify({{port_number: {port}, lane: {lane}, receiver: 0}})"
                "  });"
                "  if (!r.ok) { const t = await r.text(); return {detail: t || r.statusText}; }"
                "  return await r.json();"
                "})()",
                timeout=15.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            ui.notify(f"NRZ sweep started on lane {lane}", type="positive")
            state["polling"] = True
            progress_card.set_visibility(True)
            _start_polling()
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def _start_pam4_sweep(lane: int, port: int):
        try:
            resp = await ui.run_javascript(
                "return (async () => {"
                f'  const r = await fetch("/api/devices/{device_id}'
                f'/phy/margining/sweep-pam4", {{'
                f'    method: "POST", headers: {{"Content-Type": "application/json"}},'
                f"    body: JSON.stringify({{port_number: {port}, lane: {lane}}})"
                "  });"
                "  if (!r.ok) { const t = await r.text(); return {detail: t || r.statusText}; }"
                "  return await r.json();"
                "})()",
                timeout=15.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            ui.notify(f"PAM4 3-eye sweep started on lane {lane}", type="positive")
            state["polling"] = True
            progress_card.set_visibility(True)
            _start_polling()
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def reset_lane():
        port = state["port_number"]
        lane = state["lane"]
        try:
            resp = await ui.run_javascript(
                "return (async () => {"
                f'  const r = await fetch("/api/devices/{device_id}'
                f'/phy/margining/reset", {{'
                f'    method: "POST", headers: {{"Content-Type": "application/json"}},'
                f"    body: JSON.stringify({{port_number: {port}, lane: {lane}}})"
                "  });"
                "  if (!r.ok) { const t = await r.text(); return {detail: t || r.statusText}; }"
                "  return await r.json();"
                "})()",
                timeout=10.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            ui.notify(f"Lane {lane} reset to normal", type="info")
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    def _start_polling():
        if poll_timer["ref"] is not None:
            return
        if state["is_pam4"]:
            poll_timer["ref"] = ui.timer(0.5, _poll_pam4_progress)
        else:
            poll_timer["ref"] = ui.timer(0.5, poll_progress)

    async def poll_progress():
        lane = state["lane"]
        try:
            resp = await ui.run_javascript(
                "return (async () => {"
                f'  const r = await fetch("/api/devices/{device_id}'
                f'/phy/margining/progress?lane={lane}");'
                "  if (!r.ok) return {status: 'error', error: await r.text()};"
                "  return await r.json();"
                "})()",
                timeout=10.0,
            )
        except Exception:
            return

        status = resp.get("status", "idle")
        percent = resp.get("percent", 0)
        current = resp.get("current_step", 0)
        total = resp.get("total_steps", 0)

        progress_bar.set_value(percent / 100)
        progress_label.set_text(f"{status.upper()} - Step {current}/{total} ({percent:.0f}%)")

        if status == "complete":
            _stop_polling()
            state["polling"] = False
            ui.notify("Sweep complete!", type="positive")
            await fetch_result()
        elif status == "error":
            _stop_polling()
            state["polling"] = False
            error_msg = resp.get("error", "Unknown error")
            ui.notify(f"Sweep error: {error_msg}", type="negative")

    async def _poll_pam4_progress():
        lane = state["lane"]
        try:
            resp = await ui.run_javascript(
                "return (async () => {"
                f'  const r = await fetch("/api/devices/{device_id}'
                f'/phy/margining/progress-pam4?lane={lane}");'
                "  if (!r.ok) return {status: 'error', error: await r.text()};"
                "  return await r.json();"
                "})()",
                timeout=10.0,
            )
        except Exception:
            return

        status = resp.get("status", "idle")
        percent = resp.get("percent", 0)
        overall_step = resp.get("overall_step", 0)
        overall_total = resp.get("overall_total_steps", 0)
        current_eye = resp.get("current_eye", "")
        eye_index = resp.get("current_eye_index", 0)

        progress_bar.set_value(percent / 100)
        if current_eye:
            eye_label = current_eye.capitalize()
            progress_label.set_text(
                f"PAM4 - {eye_label} Eye ({eye_index + 1}/3) - "
                f"Step {overall_step}/{overall_total} ({percent:.0f}%)"
            )
        else:
            progress_label.set_text(f"{status.upper()} ({percent:.0f}%)")

        if status == "complete":
            _stop_polling()
            state["polling"] = False
            ui.notify("PAM4 3-eye sweep complete!", type="positive")
            await _fetch_pam4_result()
        elif status == "error":
            _stop_polling()
            state["polling"] = False
            error_msg = resp.get("error", "Unknown error")
            ui.notify(f"PAM4 sweep error: {error_msg}", type="negative")

    def _stop_polling():
        if poll_timer["ref"] is not None:
            poll_timer["ref"].cancel()
            poll_timer["ref"] = None

    async def fetch_result():
        lane = state["lane"]
        try:
            resp = await ui.run_javascript(
                "return (async () => {"
                f'  const r = await fetch("/api/devices/{device_id}'
                f'/phy/margining/result?lane={lane}");'
                "  if (!r.ok) { const t = await r.text(); return {detail: t || r.statusText}; }"
                "  return await r.json();"
                "})()",
                timeout=10.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            nrz_chart_container.set_visibility(True)
            pam4_chart_container.set_visibility(False)
            _render_eye_chart(nrz_eye_chart, resp, COLORS.cyan)
            _render_nrz_results_summary(resp)
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def _fetch_pam4_result():
        lane = state["lane"]
        try:
            resp = await ui.run_javascript(
                "return (async () => {"
                f'  const r = await fetch("/api/devices/{device_id}'
                f'/phy/margining/result-pam4?lane={lane}");'
                "  if (!r.ok) { const t = await r.text(); return {detail: t || r.statusText}; }"
                "  return await r.json();"
                "})()",
                timeout=10.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            nrz_chart_container.set_visibility(False)
            pam4_chart_container.set_visibility(True)
            _render_pam4_charts(resp)
            _render_pam4_results_summary(resp)
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    def _render_eye_chart(chart, data: dict, accent_color: str):
        """Populate a single eye chart with a 2D eye diagram.

        Uses step-distance (L1/diamond norm) to create the eye shape:
        each grid point is colored by its normalized distance from center.
        Center = green (eye open), edges = red (eye closed).  The measured
        eye boundary diamond is overlaid.

        For receivers that didn't respond (all timeouts), shows a
        'No Data' annotation instead of a misleading heatmap.
        """
        caps = data.get("capabilities", {})
        num_timing = caps.get("num_timing_steps", 1)
        num_voltage = caps.get("num_voltage_steps", 1)

        # Detect whether this receiver produced real data.
        # Real data has varying error counts; timeout/stale data is constant.
        right_pts = [
            p for p in data.get("timing_points", []) if p["direction"] == "right"
        ]
        up_pts = [
            p for p in data.get("voltage_points", [])
            if p["direction"] == "up" and p.get("status_code", 0) != 3
        ]
        right_values = {p["margin_value"] for p in right_pts}
        up_values = {p["margin_value"] for p in up_pts}

        # If both axes show ≤2 unique values (e.g. {0, 28} from stale + padding)
        # AND no measurable eye opening, treat as "no data".
        eye_w = data.get("eye_width_ui", 0)
        eye_h = data.get("eye_height_mv", 0)
        no_data = (
            len(right_values) <= 2
            and len(up_values) <= 2
            and eye_w == 0
            and eye_h == 0
        )

        if no_data:
            chart.options["series"] = []
            chart.options["graphic"] = {
                "elements": [{
                    "type": "text",
                    "left": "center",
                    "top": "middle",
                    "style": {
                        "text": "No Data\nReceiver did not respond",
                        "fontSize": 16,
                        "fontWeight": "bold",
                        "fill": COLORS.text_muted,
                        "textAlign": "center",
                    },
                }],
            }
            chart.options.pop("visualMap", None)
            chart.update()
            return

        # Clear any previous "No Data" graphic.
        chart.options.pop("graphic", None)

        # Find usable voltage range (last step before NAK).
        max_usable_v = 0
        for pt in up_pts:
            max_usable_v = max(max_usable_v, pt["step"])
        max_v = max_usable_v if max_usable_v > 0 else num_voltage
        max_t = num_timing

        # Build 2D grid using diamond distance from center.
        # Distance = |t_frac| + |v_frac| where each axis is normalized
        # to 0..1 across its measurement range.  This naturally produces
        # a diamond (eye) shape: center = 0, corners = 2.
        points: list[list[float]] = []

        for t in range(0, max_t + 1):
            t_frac = t / max_t if max_t > 0 else 0.0
            x_ui = (t / num_timing) * 0.5 if num_timing > 0 else 0.0
            for v in range(0, max_v + 1):
                v_frac = v / max_v if max_v > 0 else 0.0
                y_mv = (v / num_voltage) * 500.0 if num_voltage > 0 else 0.0
                distance = t_frac + v_frac
                # Mirror into all 4 quadrants
                x_vals = (x_ui, -x_ui) if t > 0 else (x_ui,)
                y_vals = (y_mv, -y_mv) if v > 0 else (y_mv,)
                for xv in x_vals:
                    for yv in y_vals:
                        points.append([round(xv, 4), round(yv, 2), round(distance, 3)])

        grid_steps = max(max_t, max_v, 1)
        sym_size = max(5, min(14, 360 // grid_steps))

        series: list[dict] = [
            {
                "name": "Margin",
                "type": "scatter",
                "data": points,
                "symbolSize": sym_size,
                "symbol": "rect",
            },
        ]

        # Eye boundary diamond overlay.
        if eye_w > 0 or eye_h > 0:
            hw = round(eye_w / 2, 4)
            hh = round(eye_h / 2, 2)
            series.append({
                "name": "Eye Boundary",
                "type": "line",
                "data": [[hw, 0], [0, hh], [-hw, 0], [0, -hh], [hw, 0]],
                "lineStyle": {"color": accent_color, "width": 3, "type": "dashed"},
                "itemStyle": {"color": accent_color},
                "showSymbol": False,
                "z": 10,
            })

        chart.options["visualMap"] = {
            "min": 0.0,
            "max": 2.0,
            "dimension": 2,
            "inRange": {
                "color": ["#4CAF50", "#8BC34A", "#FFEB3B", "#FF9800", "#F44336"],
            },
            "text": ["Edge", "Center"],
            "textStyle": {"color": COLORS.text_secondary},
            "right": 10,
        }
        chart.options["series"] = series
        chart.update()

    def _render_nrz_results_summary(data: dict):
        results_card.set_visibility(True)
        results_container.clear()
        with results_container:
            with ui.row().classes("w-full gap-8 items-start"):
                _result_stat(
                    "Eye Width",
                    f"{data.get('eye_width_steps', 0)} steps",
                    f"({data.get('eye_width_ui', 0):.4f} UI)",
                    COLORS.cyan,
                )
                _result_stat(
                    "Eye Height",
                    f"{data.get('eye_height_steps', 0)} steps",
                    f"({data.get('eye_height_mv', 0):.1f} mV)",
                    COLORS.cyan,
                )
                _result_stat(
                    "Lane",
                    str(data.get("lane", 0)),
                    f"Receiver {data.get('receiver', 0)}",
                    COLORS.text_primary,
                )
                _result_stat(
                    "Sweep Time",
                    f"{data.get('sweep_time_ms', 0)} ms",
                    "",
                    COLORS.text_secondary,
                )

                timing_pts = data.get("timing_points", [])
                voltage_pts = data.get("voltage_points", [])
                total = len(timing_pts) + len(voltage_pts)
                passed = sum(1 for p in timing_pts if p["passed"]) + sum(
                    1 for p in voltage_pts if p["passed"]
                )
                color = COLORS.green if passed > 0 else COLORS.red
                _result_stat("Pass/Total", f"{passed}/{total}", "", color)

    def _render_pam4_charts(data: dict):
        """Render 3 stacked eye charts for PAM4 result."""
        for label, chart in pam4_eye_charts.items():
            eye_data = data.get(f"{label}_eye", {})
            accent = _PAM4_COLORS.get(label, COLORS.cyan)
            _render_eye_chart(chart, eye_data, accent)

            # Update per-eye stats below each chart
            stats_row = pam4_eye_stats[label]
            stats_row.clear()
            with stats_row:
                w_ui = eye_data.get("eye_width_ui", 0)
                h_mv = eye_data.get("eye_height_mv", 0)
                ui.label(f"Width: {w_ui:.4f} UI").style(
                    f"color: {accent}; font-size: 13px; font-weight: bold;"
                )
                ui.label(f"Height: {h_mv:.1f} mV").style(
                    f"color: {accent}; font-size: 13px; font-weight: bold;"
                )
                t_ms = eye_data.get("sweep_time_ms", 0)
                ui.label(f"Time: {t_ms} ms").style(f"color: {COLORS.text_muted}; font-size: 12px;")

    def _render_pam4_results_summary(data: dict):
        """Render aggregate PAM4 summary below the 3 charts."""
        results_card.set_visibility(True)
        results_container.clear()
        with results_container:
            with ui.row().classes("w-full gap-8 items-start"):
                _result_stat(
                    "Worst Eye Width",
                    f"{data.get('worst_eye_width_ui', 0):.4f} UI",
                    "min of 3 eyes",
                    COLORS.cyan,
                )
                _result_stat(
                    "Worst Eye Height",
                    f"{data.get('worst_eye_height_mv', 0):.1f} mV",
                    "min of 3 eyes",
                    COLORS.cyan,
                )
                balanced = data.get("is_balanced", False)
                bal_color = COLORS.green if balanced else COLORS.yellow
                bal_text = "Balanced" if balanced else "Imbalanced"
                _result_stat("Eye Balance", bal_text, "heights within 20%", bal_color)
                _result_stat(
                    "Lane",
                    str(data.get("lane", 0)),
                    "PAM4 (3 Eyes)",
                    COLORS.text_primary,
                )
                _result_stat(
                    "Total Sweep Time",
                    f"{data.get('total_sweep_time_ms', 0)} ms",
                    "",
                    COLORS.text_secondary,
                )

    # --- Page layout ---

    # Controls card
    with (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    ):
        ui.label("Lane Margining Controls").classes("text-h6").style(
            f"color: {COLORS.text_primary};"
        )
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
                .classes("w-32")
            )
            port_input.on_value_change(
                lambda e: state.update({"port_number": int(e.value or 0)})
            )

            lane_input = (
                ui.number(
                    "Lane",
                    value=0,
                    min=0,
                    max=15,
                    step=1,
                )
                .props("dense outlined")
                .classes("w-32")
            )
            lane_input.on_value_change(lambda e: state.update({"lane": int(e.value or 0)}))

            ui.button("Check Capabilities", on_click=check_capabilities).props("flat color=primary")
            ui.button("Start Sweep", on_click=start_sweep).props("flat color=positive")
            ui.button("Reset Lane", on_click=reset_lane).props("flat color=warning")

        # Capabilities display
        caps_container = ui.row().classes("w-full gap-6 mt-3")

        @ui.refreshable
        def refresh_capabilities():
            caps_container.clear()
            with caps_container:
                caps = state["capabilities"]
                if caps is None:
                    ui.label("Press 'Check Capabilities' to read device margining support.").style(
                        f"color: {COLORS.text_muted}; font-size: 13px;"
                    )
                    return
                _caps_chip("Link Speed", caps.get("link_speed", "Unknown"))
                _caps_chip("Timing Steps", str(caps.get("num_timing_steps", 0)))
                _caps_chip("Voltage Steps", str(caps.get("num_voltage_steps", 0)))
                _caps_chip("Max Timing Offset", str(caps.get("max_timing_offset", 0)))
                _caps_chip("Max Voltage Offset", str(caps.get("max_voltage_offset", 0)))
                _caps_chip("Sample Count", str(caps.get("sample_count", 0)))
                ind_v = caps.get("ind_up_down_voltage", False)
                ind_t = caps.get("ind_left_right_timing", False)
                _caps_chip("Ind Up/Down V", "Yes" if ind_v else "No")
                _caps_chip("Ind Left/Right T", "Yes" if ind_t else "No")

                # Modulation indicator
                mod = state["modulation"]
                if mod == "PAM4":
                    mod_text = "PAM4 (3 Eyes)"
                    mod_color = "#AA66FF"
                else:
                    mod_text = "NRZ (Single Eye)"
                    mod_color = COLORS.cyan
                with ui.column().classes("items-center"):
                    ui.label(mod_text).classes("text-subtitle1 mono").style(
                        f"color: {mod_color}; font-weight: bold;"
                    )
                    ui.label("Modulation").style(f"color: {COLORS.text_muted}; font-size: 11px;")

        refresh_capabilities()

    # Progress card (hidden until sweep starts)
    progress_card = (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    )
    progress_card.set_visibility(False)
    with progress_card:
        ui.label("Sweep Progress").classes("text-h6").style(f"color: {COLORS.text_primary};")
        progress_bar = (
            ui.linear_progress(value=0, show_value=False)
            .classes("w-full mt-2")
            .props(f'color="{COLORS.cyan}"')
        )
        progress_label = ui.label("IDLE").style(f"color: {COLORS.text_secondary}; font-size: 13px;")

    # NRZ eye diagram chart container (single eye)
    nrz_chart_container = (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    )
    nrz_chart_container.set_visibility(False)
    with nrz_chart_container:
        ui.label("Eye Diagram").classes("text-h6").style(f"color: {COLORS.text_primary};")
        nrz_eye_chart = _create_eye_echart()

    # PAM4 3-eye chart container (3 stacked eyes)
    pam4_chart_container = (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    )
    pam4_chart_container.set_visibility(False)
    pam4_eye_charts: dict[str, ui.echart] = {}
    pam4_eye_stats: dict[str, ui.row] = {}
    with pam4_chart_container:
        ui.label("PAM4 3-Eye Diagram").classes("text-h6").style(f"color: {COLORS.text_primary};")
        for label in ("upper", "middle", "lower"):
            accent = _PAM4_COLORS[label]
            ui.label(f"{label.capitalize()} Eye (Receiver {_EYE_TO_RECEIVER[label]})").style(
                f"color: {accent}; font-size: 14px; font-weight: bold; margin-top: 12px;"
            )
            pam4_eye_charts[label] = _create_eye_echart(height="280px")
            pam4_eye_stats[label] = ui.row().classes("w-full gap-6 mb-2")

    # Results summary card (hidden until result available)
    results_card = (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    )
    results_card.set_visibility(False)
    with results_card:
        ui.label("Sweep Results").classes("text-h6").style(f"color: {COLORS.text_primary};")
        results_container = ui.row().classes("w-full mt-2")


def _create_eye_echart(height: str = "450px") -> ui.echart:
    """Create a reusable eye diagram EChart instance."""
    return (
        ui.echart(
            {
                "animation": False,
                "backgroundColor": "transparent",
                "grid": {"containLabel": True},
                "tooltip": {"trigger": "item"},
                "legend": {"textStyle": {"color": COLORS.text_secondary}},
                "xAxis": {
                    "type": "value",
                    "name": "Timing Offset (UI)",
                    "nameTextStyle": {"color": COLORS.text_secondary},
                    "axisLabel": {"color": COLORS.text_secondary},
                    "axisLine": {"lineStyle": {"color": COLORS.border}},
                    "splitLine": {"lineStyle": {"color": COLORS.border}},
                },
                "yAxis": {
                    "type": "value",
                    "name": "Voltage Offset (mV)",
                    "nameTextStyle": {"color": COLORS.text_secondary},
                    "axisLabel": {"color": COLORS.text_secondary},
                    "axisLine": {"lineStyle": {"color": COLORS.border}},
                    "splitLine": {"lineStyle": {"color": COLORS.border}},
                },
                "series": [],
            }
        )
        .classes("w-full")
        .style(f"height: {height}")
    )


def _caps_chip(label: str, value: str) -> None:
    """Render a small capability info chip."""
    with ui.column().classes("items-center"):
        ui.label(value).classes("text-subtitle1 mono").style(
            f"color: {COLORS.cyan}; font-weight: bold;"
        )
        ui.label(label).style(f"color: {COLORS.text_muted}; font-size: 11px;")


def _result_stat(label: str, value: str, subtitle: str, color: str) -> None:
    """Render a result statistic."""
    with ui.column().classes("items-center"):
        ui.label(value).classes("text-subtitle1").style(f"color: {color}; font-weight: bold;")
        if subtitle:
            ui.label(subtitle).style(f"color: {COLORS.text_secondary}; font-size: 12px;")
        ui.label(label).style(f"color: {COLORS.text_muted}; font-size: 11px;")
