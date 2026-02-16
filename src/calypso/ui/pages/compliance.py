"""PCIe Compliance Testing page."""

from __future__ import annotations

import json

from nicegui import ui

from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS


def compliance_page(device_id: str) -> None:
    """Render the Compliance Testing page."""

    def content():
        _compliance_content(device_id)

    page_layout("Compliance Testing", content, device_id=device_id)


def _compliance_content(device_id: str) -> None:
    """Build the compliance page content inside page_layout."""

    state: dict = {
        "suites": {
            "link_training": True,
            "error_audit": True,
            "config_audit": True,
            "signal_integrity": True,
            "ber_test": True,
            "port_sweep": True,
        },
        "ports": [{"port_number": 0, "port_select": 0, "num_lanes": 16}],
        "ber_duration_s": 10.0,
        "idle_wait_s": 5.0,
        "speed_settle_s": 2.0,
        "polling": False,
        "result": None,
    }
    poll_timer: dict = {"ref": None}

    # --- Actions ---

    async def start_run():
        suites = [k for k, v in state["suites"].items() if v]
        if not suites:
            ui.notify("Select at least one test suite", type="warning")
            return

        ports = state["ports"]
        body = {
            "suites": suites,
            "ports": ports,
            "ber_duration_s": state["ber_duration_s"],
            "idle_wait_s": state["idle_wait_s"],
            "speed_settle_s": state["speed_settle_s"],
        }

        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}'
                f'/compliance/start", {{'
                f'method: "POST", headers: {{"Content-Type": "application/json"}},'
                f'body: JSON.stringify({json.dumps(body)})'
                f'}})).json()',
                timeout=10.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            ui.notify("Compliance run started", type="positive")
            state["polling"] = True
            state["result"] = None
            progress_card.set_visibility(True)
            results_card.set_visibility(False)
            _start_polling()
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    async def cancel_run():
        try:
            await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}'
                f'/compliance/cancel", {{method: "POST"}})).json()',
                timeout=10.0,
            )
            ui.notify("Cancellation requested", type="info")
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    def _start_polling():
        if poll_timer["ref"] is not None:
            return
        poll_timer["ref"] = ui.timer(1.0, poll_progress)

    async def poll_progress():
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}'
                f'/compliance/progress")).json()',
                timeout=10.0,
            )
        except Exception:
            return

        status = resp.get("status", "idle")
        percent = resp.get("percent", 0)
        completed = resp.get("tests_completed", 0)
        total = resp.get("tests_total", 0)
        suite = resp.get("current_suite", "")
        test = resp.get("current_test", "")
        elapsed = resp.get("elapsed_ms", 0)

        progress_bar.set_value(percent / 100)
        progress_label.set_text(
            f"{status.upper()} - {suite}: {test} ({completed}/{total}, {percent:.0f}%)"
        )
        elapsed_label.set_text(f"Elapsed: {elapsed / 1000:.1f}s")

        if status in ("complete", "cancelled", "error"):
            _stop_polling()
            state["polling"] = False

            if status == "error":
                error_msg = resp.get("error", "Unknown error")
                ui.notify(f"Run failed: {error_msg}", type="negative")
            elif status == "cancelled":
                ui.notify("Run cancelled", type="warning")
            else:
                ui.notify("Compliance run complete!", type="positive")

            await fetch_result()

    def _stop_polling():
        if poll_timer["ref"] is not None:
            poll_timer["ref"].cancel()
            poll_timer["ref"] = None

    async def fetch_result():
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}'
                f'/compliance/result")).json()',
                timeout=10.0,
            )
            if resp.get("detail"):
                return
            state["result"] = resp
            _render_results(resp)
        except Exception:
            pass

    def _render_results(data: dict):
        results_card.set_visibility(True)
        results_container.clear()
        with results_container:
            # Summary stats
            overall = data.get("overall_verdict", "unknown")
            overall_color = _verdict_color(overall)

            with ui.row().classes("w-full gap-6 items-center"):
                _stat_chip("Overall", overall.upper(), overall_color)
                _stat_chip("Pass", str(data.get("total_pass", 0)), COLORS.green)
                _stat_chip("Fail", str(data.get("total_fail", 0)), COLORS.red)
                _stat_chip("Warn", str(data.get("total_warn", 0)), COLORS.yellow)
                _stat_chip("Skip", str(data.get("total_skip", 0)), COLORS.text_muted)
                _stat_chip("Duration", f"{data.get('duration_ms', 0) / 1000:.1f}s", COLORS.text_secondary)

                ui.button(
                    "Download Report",
                    icon="download",
                    on_click=lambda: ui.run_javascript(
                        f'window.open("/api/devices/{device_id}/compliance/report", "_blank")'
                    ),
                ).props("flat color=primary")

            # Per-suite results
            for suite in data.get("suites", []):
                suite_name = suite.get("suite_name", "")
                tests = suite.get("tests", [])
                fail_count = sum(1 for t in tests if t.get("verdict") == "fail")

                with ui.card().classes("w-full p-3 mt-3").style(
                    f"background: {COLORS.bg_primary}; border: 1px solid {COLORS.border}"
                ):
                    badge_color = COLORS.green if fail_count == 0 else COLORS.red
                    badge_text = f"{len(tests) - fail_count}/{len(tests)} pass" if fail_count == 0 else f"{fail_count} fail"

                    with ui.row().classes("items-center gap-2"):
                        ui.label(suite_name).classes("text-subtitle1").style(
                            f"color: {COLORS.text_primary}; font-weight: bold;"
                        )
                        ui.badge(badge_text).style(
                            f"background: {badge_color}30; color: {badge_color};"
                        )

                    columns = [
                        {"name": "test_id", "label": "ID", "field": "test_id", "align": "left"},
                        {"name": "test_name", "label": "Test", "field": "test_name", "align": "left"},
                        {"name": "verdict", "label": "Verdict", "field": "verdict", "align": "center"},
                        {"name": "message", "label": "Message", "field": "message", "align": "left"},
                        {"name": "duration_ms", "label": "Duration", "field": "duration_ms", "align": "right"},
                    ]

                    rows = []
                    for i, t in enumerate(tests):
                        rows.append({
                            "id": i,
                            "test_id": t.get("test_id", ""),
                            "test_name": t.get("test_name", ""),
                            "verdict": t.get("verdict", "").upper(),
                            "message": t.get("message", ""),
                            "duration_ms": f"{t.get('duration_ms', 0):.0f}ms",
                        })

                    table = ui.table(
                        columns=columns,
                        rows=rows,
                        row_key="id",
                    ).classes("w-full")
                    table.props("dense flat")
                    table.style(f"background: {COLORS.bg_primary}")

    def add_port():
        state["ports"].append({"port_number": 0, "port_select": 0, "num_lanes": 16})
        refresh_ports()

    def remove_port(idx: int):
        if len(state["ports"]) > 1:
            state["ports"].pop(idx)
            refresh_ports()

    # --- Page Layout ---

    # Configuration card
    with ui.card().classes("w-full p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    ):
        ui.label("Compliance Test Configuration").classes("text-h6").style(
            f"color: {COLORS.text_primary};"
        )

        # Suite selection
        ui.label("Test Suites").classes("text-subtitle2 mt-3").style(
            f"color: {COLORS.text_secondary};"
        )
        with ui.row().classes("gap-4 mt-1"):
            for suite_key, suite_label in [
                ("link_training", "Link Training"),
                ("error_audit", "Error Audit"),
                ("config_audit", "Config Audit"),
                ("signal_integrity", "Signal Integrity"),
                ("ber_test", "BER Test"),
                ("port_sweep", "Port Sweep"),
            ]:
                ui.checkbox(
                    suite_label,
                    value=True,
                    on_change=lambda e, k=suite_key: state["suites"].update({k: e.value}),
                ).props("dense")

        # Port configuration
        ui.label("Port Configuration").classes("text-subtitle2 mt-4").style(
            f"color: {COLORS.text_secondary};"
        )
        ports_container = ui.column().classes("w-full mt-1 gap-2")

        @ui.refreshable
        def refresh_ports():
            ports_container.clear()
            with ports_container:
                for i, port_cfg in enumerate(state["ports"]):
                    with ui.row().classes("items-end gap-3"):
                        pn = ui.number(
                            "Port", value=port_cfg["port_number"],
                            min=0, max=143, step=1,
                        ).props("dense outlined").classes("w-24")
                        pn.on_value_change(
                            lambda e, idx=i: state["ports"][idx].update(
                                {"port_number": int(e.value or 0)}
                            )
                        )

                        ps = ui.number(
                            "Select", value=port_cfg["port_select"],
                            min=0, max=15, step=1,
                        ).props("dense outlined").classes("w-20")
                        ps.on_value_change(
                            lambda e, idx=i: state["ports"][idx].update(
                                {"port_select": int(e.value or 0)}
                            )
                        )

                        nl = ui.number(
                            "Lanes", value=port_cfg["num_lanes"],
                            min=1, max=16, step=1,
                        ).props("dense outlined").classes("w-20")
                        nl.on_value_change(
                            lambda e, idx=i: state["ports"][idx].update(
                                {"num_lanes": int(e.value or 16)}
                            )
                        )

                        if len(state["ports"]) > 1:
                            ui.button(
                                icon="remove_circle",
                                on_click=lambda _, idx=i: remove_port(idx),
                            ).props("flat dense color=negative")

                ui.button("Add Port", icon="add", on_click=add_port).props(
                    "flat dense color=primary"
                ).classes("mt-1")

        refresh_ports()

        # Timing parameters
        ui.label("Timing Parameters").classes("text-subtitle2 mt-4").style(
            f"color: {COLORS.text_secondary};"
        )
        with ui.row().classes("items-end gap-4 mt-1"):
            ber_input = ui.number(
                "BER Duration (s)", value=10.0, min=1.0, max=300.0, step=1.0,
            ).props("dense outlined").classes("w-36")
            ber_input.on_value_change(
                lambda e: state.update({"ber_duration_s": float(e.value or 10.0)})
            )

            idle_input = ui.number(
                "Idle Wait (s)", value=5.0, min=1.0, max=60.0, step=1.0,
            ).props("dense outlined").classes("w-32")
            idle_input.on_value_change(
                lambda e: state.update({"idle_wait_s": float(e.value or 5.0)})
            )

            settle_input = ui.number(
                "Speed Settle (s)", value=2.0, min=0.5, max=10.0, step=0.5,
            ).props("dense outlined").classes("w-36")
            settle_input.on_value_change(
                lambda e: state.update({"speed_settle_s": float(e.value or 2.0)})
            )

        # Action buttons
        with ui.row().classes("gap-3 mt-4"):
            ui.button("Start Test Run", icon="play_arrow", on_click=start_run).props(
                "color=positive"
            )
            ui.button("Cancel", icon="stop", on_click=cancel_run).props(
                "flat color=negative"
            )

    # Progress card (hidden until running)
    progress_card = ui.card().classes("w-full p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    )
    progress_card.set_visibility(False)
    with progress_card:
        ui.label("Test Progress").classes("text-h6").style(
            f"color: {COLORS.text_primary};"
        )
        progress_bar = ui.linear_progress(value=0, show_value=False).classes("w-full mt-2").props(
            f'color="{COLORS.cyan}"'
        )
        progress_label = ui.label("IDLE").style(
            f"color: {COLORS.text_secondary}; font-size: 13px;"
        )
        elapsed_label = ui.label("").style(
            f"color: {COLORS.text_muted}; font-size: 12px;"
        )

    # Results card (hidden until complete)
    results_card = ui.card().classes("w-full p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    )
    results_card.set_visibility(False)
    with results_card:
        ui.label("Test Results").classes("text-h6").style(
            f"color: {COLORS.text_primary};"
        )
        results_container = ui.column().classes("w-full mt-2")


def _stat_chip(label: str, value: str, color: str) -> None:
    """Render a summary stat chip."""
    with ui.column().classes("items-center"):
        ui.label(value).classes("text-subtitle1").style(
            f"color: {color}; font-weight: bold;"
        )
        ui.label(label).style(
            f"color: {COLORS.text_muted}; font-size: 11px;"
        )


def _verdict_color(verdict: str) -> str:
    """Map verdict string to a theme color."""
    return {
        "pass": COLORS.green,
        "fail": COLORS.red,
        "warn": COLORS.yellow,
        "skip": COLORS.text_muted,
        "error": COLORS.red,
    }.get(verdict, COLORS.text_secondary)
