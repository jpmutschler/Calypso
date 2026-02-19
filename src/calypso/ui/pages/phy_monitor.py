"""PHY layer monitoring and diagnostics page."""

from __future__ import annotations

import asyncio

from nicegui import ui

from calypso.ui.components.status_indicator import (
    link_status_badge,
    port_role_badge,
    speed_badge,
)
from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS


def phy_monitor_page(device_id: str) -> None:
    """Render the PHY monitoring page."""

    def content():
        _phy_monitor_content(device_id)

    page_layout("PHY Monitor", content, device_id=device_id)


def _phy_monitor_content(device_id: str) -> None:  # noqa: C901
    """Build the PHY monitor page content inside page_layout."""

    # --- Shared state ---
    ports_data: list[dict] = []
    speeds_data: dict = {}
    eq_data: dict = {"eq_16gt": None, "eq_32gt": None, "eq_64gt": None}
    lane_eq_data: dict = {"lanes": []}
    serdes_data: dict = {"lanes": []}
    port_ctrl_data: dict = {}
    cmd_status_data: dict = {}
    utp_results_data: dict = {"results": []}
    utp_monitoring: dict = {"active": False, "timer": None}

    # --- Helpers ---

    def _selected_port() -> int:
        val = port_select.value
        if val is None:
            return 0
        return int(val)

    def _selected_lanes() -> int:
        return int(lanes_input.value or 16)

    # --- Data loaders ---

    async def load_ports():
        """Fetch active ports and populate the port dropdown."""
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/ports")).json()',
                timeout=15.0,
            )
            ports_data.clear()
            ports_data.extend(resp)
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
                first = active[0]
                port_select.set_value(str(first["port_number"]))
                lanes_input.set_value(min(first.get("link_width", 16), 16))
        except Exception as e:
            ui.notify(f"Error loading ports: {e}", type="negative")

    async def on_port_changed(_e=None):
        """When port selection changes, refresh link summary + Tab 1 data."""
        if port_select.value is not None:
            refresh_link_summary()
            await asyncio.gather(
                load_speeds(),
                load_eq_status(),
                load_lane_eq(),
            )

    async def load_speeds():
        pn = _selected_port()
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/phy/speeds?port_number={pn}")).json()',
                timeout=10.0,
            )
            speeds_data.clear()
            speeds_data.update(resp)
            refresh_speeds()
        except Exception as e:
            ui.notify(f"Error loading speeds: {e}", type="negative")

    async def load_eq_status():
        pn = _selected_port()
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/phy/eq-status?port_number={pn}")).json()',
                timeout=10.0,
            )
            eq_data.clear()
            eq_data.update(resp)
            refresh_eq_status()
        except Exception as e:
            ui.notify(f"Error loading EQ status: {e}", type="negative")

    async def load_lane_eq():
        pn = _selected_port()
        nl = _selected_lanes()
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/phy/lane-eq?port_number={pn}&num_lanes={nl}")).json()',
                timeout=10.0,
            )
            lane_eq_data["lanes"] = resp.get("lanes", [])
            refresh_lane_eq()
        except Exception as e:
            ui.notify(f"Error loading lane EQ: {e}", type="negative")

    async def clear_all_serdes():
        pn = _selected_port()
        nl = _selected_lanes()
        try:
            await asyncio.gather(
                *(
                    ui.run_javascript(
                        f'return await (await fetch("/api/devices/{device_id}/phy/serdes-diag/clear?port_number={pn}", '
                        f'{{method:"POST",headers:{{"Content-Type":"application/json"}},'
                        f"body:JSON.stringify({{lane:{lane}}})}})).json()",
                        timeout=10.0,
                    )
                    for lane in range(nl)
                )
            )
            ui.notify(f"All {nl} lane errors cleared", type="positive")
            await load_utp_results()
        except Exception as e:
            ui.notify(f"Error clearing lanes: {e}", type="negative")

    async def load_port_control():
        pn = _selected_port()
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/phy/port-control?port_number={pn}")).json()',
                timeout=10.0,
            )
            port_ctrl_data.clear()
            port_ctrl_data.update(resp)
            refresh_port_control()
        except Exception as e:
            ui.notify(f"Error loading port control: {e}", type="negative")

    async def load_cmd_status():
        pn = _selected_port()
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/phy/cmd-status?port_number={pn}")).json()',
                timeout=10.0,
            )
            cmd_status_data.clear()
            cmd_status_data.update(resp)
            refresh_cmd_status()
        except Exception as e:
            ui.notify(f"Error loading PHY cmd/status: {e}", type="negative")

    async def prepare_utp():
        pn = _selected_port()
        preset = utp_preset_select.value or "prbs7"
        rate = int(utp_rate_select.value or 2)
        ps = int(utp_port_select.value or 0)
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/phy/utp/prepare?port_number={pn}", '
                f'{{method:"POST",headers:{{"Content-Type":"application/json"}},'
                f'body:JSON.stringify({{preset:"{preset}",rate:{rate},port_select:{ps}}})}})).json()',
                timeout=10.0,
            )
            ui.notify(
                f"UTP prepared: {resp.get('pattern', '')} @ {resp.get('rate', '')}",
                type="positive",
            )
            utp_step_label.set_text("Pattern loaded -- click Start Monitoring to begin.")
            utp_step_label.style(f"color: {COLORS.cyan}")
        except Exception as e:
            ui.notify(f"Error preparing UTP: {e}", type="negative")

    async def load_utp_results():
        pn = _selected_port()
        nl = _selected_lanes()
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/phy/utp/results?port_number={pn}&num_lanes={nl}")).json()',
                timeout=10.0,
            )
            utp_results_data["results"] = resp.get("results", [])
            serdes_data["lanes"] = [
                {
                    "lane": r["lane"],
                    "synced": r.get("synced", False),
                    "error_count": r.get("error_count", 0),
                    "expected_data": r.get("expected_on_error") or 0,
                    "actual_data": r.get("actual_on_error") or 0,
                }
                for r in resp.get("results", [])
            ]
            refresh_utp_serdes()
        except Exception as e:
            ui.notify(f"Error loading UTP results: {e}", type="negative")

    def start_monitoring():
        if utp_monitoring["active"]:
            return
        utp_monitoring["active"] = True
        utp_step_label.set_text("Monitoring SerDes -- data refreshing automatically...")
        utp_step_label.style(f"color: {COLORS.green}")
        start_btn.set_visibility(False)
        stop_btn.set_visibility(True)
        if utp_monitoring["timer"] is not None:
            utp_monitoring["timer"].activate()

    def stop_monitoring():
        utp_monitoring["active"] = False
        utp_step_label.set_text("Monitoring stopped.")
        utp_step_label.style(f"color: {COLORS.text_muted}")
        start_btn.set_visibility(True)
        stop_btn.set_visibility(False)
        if utp_monitoring["timer"] is not None:
            utp_monitoring["timer"].deactivate()

    async def _poll_utp():
        if utp_monitoring["active"]:
            await load_utp_results()

    # =================================================================
    # Page layout
    # =================================================================

    # --- Port selector + link summary strip ---
    with (
        ui.card()
        .classes("w-full p-4")
        .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
    ):
        with ui.row().classes("items-end gap-4 w-full"):
            port_select = ui.select(
                options={},
                label="Active Port",
                on_change=on_port_changed,
            ).classes("w-72")
            lanes_input = ui.number("Num Lanes", value=16, min=1, max=16, step=1).classes("w-28")

        link_summary_container = ui.row().classes("items-center gap-3 mt-2")

        @ui.refreshable
        def refresh_link_summary():
            link_summary_container.clear()
            with link_summary_container:
                pn = _selected_port()
                port_info = None
                for p in ports_data:
                    if p.get("port_number") == pn:
                        port_info = p
                        break
                if port_info is None:
                    ui.label("No port data").style(f"color: {COLORS.text_muted}")
                    return
                link_status_badge(port_info.get("is_link_up", False))
                speed_badge(port_info.get("link_speed", "Unknown"))
                port_role_badge(port_info.get("role", "unknown"))
                width = port_info.get("link_width", 0)
                lbl = ui.label(f"x{width}").classes("px-2 py-1 rounded text-xs")
                lbl.style(
                    f"background: {COLORS.bg_secondary}; "
                    f"color: {COLORS.text_primary}; "
                    f"border: 1px solid {COLORS.border}"
                )

        refresh_link_summary()

    # --- Tabs ---
    with ui.tabs().classes("w-full") as tabs:
        link_eq_tab = ui.tab("Link & EQ")
        utp_tab = ui.tab("UTP Testing")
        registers_tab = ui.tab("Registers")

    with ui.tab_panels(tabs, value=link_eq_tab).classes("w-full"):
        # =============================================================
        # Tab 1: Link & EQ
        # =============================================================
        with ui.tab_panel(link_eq_tab):
            # --- Supported Speeds ---
            with (
                ui.card()
                .classes("w-full p-4")
                .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
            ):
                with ui.row().classes("items-center gap-4 mb-2"):
                    ui.label("Supported Link Speeds").classes("text-h6").style(
                        f"color: {COLORS.text_primary}"
                    )
                    ui.button("Refresh", on_click=load_speeds).props("flat color=primary")

                speeds_container = ui.column().classes("w-full")

                @ui.refreshable
                def refresh_speeds():
                    speeds_container.clear()
                    with speeds_container:
                        if not speeds_data:
                            ui.label("Select a port to load.").style(f"color: {COLORS.text_muted}")
                            return
                        gen_names = [
                            ("gen1", "Gen1 (2.5 GT/s)"),
                            ("gen2", "Gen2 (5.0 GT/s)"),
                            ("gen3", "Gen3 (8.0 GT/s)"),
                            ("gen4", "Gen4 (16.0 GT/s)"),
                            ("gen5", "Gen5 (32.0 GT/s)"),
                            ("gen6", "Gen6 (64.0 GT/s)"),
                        ]
                        with ui.row().classes("gap-3 flex-wrap"):
                            for key, label in gen_names:
                                supported = speeds_data.get(key, False)
                                color = COLORS.green if supported else COLORS.text_muted
                                icon = "check_circle" if supported else "cancel"
                                with ui.row().classes("items-center gap-1"):
                                    ui.icon(icon).classes("text-sm").style(f"color: {color}")
                                    ui.label(label).style(f"color: {color}; font-size: 13px")

                refresh_speeds()

            # --- EQ Status (3 columns: 16GT, 32GT, 64GT) ---
            with (
                ui.card()
                .classes("w-full p-4")
                .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
            ):
                with ui.row().classes("items-center gap-4 mb-2"):
                    ui.label("Equalization Status").classes("text-h6").style(
                        f"color: {COLORS.text_primary}"
                    )
                    ui.button("Refresh", on_click=load_eq_status).props("flat color=primary")

                eq_container = ui.column().classes("w-full")

                @ui.refreshable
                def refresh_eq_status():
                    eq_container.clear()
                    with eq_container:
                        eq16 = eq_data.get("eq_16gt")
                        eq32 = eq_data.get("eq_32gt")
                        eq64 = eq_data.get("eq_64gt")
                        if eq16 is None and eq32 is None and eq64 is None:
                            ui.label("Select a port to load.").style(f"color: {COLORS.text_muted}")
                            return

                        with ui.row().classes("w-full gap-4"):
                            # 16 GT/s column
                            with ui.column().classes("flex-1"):
                                ui.label("16 GT/s").style(
                                    f"color: {COLORS.text_primary}; font-weight: bold"
                                )
                                if eq16:
                                    _eq_flag("Complete", eq16.get("complete", False))
                                    _eq_flag("Phase 1", eq16.get("phase1_success", False))
                                    _eq_flag("Phase 2", eq16.get("phase2_success", False))
                                    _eq_flag("Phase 3", eq16.get("phase3_success", False))
                                    _eq_flag("Link EQ Req", eq16.get("link_eq_request", False))
                                    raw = eq16.get("raw_value") or 0
                                    ui.label(f"Raw: 0x{raw:08X}").style(
                                        f"color: {COLORS.text_muted}; "
                                        f"font-family: monospace; font-size: 12px"
                                    )
                                else:
                                    ui.label("Not available").style(f"color: {COLORS.text_muted}")

                            # 32 GT/s column
                            with ui.column().classes("flex-1"):
                                ui.label("32 GT/s").style(
                                    f"color: {COLORS.text_primary}; font-weight: bold"
                                )
                                if eq32:
                                    _eq_flag("Complete", eq32.get("complete", False))
                                    _eq_flag("Phase 1", eq32.get("phase1_success", False))
                                    _eq_flag("Phase 2", eq32.get("phase2_success", False))
                                    _eq_flag("Phase 3", eq32.get("phase3_success", False))
                                    _eq_flag(
                                        "Link EQ Req",
                                        eq32.get("link_eq_request", False),
                                    )
                                    _eq_flag(
                                        "Modified TS",
                                        eq32.get("modified_ts_received", False),
                                    )
                                    _eq_flag(
                                        "RX Margin Cap",
                                        eq32.get("rx_lane_margin_capable", False),
                                    )
                                    _eq_flag(
                                        "No EQ Needed",
                                        eq32.get("no_eq_needed", False),
                                    )
                                    raw_s = eq32.get("raw_status") or 0
                                    raw_c = eq32.get("raw_capabilities") or 0
                                    ui.label(f"Sts: 0x{raw_s:08X} | Cap: 0x{raw_c:08X}").style(
                                        f"color: {COLORS.text_muted}; "
                                        f"font-family: monospace; font-size: 12px"
                                    )
                                else:
                                    ui.label("Not available").style(f"color: {COLORS.text_muted}")

                            # 64 GT/s column
                            with ui.column().classes("flex-1"):
                                ui.label("64 GT/s").style(
                                    f"color: {COLORS.text_primary}; font-weight: bold"
                                )
                                if eq64:
                                    _eq_flag("Complete", eq64.get("complete", False))
                                    _eq_flag("Phase 1", eq64.get("phase1_success", False))
                                    _eq_flag("Phase 2", eq64.get("phase2_success", False))
                                    _eq_flag("Phase 3", eq64.get("phase3_success", False))
                                    _eq_flag(
                                        "Link EQ Req",
                                        eq64.get("link_eq_request", False),
                                    )
                                    _eq_flag(
                                        "FLIT Mode",
                                        eq64.get("flit_mode_supported", False),
                                    )
                                    _eq_flag(
                                        "No EQ Needed",
                                        eq64.get("no_eq_needed", False),
                                    )
                                    raw_s = eq64.get("raw_status") or 0
                                    raw_c = eq64.get("raw_capabilities") or 0
                                    ui.label(f"Sts: 0x{raw_s:08X} | Cap: 0x{raw_c:08X}").style(
                                        f"color: {COLORS.text_muted}; "
                                        f"font-family: monospace; font-size: 12px"
                                    )
                                else:
                                    ui.label("Not available").style(f"color: {COLORS.text_muted}")

                refresh_eq_status()

            # --- Lane EQ Settings ---
            with (
                ui.card()
                .classes("w-full p-4")
                .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
            ):
                with ui.row().classes("items-center gap-4 mb-2"):
                    ui.label("Lane Equalization Settings (16 GT/s)").classes("text-h6").style(
                        f"color: {COLORS.text_primary}"
                    )
                    ui.button("Refresh", on_click=load_lane_eq).props("flat color=primary")

                lane_eq_container = ui.column().classes("w-full")

                @ui.refreshable
                def refresh_lane_eq():
                    lane_eq_container.clear()
                    with lane_eq_container:
                        lanes = lane_eq_data.get("lanes", [])
                        if not lanes:
                            ui.label("Select a port to load.").style(f"color: {COLORS.text_muted}")
                            return
                        rows = [
                            {
                                "lane": ln["lane"],
                                "ds_tx": f"P{ln['downstream_tx_preset']}",
                                "ds_rx": str(ln["downstream_rx_hint"]),
                                "us_tx": f"P{ln['upstream_tx_preset']}",
                                "us_rx": str(ln["upstream_rx_hint"]),
                            }
                            for ln in lanes
                        ]
                        columns = [
                            {
                                "name": "lane",
                                "label": "Lane",
                                "field": "lane",
                                "align": "center",
                            },
                            {
                                "name": "ds_tx",
                                "label": "DS TX Preset",
                                "field": "ds_tx",
                                "align": "center",
                            },
                            {
                                "name": "ds_rx",
                                "label": "DS RX Hint",
                                "field": "ds_rx",
                                "align": "center",
                            },
                            {
                                "name": "us_tx",
                                "label": "US TX Preset",
                                "field": "us_tx",
                                "align": "center",
                            },
                            {
                                "name": "us_rx",
                                "label": "US RX Hint",
                                "field": "us_rx",
                                "align": "center",
                            },
                        ]
                        ui.table(columns=columns, rows=rows, row_key="lane").classes("w-full")

                refresh_lane_eq()

        # =============================================================
        # Tab 2: UTP Testing
        # =============================================================
        with ui.tab_panel(utp_tab):
            # Step indicator
            utp_step_label = ui.label(
                "Configure a test pattern below, then click Prepare Test."
            ).style(f"color: {COLORS.text_muted}; font-style: italic; margin-bottom: 8px")

            # Configure section
            with (
                ui.card()
                .classes("w-full p-4")
                .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
            ):
                ui.label("Configure").classes("text-h6").style(f"color: {COLORS.text_primary}")
                with ui.row().classes("items-end gap-4 mt-2"):
                    preset_opts = {
                        "prbs7": "PRBS-7",
                        "prbs15": "PRBS-15",
                        "prbs31": "PRBS-31",
                        "alternating": "Alternating (AA/55)",
                        "walking_ones": "Walking Ones",
                        "zeros": "All Zeros",
                        "ones": "All Ones",
                    }
                    utp_preset_select = ui.select(
                        preset_opts, label="Pattern", value="prbs7"
                    ).classes("w-44")
                    rate_opts = {
                        "0": "2.5 GT/s (Gen1)",
                        "1": "5.0 GT/s (Gen2)",
                        "2": "8.0 GT/s (Gen3)",
                        "3": "16.0 GT/s (Gen4)",
                        "4": "32.0 GT/s (Gen5)",
                        "5": "64.0 GT/s (Gen6)",
                    }
                    utp_rate_select = ui.select(rate_opts, label="Rate", value="2").classes("w-40")
                    utp_port_select = ui.number(
                        "Port Select", value=0, min=0, max=15, step=1
                    ).classes("w-28")
                    ui.button("Prepare Test", on_click=prepare_utp).props("flat color=warning")

            # Results section
            with (
                ui.card()
                .classes("w-full p-4 mt-2")
                .style(f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}")
            ):
                with ui.row().classes("items-center gap-4 mb-2"):
                    ui.label("SerDes Results").classes("text-h6").style(
                        f"color: {COLORS.text_primary}"
                    )
                    start_btn = ui.button("Start Monitoring", on_click=start_monitoring).props(
                        "flat color=positive"
                    )
                    stop_btn = ui.button("Stop", on_click=stop_monitoring).props(
                        "flat color=negative"
                    )
                    stop_btn.set_visibility(False)
                    ui.button("Refresh", on_click=load_utp_results).props("flat color=primary")
                    ui.button("Clear All Errors", on_click=clear_all_serdes).props(
                        "flat color=negative"
                    )

                utp_serdes_container = ui.column().classes("w-full")

                @ui.refreshable
                def refresh_utp_serdes():
                    utp_serdes_container.clear()
                    with utp_serdes_container:
                        results = utp_results_data.get("results", [])
                        lanes = serdes_data.get("lanes", [])
                        if results:
                            _render_utp_results_table(results)
                        elif lanes:
                            _render_serdes_table(lanes)
                        else:
                            ui.label("Prepare a test and start monitoring.").style(
                                f"color: {COLORS.text_muted}"
                            )

                refresh_utp_serdes()

            # Auto-poll timer (created deactivated)
            poll_timer = ui.timer(1.5, _poll_utp, active=False)
            utp_monitoring["timer"] = poll_timer

        # =============================================================
        # Tab 3: Registers
        # =============================================================
        with ui.tab_panel(registers_tab):
            # --- Port Control (0x3208) ---
            with (
                ui.expansion("Port Control (0x3208)", icon="settings")
                .classes("w-full")
                .style(f"color: {COLORS.text_primary}") as port_ctrl_exp
            ):
                with ui.row().classes("items-center gap-4 mb-2"):
                    ui.button("Refresh", on_click=load_port_control).props("flat color=primary")

                port_ctrl_container = ui.column().classes("w-full")

                @ui.refreshable
                def refresh_port_control():
                    port_ctrl_container.clear()
                    with port_ctrl_container:
                        if not port_ctrl_data:
                            ui.label("Click Refresh to load.").style(f"color: {COLORS.text_muted}")
                            return
                        fields = [
                            ("disable_port", "Disable Port"),
                            ("port_quiet", "Port Quiet"),
                            ("lock_down_fe_preset", "Lock FE Preset"),
                            ("test_pattern_rate", "Test Pattern Rate"),
                            ("bypass_utp_alignment", "Bypass UTP Align"),
                            ("port_select", "Port Select"),
                        ]
                        rate_names = {
                            0: "2.5 GT/s",
                            1: "5.0 GT/s",
                            2: "8.0 GT/s",
                            3: "16.0 GT/s",
                            4: "32.0 GT/s",
                            5: "64.0 GT/s",
                        }
                        with ui.grid(columns=2).classes("gap-2"):
                            for key, label in fields:
                                ui.label(label).style(f"color: {COLORS.text_secondary}")
                                val = port_ctrl_data.get(key, "")
                                if key == "test_pattern_rate":
                                    val = rate_names.get(val, str(val))
                                elif key == "bypass_utp_alignment":
                                    val = f"0x{val:04X}" if isinstance(val, int) else str(val)
                                elif isinstance(val, bool):
                                    color = COLORS.green if val else COLORS.text_muted
                                    ui.label(str(val)).style(f"color: {color}")
                                    continue
                                ui.label(str(val)).style(f"color: {COLORS.text_primary}")

                refresh_port_control()

            async def _on_port_ctrl_open():
                if not port_ctrl_data:
                    await load_port_control()

            port_ctrl_exp.on("after-show", _on_port_ctrl_open)

            # --- PHY Command/Status (0x321C) ---
            with (
                ui.expansion("PHY Cmd/Status (0x321C)", icon="terminal")
                .classes("w-full")
                .style(f"color: {COLORS.text_primary}") as cmd_status_exp
            ):
                with ui.row().classes("items-center gap-4 mb-2"):
                    ui.button("Refresh", on_click=load_cmd_status).props("flat color=primary")

                cmd_status_container = ui.column().classes("w-full")

                @ui.refreshable
                def refresh_cmd_status():
                    cmd_status_container.clear()
                    with cmd_status_container:
                        if not cmd_status_data:
                            ui.label("Click Refresh to load.").style(f"color: {COLORS.text_muted}")
                            return
                        fields = [
                            ("num_ports", "Num Ports"),
                            ("upstream_crosslink_enable", "US Crosslink EN"),
                            ("downstream_crosslink_enable", "DS Crosslink EN"),
                            ("lane_reversal_disable", "Lane Rev Disable"),
                            ("ltssm_wdt_disable", "LTSSM WDT Disable"),
                            ("ltssm_wdt_port_select", "WDT Port Select"),
                            ("utp_kcode_flags", "UTP K-Code Flags"),
                        ]
                        with ui.grid(columns=2).classes("gap-2"):
                            for key, label in fields:
                                ui.label(label).style(f"color: {COLORS.text_secondary}")
                                val = cmd_status_data.get(key, "")
                                if key == "utp_kcode_flags":
                                    val = f"0x{val:04X}" if isinstance(val, int) else str(val)
                                elif isinstance(val, bool):
                                    color = COLORS.green if val else COLORS.text_muted
                                    ui.label(str(val)).style(f"color: {color}")
                                    continue
                                ui.label(str(val)).style(f"color: {COLORS.text_primary}")

                refresh_cmd_status()

            async def _on_cmd_status_open():
                if not cmd_status_data:
                    await load_cmd_status()

            cmd_status_exp.on("after-show", _on_cmd_status_open)

    # Load active ports on page init
    ui.timer(0.1, load_ports, once=True)


