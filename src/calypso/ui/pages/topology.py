"""Switch topology page with connector and station mapping."""

from __future__ import annotations

from nicegui import ui

from calypso.hardware.atlas3 import (
    BoardProfile,
    PROFILE_144,
    get_board_profile,
)
from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS


def _build_connector_ref(profile: BoardProfile) -> list[dict]:
    """Build connector reference table rows from a board profile."""
    return [
        {
            "name": cn_name,
            "type": info.connector_type or "Unknown",
            "station": info.station,
            "lanes": f"{info.lanes[0]}-{info.lanes[1]}",
            "width": f"x{info.lanes[1] - info.lanes[0] + 1}",
            "con_id": info.con_id,
        }
        for cn_name, info in sorted(profile.connector_map.items())
    ]


def _build_station_ref(profile: BoardProfile) -> list[dict]:
    """Build station reference table rows from a board profile."""
    return [
        {
            "stn": stn_id,
            "label": stn.label,
            "ports": f"{stn.port_range[0]}-{stn.port_range[1]}",
            "connector": stn.connector,
        }
        for stn_id, stn in sorted(profile.station_map.items())
    ]


def _build_block_diagram(profile: BoardProfile) -> str:
    """Build an ASCII block diagram for the given board profile."""
    if profile.chip_name == "PEX90080":
        return (
            "  [Host CPU] &lt;--x16--&gt; [Golden Finger / STN1]\n"
            "                               |\n"
            "                      [Atlas3 PEX90080 Switch]\n"
            "                        /      |       \\\n"
            "                  STN0(Int MCIO)  STN2(Ext MCIO)  STN6(Straddle)\n"
            "                  CN2[8:15]x8     CN0[40:47]x8     CN4[96:111]x16\n"
            "                  CN3[0:7]x8      CN1[32:39]x8"
        )
    # Default: PEX90144
    return (
        "  [Host CPU] &lt;--x16--&gt; [Golden Finger / STN2]\n"
        "                               |\n"
        "                      [Atlas3 PEX90144 Switch]\n"
        "                        /      |       \\\n"
        "                  STN0(RC)   STN1(Rsvd)  STN5(Straddle/CN4)\n"
        "                                          x16\n"
        "                        /               \\\n"
        "           STN7(Ext MCIO)            STN8(Int MCIO)\n"
        "           CN1[112:119]x8            CN3[128:135]x8\n"
        "           CN0[120:127]x8            CN2[136:143]x8"
    )


def topology_page(device_id: str) -> None:
    """Render the switch topology page with hardware mapping details."""

    def content():
        topo_data: dict = {}
        active_profile: list[BoardProfile] = [PROFILE_144]

        async def load_topology():
            try:
                resp = await ui.run_javascript(
                    f'return await (await fetch("/api/devices/{device_id}/topology")).json()'
                )
                topo_data.clear()
                topo_data.update(resp)

                chip_id = topo_data.get("chip_id", 0)
                detected = get_board_profile(chip_id)
                if detected.chip_name != active_profile[0].chip_name:
                    active_profile[0] = detected
                    refresh_hw_reference()

                refresh_topology()
            except Exception as e:
                ui.notify(f"Error: {e}", type="negative")

        with ui.row().classes("items-center gap-4"):
            ui.button("Load Topology", on_click=load_topology).props("flat color=primary")

        # Hardware reference (refreshable -- updates when live data reveals board variant)
        ref_container = ui.column().classes("w-full")

        @ui.refreshable
        def refresh_hw_reference():
            ref_container.clear()
            with ref_container:
                _render_hardware_reference(active_profile[0])

        refresh_hw_reference()

        # Live topology data
        topo_container = ui.column().classes("w-full gap-4")

        @ui.refreshable
        def refresh_topology():
            topo_container.clear()
            with topo_container:
                if not topo_data:
                    with ui.card().classes("w-full p-4").style(
                        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
                    ):
                        ui.label("Click Load Topology to discover the switch fabric.").style(
                            f"color: {COLORS.text_muted}"
                        )
                    return

                profile = active_profile[0]
                _render_fabric_summary(topo_data, profile)
                _render_connector_health(topo_data, profile)
                _render_station_cards(topo_data, profile)

        refresh_topology()

    page_layout("Switch Topology", content, device_id=device_id)


