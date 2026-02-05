"""PHY layer monitoring and diagnostics page."""

from __future__ import annotations

import asyncio

from nicegui import ui

from calypso.ui.theme import COLORS, CSS


def phy_monitor_page(device_id: str) -> None:
    """Render the PHY monitoring page."""
    ui.add_head_html(f"<style>{CSS}</style>")

    speeds_data: dict = {}
    eq_data: dict = {"eq_16gt": None, "eq_32gt": None}
    lane_eq_data: dict = {"lanes": []}
    serdes_data: dict = {"lanes": []}
    port_ctrl_data: dict = {}
    cmd_status_data: dict = {}
    utp_results_data: dict = {"results": []}
    margining_data: dict = {}

    # --- Data loaders ---

    async def load_speeds():
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/phy/speeds")).json()'
            )
            speeds_data.clear()
            speeds_data.update(resp)
            refresh_speeds()
        except Exception as e:
            ui.notify(f"Error loading speeds: {e}", type="negative")

    async def load_eq_status():
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/phy/eq-status")).json()'
            )
            eq_data.clear()
            eq_data.update(resp)
            refresh_eq_status()
        except Exception as e:
            ui.notify(f"Error loading EQ status: {e}", type="negative")

    async def load_lane_eq():
        pn = int(port_input.value or 0)
        nl = int(lanes_input.value or 16)
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/phy/lane-eq?port_number={pn}&num_lanes={nl}")).json()'
            )
            lane_eq_data["lanes"] = resp.get("lanes", [])
            refresh_lane_eq()
        except Exception as e:
            ui.notify(f"Error loading lane EQ: {e}", type="negative")

    async def load_serdes():
        pn = int(port_input.value or 0)
        nl = int(lanes_input.value or 16)
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/phy/serdes-diag?port_number={pn}&num_lanes={nl}")).json()'
            )
            serdes_data["lanes"] = resp.get("lanes", [])
            refresh_serdes()
        except Exception as e:
            ui.notify(f"Error loading SerDes diag: {e}", type="negative")

    async def clear_serdes_lane():
        pn = int(port_input.value or 0)
        lane = int(clear_lane_input.value or 0)
        try:
            await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/phy/serdes-diag/clear?port_number={pn}", '
                f'{{method:"POST",headers:{{"Content-Type":"application/json"}},'
                f'body:JSON.stringify({{lane:{lane}}})}})).json()'
            )
            ui.notify(f"Lane {lane} errors cleared", type="positive")
            await load_serdes()
        except Exception as e:
            ui.notify(f"Error clearing lane: {e}", type="negative")

    async def load_port_control():
        pn = int(port_input.value or 0)
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/phy/port-control?port_number={pn}")).json()'
            )
            port_ctrl_data.clear()
            port_ctrl_data.update(resp)
            refresh_port_control()
        except Exception as e:
            ui.notify(f"Error loading port control: {e}", type="negative")

    async def load_cmd_status():
        pn = int(port_input.value or 0)
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/phy/cmd-status?port_number={pn}")).json()'
            )
            cmd_status_data.clear()
            cmd_status_data.update(resp)
            refresh_cmd_status()
        except Exception as e:
            ui.notify(f"Error loading PHY cmd/status: {e}", type="negative")

    async def load_margining():
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/phy/lane-margining")).json()'
            )
            margining_data.clear()
            margining_data.update(resp)
            refresh_margining()
        except Exception as e:
            ui.notify(f"Error loading margining: {e}", type="negative")

    async def prepare_utp():
        pn = int(port_input.value or 0)
        preset = utp_preset_select.value or "prbs7"
        rate = int(utp_rate_select.value or 2)
        ps = int(utp_port_select.value or 0)
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/phy/utp/prepare?port_number={pn}", '
                f'{{method:"POST",headers:{{"Content-Type":"application/json"}},'
                f'body:JSON.stringify({{preset:"{preset}",rate:{rate},port_select:{ps}}})}})).json()'
            )
            ui.notify(f"UTP prepared: {resp.get('pattern', '')} @ {resp.get('rate', '')}", type="positive")
        except Exception as e:
            ui.notify(f"Error preparing UTP: {e}", type="negative")

    async def load_utp_results():
        pn = int(port_input.value or 0)
        nl = int(lanes_input.value or 16)
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}/phy/utp/results?port_number={pn}&num_lanes={nl}")).json()'
            )
            utp_results_data["results"] = resp.get("results", [])
            refresh_utp_results()
        except Exception as e:
            ui.notify(f"Error loading UTP results: {e}", type="negative")

    async def load_all():
        """Load all status sections concurrently."""
        await asyncio.gather(
            load_speeds(),
            load_eq_status(),
            load_lane_eq(),
            load_serdes(),
            load_port_control(),
            load_cmd_status(),
            load_margining(),
        )

    # --- Page layout ---

    with ui.column().classes("w-full p-4 gap-4"):
        ui.label("PHY Monitor").classes("text-h5").style(
            f"color: {COLORS['text_primary']}"
        )
        ui.label(f"Device: {device_id}").style(f"color: {COLORS['text_secondary']}")

        # Global controls
        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS['bg_secondary']}; border: 1px solid {COLORS['border']}"
        ):
            with ui.row().classes("items-end gap-4"):
                port_input = ui.number(
                    "Port Number", value=0, min=0, max=143, step=1
                ).classes("w-28")
                lanes_input = ui.number(
                    "Num Lanes", value=16, min=1, max=16, step=1
                ).classes("w-28")
                ui.button("Refresh All", on_click=load_all).props("flat color=primary")

        # --- Supported Speeds ---
        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS['bg_secondary']}; border: 1px solid {COLORS['border']}"
        ):
            with ui.row().classes("items-center gap-4 mb-2"):
                ui.label("Supported Link Speeds").classes("text-h6").style(
                    f"color: {COLORS['text_primary']}"
                )
                ui.button("Refresh", on_click=load_speeds).props("flat color=primary")

            speeds_container = ui.column().classes("w-full")

            @ui.refreshable
            def refresh_speeds():
                speeds_container.clear()
                with speeds_container:
                    if not speeds_data:
                        ui.label("Click Refresh to load.").style(
                            f"color: {COLORS['text_muted']}"
                        )
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
                            color = COLORS["accent_green"] if supported else COLORS["text_muted"]
                            icon = "check_circle" if supported else "cancel"
                            with ui.row().classes("items-center gap-1"):
                                ui.icon(icon).classes("text-sm").style(f"color: {color}")
                                ui.label(label).style(
                                    f"color: {color}; font-size: 13px"
                                )

            refresh_speeds()

        # --- EQ Status ---
        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS['bg_secondary']}; border: 1px solid {COLORS['border']}"
        ):
            with ui.row().classes("items-center gap-4 mb-2"):
                ui.label("Equalization Status").classes("text-h6").style(
                    f"color: {COLORS['text_primary']}"
                )
                ui.button("Refresh", on_click=load_eq_status).props("flat color=primary")

            eq_container = ui.column().classes("w-full")

            @ui.refreshable
            def refresh_eq_status():
                eq_container.clear()
                with eq_container:
                    eq16 = eq_data.get("eq_16gt")
                    eq32 = eq_data.get("eq_32gt")
                    if eq16 is None and eq32 is None:
                        ui.label("Click Refresh to load.").style(
                            f"color: {COLORS['text_muted']}"
                        )
                        return

                    with ui.row().classes("w-full gap-4"):
                        # 16 GT/s column
                        with ui.column().classes("flex-1"):
                            ui.label("16 GT/s EQ Status").style(
                                f"color: {COLORS['text_primary']}; font-weight: bold"
                            )
                            if eq16:
                                _eq_flag("Complete", eq16.get("complete", False))
                                _eq_flag("Phase 1 Success", eq16.get("phase1_success", False))
                                _eq_flag("Phase 2 Success", eq16.get("phase2_success", False))
                                _eq_flag("Phase 3 Success", eq16.get("phase3_success", False))
                                _eq_flag("Link EQ Request", eq16.get("link_eq_request", False))
                                raw = eq16.get("raw_value") or 0
                                ui.label(f"Raw: 0x{raw:08X}").style(
                                    f"color: {COLORS['text_muted']}; font-family: monospace; font-size: 12px"
                                )
                            else:
                                ui.label("Not available").style(
                                    f"color: {COLORS['text_muted']}"
                                )

                        # 32 GT/s column
                        with ui.column().classes("flex-1"):
                            ui.label("32 GT/s EQ Status").style(
                                f"color: {COLORS['text_primary']}; font-weight: bold"
                            )
                            if eq32:
                                _eq_flag("Complete", eq32.get("complete", False))
                                _eq_flag("Phase 1 Success", eq32.get("phase1_success", False))
                                _eq_flag("Phase 2 Success", eq32.get("phase2_success", False))
                                _eq_flag("Phase 3 Success", eq32.get("phase3_success", False))
                                _eq_flag("Link EQ Request", eq32.get("link_eq_request", False))
                                _eq_flag("Modified TS Received", eq32.get("modified_ts_received", False))
                                _eq_flag("RX Lane Margin Capable", eq32.get("rx_lane_margin_capable", False))
                                _eq_flag("No EQ Needed", eq32.get("no_eq_needed", False))
                                raw_s = eq32.get("raw_status") or 0
                                raw_c = eq32.get("raw_capabilities") or 0
                                ui.label(
                                    f"Status: 0x{raw_s:08X} | Caps: 0x{raw_c:08X}"
                                ).style(
                                    f"color: {COLORS['text_muted']}; font-family: monospace; font-size: 12px"
                                )
                            else:
                                ui.label("Not available").style(
                                    f"color: {COLORS['text_muted']}"
                                )

            refresh_eq_status()

        # --- Lane EQ Settings ---
        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS['bg_secondary']}; border: 1px solid {COLORS['border']}"
        ):
            with ui.row().classes("items-center gap-4 mb-2"):
                ui.label("Lane Equalization Settings (16 GT/s)").classes("text-h6").style(
                    f"color: {COLORS['text_primary']}"
                )
                ui.button("Refresh", on_click=load_lane_eq).props("flat color=primary")

            lane_eq_container = ui.column().classes("w-full")

            @ui.refreshable
            def refresh_lane_eq():
                lane_eq_container.clear()
                with lane_eq_container:
                    lanes = lane_eq_data.get("lanes", [])
                    if not lanes:
                        ui.label("Click Refresh to load.").style(
                            f"color: {COLORS['text_muted']}"
                        )
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
                        {"name": "lane", "label": "Lane", "field": "lane", "align": "center"},
                        {"name": "ds_tx", "label": "DS TX Preset", "field": "ds_tx", "align": "center"},
                        {"name": "ds_rx", "label": "DS RX Hint", "field": "ds_rx", "align": "center"},
                        {"name": "us_tx", "label": "US TX Preset", "field": "us_tx", "align": "center"},
                        {"name": "us_rx", "label": "US RX Hint", "field": "us_rx", "align": "center"},
                    ]
                    ui.table(columns=columns, rows=rows, row_key="lane").classes("w-full")

            refresh_lane_eq()

        # --- SerDes Diagnostics ---
        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS['bg_secondary']}; border: 1px solid {COLORS['border']}"
        ):
            with ui.row().classes("items-center gap-4 mb-2"):
                ui.label("SerDes Diagnostics").classes("text-h6").style(
                    f"color: {COLORS['text_primary']}"
                )
                ui.button("Refresh", on_click=load_serdes).props("flat color=primary")

            with ui.row().classes("items-end gap-4 mb-2"):
                clear_lane_input = ui.number("Lane to Clear", value=0, min=0, max=15, step=1).classes("w-28")
                ui.button("Clear Errors", on_click=clear_serdes_lane).props("flat color=negative")

            serdes_container = ui.column().classes("w-full")

            @ui.refreshable
            def refresh_serdes():
                serdes_container.clear()
                with serdes_container:
                    lanes = serdes_data.get("lanes", [])
                    if not lanes:
                        ui.label("Click Refresh to load.").style(
                            f"color: {COLORS['text_muted']}"
                        )
                        return
                    rows = []
                    for ln in lanes:
                        synced = ln.get("synced", False)
                        errs = ln.get("error_count", 0)
                        status_str = "SYNC" if synced else "NO SYNC"
                        if synced and errs == 0:
                            status_str = "PASS"
                        elif synced and errs > 0:
                            status_str = f"FAIL ({errs})"
                        rows.append({
                            "lane": ln["lane"],
                            "synced": status_str,
                            "errors": errs,
                            "expected": f"0x{ln.get('expected_data', 0):02X}",
                            "actual": f"0x{ln.get('actual_data', 0):02X}",
                        })
                    columns = [
                        {"name": "lane", "label": "Lane", "field": "lane", "align": "center"},
                        {"name": "synced", "label": "Status", "field": "synced", "align": "center"},
                        {"name": "errors", "label": "Errors", "field": "errors", "align": "center"},
                        {"name": "expected", "label": "Expected", "field": "expected", "align": "center"},
                        {"name": "actual", "label": "Actual", "field": "actual", "align": "center"},
                    ]
                    ui.table(columns=columns, rows=rows, row_key="lane").classes("w-full")

            refresh_serdes()

        # --- Port Control & PHY Cmd/Status side by side ---
        with ui.row().classes("w-full gap-4"):
            # Port Control
            with ui.card().classes("flex-1 p-4").style(
                f"background: {COLORS['bg_secondary']}; border: 1px solid {COLORS['border']}"
            ):
                with ui.row().classes("items-center gap-4 mb-2"):
                    ui.label("Port Control (0x3208)").classes("text-h6").style(
                        f"color: {COLORS['text_primary']}"
                    )
                    ui.button("Refresh", on_click=load_port_control).props("flat color=primary")

                port_ctrl_container = ui.column().classes("w-full")

                @ui.refreshable
                def refresh_port_control():
                    port_ctrl_container.clear()
                    with port_ctrl_container:
                        if not port_ctrl_data:
                            ui.label("Click Refresh to load.").style(
                                f"color: {COLORS['text_muted']}"
                            )
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
                            0: "2.5 GT/s", 1: "5.0 GT/s", 2: "8.0 GT/s",
                            3: "16.0 GT/s", 4: "32.0 GT/s", 5: "64.0 GT/s",
                        }
                        with ui.grid(columns=2).classes("gap-2"):
                            for key, label in fields:
                                ui.label(label).style(f"color: {COLORS['text_secondary']}")
                                val = port_ctrl_data.get(key, "")
                                if key == "test_pattern_rate":
                                    val = rate_names.get(val, str(val))
                                elif key == "bypass_utp_alignment":
                                    val = f"0x{val:04X}" if isinstance(val, int) else str(val)
                                elif isinstance(val, bool):
                                    color = COLORS["accent_green"] if val else COLORS["text_muted"]
                                    ui.label(str(val)).style(f"color: {color}")
                                    continue
                                ui.label(str(val)).style(f"color: {COLORS['text_primary']}")

                refresh_port_control()

            # PHY Command/Status
            with ui.card().classes("flex-1 p-4").style(
                f"background: {COLORS['bg_secondary']}; border: 1px solid {COLORS['border']}"
            ):
                with ui.row().classes("items-center gap-4 mb-2"):
                    ui.label("PHY Cmd/Status (0x321C)").classes("text-h6").style(
                        f"color: {COLORS['text_primary']}"
                    )
                    ui.button("Refresh", on_click=load_cmd_status).props("flat color=primary")

                cmd_status_container = ui.column().classes("w-full")

                @ui.refreshable
                def refresh_cmd_status():
                    cmd_status_container.clear()
                    with cmd_status_container:
                        if not cmd_status_data:
                            ui.label("Click Refresh to load.").style(
                                f"color: {COLORS['text_muted']}"
                            )
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
                                ui.label(label).style(f"color: {COLORS['text_secondary']}")
                                val = cmd_status_data.get(key, "")
                                if key == "utp_kcode_flags":
                                    val = f"0x{val:04X}" if isinstance(val, int) else str(val)
                                elif isinstance(val, bool):
                                    color = COLORS["accent_green"] if val else COLORS["text_muted"]
                                    ui.label(str(val)).style(f"color: {color}")
                                    continue
                                ui.label(str(val)).style(f"color: {COLORS['text_primary']}")

                refresh_cmd_status()

        # --- UTP Testing ---
        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS['bg_secondary']}; border: 1px solid {COLORS['border']}"
        ):
            with ui.row().classes("items-center gap-4 mb-2"):
                ui.label("User Test Pattern (UTP)").classes("text-h6").style(
                    f"color: {COLORS['text_primary']}"
                )

            with ui.row().classes("items-end gap-4 mb-3"):
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
                utp_rate_select = ui.select(
                    rate_opts, label="Rate", value="2"
                ).classes("w-40")
                utp_port_select = ui.number(
                    "Port Select", value=0, min=0, max=15, step=1
                ).classes("w-28")
                ui.button("Prepare Test", on_click=prepare_utp).props("flat color=warning")
                ui.button("Read Results", on_click=load_utp_results).props("flat color=primary")

            utp_container = ui.column().classes("w-full")

            @ui.refreshable
            def refresh_utp_results():
                utp_container.clear()
                with utp_container:
                    results = utp_results_data.get("results", [])
                    if not results:
                        ui.label("Prepare a test and read results.").style(
                            f"color: {COLORS['text_muted']}"
                        )
                        return
                    rows = []
                    for r in results:
                        passed = r.get("passed", False)
                        rows.append({
                            "lane": r["lane"],
                            "synced": "Yes" if r.get("synced", False) else "No",
                            "errors": r.get("error_count", 0),
                            "result": r.get("error_rate", ""),
                            "expected": (
                                f"0x{r['expected_on_error']:02X}"
                                if r.get("expected_on_error") is not None
                                else "-"
                            ),
                            "actual": (
                                f"0x{r['actual_on_error']:02X}"
                                if r.get("actual_on_error") is not None
                                else "-"
                            ),
                            "_passed": passed,
                        })
                    columns = [
                        {"name": "lane", "label": "Lane", "field": "lane", "align": "center"},
                        {"name": "synced", "label": "Synced", "field": "synced", "align": "center"},
                        {"name": "errors", "label": "Errors", "field": "errors", "align": "center"},
                        {"name": "result", "label": "Result", "field": "result", "align": "center"},
                        {"name": "expected", "label": "Expected", "field": "expected", "align": "center"},
                        {"name": "actual", "label": "Actual", "field": "actual", "align": "center"},
                    ]
                    ui.table(columns=columns, rows=rows, row_key="lane").classes("w-full")

                    # Summary
                    total = len(results)
                    passed_count = sum(1 for r in results if r.get("passed", False))
                    failed_count = total - passed_count
                    summary_color = COLORS["accent_green"] if failed_count == 0 else COLORS["accent_red"]
                    ui.label(
                        f"{passed_count}/{total} lanes passed, {failed_count} failed"
                    ).style(
                        f"color: {summary_color}; font-weight: bold; margin-top: 8px"
                    )

            refresh_utp_results()

        # --- Lane Margining ---
        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS['bg_secondary']}; border: 1px solid {COLORS['border']}"
        ):
            with ui.row().classes("items-center gap-4 mb-2"):
                ui.label("Lane Margining at Receiver").classes("text-h6").style(
                    f"color: {COLORS['text_primary']}"
                )
                ui.button("Check", on_click=load_margining).props("flat color=primary")

            margining_container = ui.column().classes("w-full")

            @ui.refreshable
            def refresh_margining():
                margining_container.clear()
                with margining_container:
                    if not margining_data:
                        ui.label("Click Check to detect capability.").style(
                            f"color: {COLORS['text_muted']}"
                        )
                        return
                    supported = margining_data.get("supported", False)
                    offset = margining_data.get("capability_offset")
                    if supported and offset is not None:
                        ui.label(
                            f"Supported - capability at offset 0x{offset:X}"
                        ).style(f"color: {COLORS['accent_green']}")
                    else:
                        ui.label("Not supported on this device").style(
                            f"color: {COLORS['text_muted']}"
                        )

            refresh_margining()


def _eq_flag(label: str, value: bool) -> None:
    """Render an EQ status flag with colored indicator."""
    color = COLORS["accent_green"] if value else COLORS["text_muted"]
    icon = "check_circle" if value else "cancel"
    with ui.row().classes("items-center gap-1"):
        ui.icon(icon).classes("text-sm").style(f"color: {color}")
        ui.label(label).style(f"color: {color}; font-size: 13px")