# =============================================================================
# Shared table renderers
# =============================================================================


def _render_utp_results_table(results: list[dict]) -> None:
    """Render the UTP results as a table with summary."""
    rows = []
    for r in results:
        synced = r.get("synced", False)
        errs = r.get("error_count", 0)
        if not synced:
            status_str = "NO SYNC"
        elif errs == 0:
            status_str = "PASS"
        else:
            status_str = f"FAIL ({errs})"
        rows.append(
            {
                "lane": r["lane"],
                "status": status_str,
                "errors": errs,
                "expected": (
                    f"0x{r['expected_on_error']:02X}"
                    if r.get("expected_on_error") is not None
                    else "-"
                ),
                "actual": (
                    f"0x{r['actual_on_error']:02X}" if r.get("actual_on_error") is not None else "-"
                ),
            }
        )
    columns = [
        {"name": "lane", "label": "Lane", "field": "lane", "align": "center"},
        {"name": "status", "label": "Status", "field": "status", "align": "center"},
        {"name": "errors", "label": "Errors", "field": "errors", "align": "center"},
        {"name": "expected", "label": "Expected", "field": "expected", "align": "center"},
        {"name": "actual", "label": "Actual", "field": "actual", "align": "center"},
    ]
    ui.table(columns=columns, rows=rows, row_key="lane").classes("w-full")

    total = len(results)
    passed = sum(1 for r in results if r.get("synced") and r.get("error_count", 0) == 0)
    failed = sum(1 for r in results if r.get("synced") and r.get("error_count", 0) > 0)
    no_sync = total - passed - failed
    parts = [f"{passed}/{total} passed"]
    if failed:
        parts.append(f"{failed} failed")
    if no_sync:
        parts.append(f"{no_sync} no sync")
    summary_color = COLORS.green if failed == 0 and no_sync == 0 else COLORS.red
    ui.label(", ".join(parts)).style(f"color: {summary_color}; font-weight: bold; margin-top: 8px")