def _render_hardware_reference(profile: BoardProfile) -> None:
    """Render the static Atlas3 hardware reference cards."""
    connector_ref = _build_connector_ref(profile)
    station_ref = _build_station_ref(profile)

    with ui.expansion(
        f"Atlas3 Host Card Reference ({profile.chip_name})",
        icon="developer_board",
    ).classes("w-full").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}; "
        f"color: {COLORS.text_primary}"
    ):
        with ui.row().classes("w-full gap-4"):
            # Connector reference table
            with ui.column().classes("flex-1"):
                ui.label("Physical Connectors").style(
                    f"color: {COLORS.text_primary}; font-weight: bold"
                )
                columns = [
                    {"name": "name", "label": "Connector", "field": "name", "align": "left"},
                    {"name": "type", "label": "Type", "field": "type", "align": "left"},
                    {"name": "station", "label": "Station", "field": "station", "align": "center"},
                    {"name": "lanes", "label": "Lanes", "field": "lanes", "align": "center"},
                    {"name": "width", "label": "Width", "field": "width", "align": "center"},
                    {"name": "con_id", "label": "CON ID", "field": "con_id", "align": "center"},
                ]
                ui.table(
                    columns=columns, rows=connector_ref, row_key="name"
                ).classes("w-full")

            # Station reference table
            with ui.column().classes("flex-1"):
                ui.label("Station Layout").style(
                    f"color: {COLORS.text_primary}; font-weight: bold"
                )
                rows = [
                    {
                        "stn": f"STN{s['stn']}",
                        "label": s["label"],
                        "ports": s["ports"],
                        "connector": s["connector"] or "-",
                    }
                    for s in station_ref
                ]
                columns = [
                    {"name": "stn", "label": "Station", "field": "stn", "align": "left"},
                    {"name": "label", "label": "Purpose", "field": "label", "align": "left"},
                    {"name": "ports", "label": "Port Range", "field": "ports", "align": "center"},
                    {"name": "connector", "label": "Connector", "field": "connector", "align": "center"},
                ]
                ui.table(columns=columns, rows=rows, row_key="stn").classes("w-full")

        # Board block diagram
        with ui.column().classes("w-full mt-3"):
            ui.label("Data Path").style(
                f"color: {COLORS.text_primary}; font-weight: bold"
            )
            with ui.element("pre").classes("w-full overflow-x-auto").style(
                f"color: {COLORS.text_secondary}; font-family: 'JetBrains Mono', monospace; "
                f"font-size: 12px; background: {COLORS.bg_primary}; "
                f"padding: 12px; border-radius: 4px; line-height: 1.4"
            ):
                ui.html(_build_block_diagram(profile))


