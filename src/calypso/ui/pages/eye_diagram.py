"""Eye Diagram page - PCIe Lane Margining sweep visualization."""

from __future__ import annotations

from nicegui import ui

from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS


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
    }
    poll_timer: dict = {"ref": None}

    # --- Actions ---

    async def check_capabilities():
        port = state["port_number"]
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}'
                f'/phy/margining/capabilities?port_number={port}")).json()',
                timeout=10.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            state["capabilities"] = resp
            refresh_capabilities()
            ui.notify("Capabilities loaded", type="positive")
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def start_sweep():
        lane = state["lane"]
        port = state["port_number"]
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}'
                f'/phy/margining/sweep", {{'
                f'method: "POST", headers: {{"Content-Type": "application/json"}},'
                f'body: JSON.stringify({{lane: {lane}, port_number: {port}, receiver: 0}})'
                f'}})).json()',
                timeout=10.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            ui.notify(f"Sweep started on lane {lane}", type="positive")
            state["polling"] = True
            progress_card.set_visibility(True)
            _start_polling()
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def reset_lane():
        lane = state["lane"]
        port = state["port_number"]
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}'
                f'/phy/margining/reset", {{'
                f'method: "POST", headers: {{"Content-Type": "application/json"}},'
                f'body: JSON.stringify({{lane: {lane}, port_number: {port}}})'
                f'}})).json()',
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
        poll_timer["ref"] = ui.timer(0.5, poll_progress)

    async def poll_progress():
        lane = state["lane"]
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}'
                f'/phy/margining/progress?lane={lane}")).json()',
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

    def _stop_polling():
        if poll_timer["ref"] is not None:
            poll_timer["ref"].cancel()
            poll_timer["ref"] = None

    async def fetch_result():
        lane = state["lane"]
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}'
                f'/phy/margining/result?lane={lane}")).json()',
                timeout=10.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            _render_eye_chart(resp)
            _render_results_summary(resp)
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    def _render_eye_chart(data: dict):
        caps = data.get("capabilities", {})
        num_timing = caps.get("num_timing_steps", 1)
        num_voltage = caps.get("num_voltage_steps", 1)

        pass_points: list[list[float]] = []
        fail_points: list[list[float]] = []
        boundary_points: list[list[float]] = []

        # Process timing points into X-axis positions
        max_pass_right = 0.0
        max_pass_left = 0.0
        for pt in data.get("timing_points", []):
            step = pt["step"]
            direction = pt["direction"]
            passed = pt["passed"]

            # Convert step to UI (timing offset)
            if num_timing > 0:
                x_ui = (step / num_timing) * 0.5
            else:
                x_ui = 0.0
            if direction == "left":
                x_ui = -x_ui

            # Timing points are at y=0
            point = [round(x_ui, 4), 0.0]
            if passed:
                pass_points.append(point)
                if direction == "right" and x_ui > max_pass_right:
                    max_pass_right = x_ui
                if direction == "left" and abs(x_ui) > abs(max_pass_left):
                    max_pass_left = x_ui
            else:
                fail_points.append(point)

        # Process voltage points into Y-axis positions
        max_pass_up = 0.0
        max_pass_down = 0.0
        for pt in data.get("voltage_points", []):
            step = pt["step"]
            direction = pt["direction"]
            passed = pt["passed"]

            # Convert step to mV
            if num_voltage > 0:
                y_mv = (step / num_voltage) * 500.0
            else:
                y_mv = 0.0
            if direction == "down":
                y_mv = -y_mv

            # Voltage points are at x=0
            point = [0.0, round(y_mv, 2)]
            if passed:
                pass_points.append(point)
                if direction == "up" and y_mv > max_pass_up:
                    max_pass_up = y_mv
                if direction == "down" and abs(y_mv) > abs(max_pass_down):
                    max_pass_down = y_mv
            else:
                fail_points.append(point)

        # Build diamond boundary from outermost passing points
        boundary_points = [
            [max_pass_right, 0.0],
            [0.0, max_pass_up],
            [max_pass_left, 0.0],
            [0.0, max_pass_down],
            [max_pass_right, 0.0],  # close the diamond
        ]

        eye_chart.options["series"] = [
            {
                "name": "Pass",
                "type": "scatter",
                "data": pass_points,
                "itemStyle": {"color": COLORS.green},
                "symbolSize": 8,
                "symbol": "circle",
            },
            {
                "name": "Fail",
                "type": "scatter",
                "data": fail_points,
                "itemStyle": {"color": COLORS.red},
                "symbolSize": 8,
                "symbol": "diamond",
            },
            {
                "name": "Eye Boundary",
                "type": "line",
                "data": boundary_points,
                "lineStyle": {"color": COLORS.cyan, "width": 2, "type": "dashed"},
                "itemStyle": {"color": COLORS.cyan},
                "showSymbol": False,
            },
        ]
        eye_chart.update()
        chart_card.set_visibility(True)

    def _render_results_summary(data: dict):
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

                # Pass/fail summary
                timing_pts = data.get("timing_points", [])
                voltage_pts = data.get("voltage_points", [])
                total = len(timing_pts) + len(voltage_pts)
                passed = sum(1 for p in timing_pts if p["passed"]) + sum(1 for p in voltage_pts if p["passed"])
                color = COLORS.green if passed > 0 else COLORS.red
                _result_stat("Pass/Total", f"{passed}/{total}", "", color)

    # --- Page layout ---

    # Controls card
    with ui.card().classes("w-full p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    ):
        ui.label("Lane Margining Controls").classes("text-h6").style(
            f"color: {COLORS.text_primary};"
        )
        with ui.row().classes("items-end gap-4 mt-2"):
            port_input = ui.number(
                "Port Number", value=0, min=0, max=143, step=1,
            ).props("dense outlined").classes("w-28")
            port_input.on_value_change(lambda e: state.update({"port_number": int(e.value or 0)}))

            lane_input = ui.number(
                "Lane", value=0, min=0, max=15, step=1,
            ).props("dense outlined").classes("w-28")
            lane_input.on_value_change(lambda e: state.update({"lane": int(e.value or 0)}))

            ui.button("Check Capabilities", on_click=check_capabilities).props(
                "flat color=primary"
            )
            ui.button("Start Sweep", on_click=start_sweep).props(
                "flat color=positive"
            )
            ui.button("Reset Lane", on_click=reset_lane).props(
                "flat color=warning"
            )

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
                _caps_chip("Timing Steps", str(caps.get("num_timing_steps", 0)))
                _caps_chip("Voltage Steps", str(caps.get("num_voltage_steps", 0)))
                _caps_chip("Max Timing Offset", str(caps.get("max_timing_offset", 0)))
                _caps_chip("Max Voltage Offset", str(caps.get("max_voltage_offset", 0)))
                ind_v = caps.get("ind_up_down_voltage", False)
                ind_t = caps.get("ind_left_right_timing", False)
                _caps_chip("Ind Up/Down V", "Yes" if ind_v else "No")
                _caps_chip("Ind Left/Right T", "Yes" if ind_t else "No")

        refresh_capabilities()

    # Progress card (hidden until sweep starts)
    progress_card = ui.card().classes("w-full p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    )
    progress_card.set_visibility(False)
    with progress_card:
        ui.label("Sweep Progress").classes("text-h6").style(
            f"color: {COLORS.text_primary};"
        )
        progress_bar = ui.linear_progress(value=0, show_value=False).classes("w-full mt-2").props(
            f'color="{COLORS.cyan}"'
        )
        progress_label = ui.label("IDLE").style(
            f"color: {COLORS.text_secondary}; font-size: 13px;"
        )

    # Eye diagram chart card (hidden until result available)
    chart_card = ui.card().classes("w-full p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    )
    chart_card.set_visibility(False)
    with chart_card:
        ui.label("Eye Diagram").classes("text-h6").style(
            f"color: {COLORS.text_primary};"
        )
        eye_chart = ui.echart({
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
        }).classes("w-full").style("height: 450px")

    # Results summary card (hidden until result available)
    results_card = ui.card().classes("w-full p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    )
    results_card.set_visibility(False)
    with results_card:
        ui.label("Sweep Results").classes("text-h6").style(
            f"color: {COLORS.text_primary};"
        )
        results_container = ui.row().classes("w-full mt-2")


def _caps_chip(label: str, value: str) -> None:
    """Render a small capability info chip."""
    with ui.column().classes("items-center"):
        ui.label(value).classes("text-subtitle1 mono").style(
            f"color: {COLORS.cyan}; font-weight: bold;"
        )
        ui.label(label).style(
            f"color: {COLORS.text_muted}; font-size: 11px;"
        )


def _result_stat(label: str, value: str, subtitle: str, color: str) -> None:
    """Render a result statistic."""
    with ui.column().classes("items-center"):
        ui.label(value).classes("text-subtitle1").style(
            f"color: {color}; font-weight: bold;"
        )
        if subtitle:
            ui.label(subtitle).style(
                f"color: {COLORS.text_secondary}; font-size: 12px;"
            )
        ui.label(label).style(
            f"color: {COLORS.text_muted}; font-size: 11px;"
        )