def _render_serdes_table(lanes: list[dict]) -> None:
    """Render raw SerDes diagnostic data as a table."""
    rows = []
    for ln in lanes:
        synced = ln.get("synced", False)
        errs = ln.get("error_count", 0)
        if not synced:
            status_str = "NO SYNC"
        elif errs == 0:
            status_str = "PASS"
        else:
            status_str = f"FAIL ({errs})"
        rows.append(
            {
                "lane": ln["lane"],
                "status": status_str,
                "errors": errs,
                "expected": f"0x{ln.get('expected_data', 0):02X}",
                "actual": f"0x{ln.get('actual_data', 0):02X}",
            }
        )
    columns = [
        {"name": "lane", "label": "Lane", "field": "lane", "align": "center"},
        {"name": "status", "label": "Status", "field": "status", "align": "center"},
        {"name": "errors", "label": "Errors", "field": "errors", "align": "center"},
        {"name": "expected", "label": "Expected", "field": "expected", "align": "center"},
        {"name": "actual", "label": "Actual", "field": "actual", "align": "center"},
    ]
    ui.table(columns=columns, rows=rows, row_key="lane").classes("w-full")


def _eq_flag(label: str, value: bool) -> None:
    """Render an EQ status flag with colored indicator."""
    color = COLORS.green if value else COLORS.text_muted
    icon = "check_circle" if value else "cancel"
    with ui.row().classes("items-center gap-1"):
        ui.icon(icon).classes("text-sm").style(f"color: {color}")
        ui.label(label).style(f"color: {color}; font-size: 13px")