def _render_fabric_summary(topo_data: dict, profile: BoardProfile) -> None:
    """Render the fabric summary card with chip info and port counts."""
    with ui.card().classes("w-full p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    ):
        ui.label("Fabric Summary").classes("text-h6 mb-2").style(
            f"color: {COLORS.text_primary}"
        )

        stations = topo_data.get("stations", [])
        all_ports = []
        for stn in stations:
            all_ports.extend(stn.get("ports", []))
        ports_up = sum(1 for p in all_ports if _port_is_up(p))
        ports_down = len(all_ports) - ports_up

        with ui.grid(columns=7).classes("gap-4"):
            _stat_chip("Chip", f"0x{topo_data.get('chip_id', 0):04X}")
            _stat_chip("Board", profile.chip_name)
            _stat_chip("Family", topo_data.get("chip_family", "unknown"))
            _stat_chip("Stations", str(topo_data.get("station_count", 0)))
            _stat_chip("Total Ports", str(topo_data.get("total_ports", 0)))
            _stat_chip(
                "Ports UP",
                str(ports_up),
                COLORS.green if ports_up > 0 else COLORS.text_muted,
            )
            _stat_chip(
                "Ports DOWN",
                str(ports_down),
                COLORS.red if ports_down > 0 else COLORS.text_muted,
            )

        upstream = topo_data.get("upstream_ports", [])
        downstream = topo_data.get("downstream_ports", [])
        if upstream:
            ui.label(
                f"Upstream Ports: {', '.join(str(p) for p in upstream)}"
            ).classes("mt-2").style(f"color: {COLORS.blue}")
        if downstream:
            ui.label(
                f"Downstream Ports: {', '.join(str(p) for p in downstream)}"
            ).style(f"color: {COLORS.green}")


def _render_connector_health(topo_data: dict, profile: BoardProfile) -> None:
    """Render per-connector health summary showing link status at a glance."""
    stations = topo_data.get("stations", [])
    if not stations:
        return

    connector_ref = _build_connector_ref(profile)
    connector_stats = _build_connector_stats(stations, connector_ref)
    if not connector_stats:
        return

    with ui.card().classes("w-full p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    ):
        ui.label("Connector Health").classes("text-h6 mb-2").style(
            f"color: {COLORS.text_primary}"
        )
        with ui.row().classes("flex-wrap gap-4"):
            for cs in connector_stats:
                _render_connector_health_chip(cs)


def _build_connector_stats(
    stations: list[dict],
    connector_ref: list[dict],
) -> list[dict]:
    """Build per-connector statistics from live station/port data."""
    stn_map = {s.get("station_index", -1): s for s in stations}

    stats = []
    for ref in connector_ref:
        stn_data = stn_map.get(ref["station"])
        if not stn_data:
            continue
        ports = stn_data.get("ports", [])
        lane_lo, lane_hi = (int(x) for x in ref["lanes"].split("-"))
        connector_ports = [
            p for p in ports
            if lane_lo <= p.get("port_number", -1) <= lane_hi
        ]
        up = sum(1 for p in connector_ports if _port_is_up(p))
        down = len(connector_ports) - up

        active_speed = "none"
        for p in connector_ports:
            st = p.get("status")
            if st and st.get("is_link_up"):
                active_speed = st.get("link_speed", "unknown")
                break

        stats.append({
            "name": ref["name"],
            "type": ref["type"],
            "width": ref["width"],
            "total": len(connector_ports),
            "up": up,
            "down": down,
            "speed": active_speed,
        })
    return stats


def _render_connector_health_chip(cs: dict) -> None:
    """Render a single connector health indicator chip."""
    up = cs["up"]
    total = cs["total"]
    all_up = up == total and total > 0
    any_up = up > 0

    border = (
        COLORS.green if all_up
        else COLORS.yellow if any_up
        else COLORS.border
    )

    with ui.element("div").classes("p-3 rounded").style(
        f"background: {COLORS.bg_card}; "
        f"border: 2px solid {border}; min-width: 140px"
    ):
        with ui.row().classes("items-center gap-2 mb-1"):
            icon = "check_circle" if all_up else "warning" if any_up else "cancel"
            icon_color = (
                COLORS.green if all_up
                else COLORS.yellow if any_up
                else COLORS.red
            )
            ui.icon(icon).style(f"color: {icon_color}")
            ui.label(cs["name"]).style(
                f"color: {COLORS.text_primary}; font-weight: bold"
            )
        ui.label(f"{cs['type']} ({cs['width']})").style(
            f"color: {COLORS.text_secondary}; font-size: 12px"
        )
        ui.label(f"{up}/{total} ports up").style(
            f"color: {COLORS.text_secondary}; font-size: 12px"
        )
        if cs["speed"] != "none":
            ui.label(cs["speed"]).style(
                f"color: {COLORS.blue}; font-size: 12px"
            )


def _render_station_cards(topo_data: dict, profile: BoardProfile) -> None:
    """Render per-station detail cards with connector grouping."""
    for station in topo_data.get("stations", []):
        stn_idx = station.get("station_index", 0)
        connector = station.get("connector_name") or "Internal"
        label = station.get("label") or f"Station {stn_idx}"
        lane_range = station.get("lane_range")
        ports = station.get("ports", [])

        total = len(ports)
        up = sum(1 for p in ports if _port_is_up(p))

        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
        ):
            # Station header
            with ui.row().classes("items-center gap-4 mb-2"):
                ui.label(f"STN{stn_idx}").classes("text-h6").style(
                    f"color: {COLORS.blue}"
                )
                ui.label(label).style(f"color: {COLORS.text_primary}")
                ui.badge(connector).props("outline").style(
                    f"color: {COLORS.purple}"
                )
                if lane_range:
                    ui.label(
                        f"Ports {lane_range[0]}-{lane_range[1]}"
                    ).style(f"color: {COLORS.text_muted}")
                up_color = COLORS.green if up > 0 else COLORS.text_muted
                ui.label(f"{up}/{total} up").style(
                    f"color: {up_color}; font-size: 12px"
                )

            if not ports:
                ui.label("No active ports").style(
                    f"color: {COLORS.text_muted}"
                )
                continue

            # Group ports by sub-connector within the station
            connector_groups = _group_ports_by_connector(stn_idx, ports, profile)

            if len(connector_groups) > 1:
                for group_name, group_ports in connector_groups.items():
                    group_up = sum(1 for p in group_ports if _port_is_up(p))
                    with ui.column().classes("w-full mb-2"):
                        with ui.row().classes("items-center gap-2 mb-1"):
                            ui.label(group_name).style(
                                f"color: {COLORS.orange}; font-weight: bold; font-size: 13px"
                            )
                            ui.label(f"({group_up}/{len(group_ports)} up)").style(
                                f"color: {COLORS.text_muted}; font-size: 12px"
                            )
                        _render_port_grid(group_ports)
            else:
                _render_port_grid(ports)


def _group_ports_by_connector(
    stn_idx: int,
    ports: list[dict],
    profile: BoardProfile,
) -> dict[str, list[dict]]:
    """Group ports by their physical connector within a station.

    Derives connector ranges from the profile's connector_map instead
    of using hardcoded station/lane ranges.
    """
    # Find all connectors that belong to this station
    stn_connectors = [
        (cn_name, info)
        for cn_name, info in sorted(profile.connector_map.items())
        if info.station == stn_idx
    ]

    if len(stn_connectors) <= 1:
        return {"all": ports}

    groups: dict[str, list[dict]] = {}
    unmatched: list[dict] = []
    for port in ports:
        pn = port.get("port_number", -1)
        placed = False
        for cn_name, info in stn_connectors:
            lo, hi = info.lanes
            if lo <= pn <= hi:
                label = f"{cn_name} [{lo}:{hi}]"
                groups.setdefault(label, []).append(port)
                placed = True
                break
        if not placed:
            unmatched.append(port)

    if unmatched:
        groups["Other"] = unmatched

    return groups


def _render_port_grid(ports: list[dict]) -> None:
    """Render a grid of port tiles with status coloring."""
    with ui.row().classes("flex-wrap gap-2"):
        for port in ports:
            port_num = port.get("port_number", 0)
            role = port.get("role", "unknown")
            status = port.get("status")
            is_up = status.get("is_link_up", False) if status else False

            border_color = (
                COLORS.blue if role == "upstream"
                else COLORS.green if role == "downstream"
                else COLORS.border
            )

            with ui.element("div").classes(
                "p-2 rounded text-center"
            ).style(
                f"background: {COLORS.bg_card}; "
                f"border: 2px solid {border_color}; "
                f"min-width: 80px"
            ):
                ui.label(f"P{port_num}").style(
                    f"color: {COLORS.text_primary}; font-weight: bold"
                )
                ui.label(role).style(
                    f"color: {COLORS.text_secondary}; font-size: 11px"
                )
                if status:
                    speed = status.get("link_speed", "unknown")
                    width = status.get("link_width", 0)
                    status_color = (
                        COLORS.green if is_up
                        else COLORS.red
                    )
                    ui.label(
                        f"x{width} {speed}" if is_up else "DOWN"
                    ).style(
                        f"color: {status_color}; font-size: 11px"
                    )

                # Show connected device info on DSP ports
                connected = port.get("connected_device")
                if connected:
                    dev_type = connected.get("device_type", "")
                    vid = connected.get("vendor_id", 0)
                    did = connected.get("device_id", 0)
                    if dev_type:
                        ui.badge(dev_type).props("outline").style(
                            f"color: {COLORS.cyan}; border-color: {COLORS.cyan}; "
                            f"font-size: 9px"
                        )
                    if vid:
                        ui.label(f"{vid:04x}:{did:04x}").style(
                            f"color: {COLORS.text_muted}; font-size: 9px"
                        )


def _port_is_up(port: dict) -> bool:
    """Check if a port is link-up from its status dict."""
    status = port.get("status")
    if not status:
        return False
    return status.get("is_link_up", False)


def _stat_chip(label: str, value: str, color: str | None = None) -> None:
    """Render a small stat display."""
    val_color = color or COLORS.text_primary
    with ui.column().classes("items-center"):
        ui.label(value).classes("text-h6").style(f"color: {val_color}")
        ui.label(label).style(f"color: {COLORS.text_muted}; font-size: 12px")
