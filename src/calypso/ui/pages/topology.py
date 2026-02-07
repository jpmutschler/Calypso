"""Switch topology page with connector and station mapping."""

from __future__ import annotations

from nicegui import ui

from calypso.hardware.atlas3 import CONNECTOR_MAP, CON_TO_CN, STATION_MAP
from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS

# Connector type labels (not stored in atlas3.py dataclasses)
_CONNECTOR_TYPES: dict[str, str] = {
    "CN1": "Straddle",
    "CN2": "Ext MCIO",
    "CN3": "Ext MCIO",
    "CN4": "Int MCIO",
    "CN5": "Int MCIO",
}

# Reverse CON_TO_CN for lookup: cn_name -> "CONn"
_CN_TO_CON: dict[str, str] = {cn: f"CON{con_id}" for con_id, cn in CON_TO_CN.items()}


def _build_connector_ref() -> list[dict]:
    """Build connector reference table rows from atlas3 hardware data."""
    return [
        {
            "name": cn_name,
            "type": _CONNECTOR_TYPES.get(cn_name, "Unknown"),
            "station": info.station,
            "lanes": f"{info.lanes[0]}-{info.lanes[1]}",
            "width": f"x{info.lanes[1] - info.lanes[0] + 1}",
            "con": _CN_TO_CON.get(cn_name, ""),
        }
        for cn_name, info in sorted(CONNECTOR_MAP.items())
    ]


def _build_station_ref() -> list[dict]:
    """Build station reference table rows from atlas3 hardware data."""
    return [
        {
            "stn": stn_id,
            "label": stn.label,
            "ports": f"{stn.port_range[0]}-{stn.port_range[1]}",
            "connector": stn.connector,
        }
        for stn_id, stn in sorted(STATION_MAP.items())
    ]


_CONNECTOR_REF = _build_connector_ref()
_STATION_REF = _build_station_ref()


def topology_page(device_id: str) -> None:
    """Render the switch topology page with hardware mapping details."""

    def content():
        topo_data: dict = {}

        async def load_topology():
            try:
                resp = await ui.run_javascript(
                    f'return await (await fetch("/api/devices/{device_id}/topology")).json()'
                )
                topo_data.clear()
                topo_data.update(resp)
                refresh_topology()
            except Exception as e:
                ui.notify(f"Error: {e}", type="negative")

        with ui.row().classes("items-center gap-4"):
            ui.button("Load Topology", on_click=load_topology).props("flat color=primary")

        # Hardware reference (always visible)
        _render_hardware_reference()

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

                _render_fabric_summary(topo_data)
                _render_connector_health(topo_data)
                _render_station_cards(topo_data)

        refresh_topology()

    page_layout("Switch Topology", content, device_id=device_id)


def _render_hardware_reference() -> None:
    """Render the static Atlas3 hardware reference cards."""
    with ui.expansion(
        "Atlas3 Host Card Reference",
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
                    {"name": "con", "label": "CON ID", "field": "con", "align": "center"},
                ]
                ui.table(
                    columns=columns, rows=_CONNECTOR_REF, row_key="name"
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
                    for s in _STATION_REF
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
                ui.html(
                    "  [Host CPU] &lt;--x16--&gt; [Golden Finger / STN2]\n"
                    "                               |\n"
                    "                      [Atlas3 PEX90144 Switch]\n"
                    "                        /      |       \\\n"
                    "                  STN0(RC)   STN1(Rsvd)  STN5(Straddle/CN1)\n"
                    "                                          x16\n"
                    "                        /               \\\n"
                    "           STN7(Ext MCIO)            STN8(Int MCIO)\n"
                    "           CN3[112:119]x8            CN5[128:135]x8\n"
                    "           CN2[120:127]x8            CN4[136:143]x8"
                )


def _render_fabric_summary(topo_data: dict) -> None:
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

        with ui.grid(columns=6).classes("gap-4"):
            _stat_chip("Chip", f"0x{topo_data.get('chip_id', 0):04X}")
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


def _render_connector_health(topo_data: dict) -> None:
    """Render per-connector health summary showing link status at a glance."""
    stations = topo_data.get("stations", [])
    if not stations:
        return

    # Build connector-level summaries from live topology data
    connector_stats = _build_connector_stats(stations)
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


def _build_connector_stats(stations: list[dict]) -> list[dict]:
    """Build per-connector statistics from live station/port data."""
    # Map station index -> station data
    stn_map = {s.get("station_index", -1): s for s in stations}

    stats = []
    for ref in _CONNECTOR_REF:
        stn_data = stn_map.get(ref["station"])
        if not stn_data:
            continue
        ports = stn_data.get("ports", [])
        lane_lo, lane_hi = (int(x) for x in ref["lanes"].split("-"))
        # Filter ports that belong to this specific connector
        connector_ports = [
            p for p in ports
            if lane_lo <= p.get("port_number", -1) <= lane_hi
        ]
        up = sum(1 for p in connector_ports if _port_is_up(p))
        down = len(connector_ports) - up

        # Find active link speed from first link-up port
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


def _render_station_cards(topo_data: dict) -> None:
    """Render per-station detail cards with connector grouping."""
    for station in topo_data.get("stations", []):
        stn_idx = station.get("station_index", 0)
        connector = station.get("connector_name") or "Internal"
        label = station.get("label") or f"Station {stn_idx}"
        lane_range = station.get("lane_range")
        ports = station.get("ports", [])

        # Calculate station-level stats
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
                # Port count summary
                up_color = COLORS.green if up > 0 else COLORS.text_muted
                ui.label(f"{up}/{total} up").style(
                    f"color: {up_color}; font-size: 12px"
                )

            if not ports:
                ui.label("No active ports").style(
                    f"color: {COLORS.text_muted}"
                )
                continue

            # For stations with multiple connectors (STN7, STN8), group ports
            connector_groups = _group_ports_by_connector(stn_idx, ports)

            if len(connector_groups) > 1:
                # Multiple sub-connectors: show grouped
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
                # Single connector or ungrouped
                _render_port_grid(ports)


def _group_ports_by_connector(stn_idx: int, ports: list[dict]) -> dict[str, list[dict]]:
    """Group ports by their physical connector within a station."""
    # Station 7: CN3 [112:119], CN2 [120:127]
    # Station 8: CN5 [128:135], CN4 [136:143]
    connector_ranges: dict[int, list[tuple[str, int, int]]] = {
        7: [("CN3 [112:119]", 112, 119), ("CN2 [120:127]", 120, 127)],
        8: [("CN5 [128:135]", 128, 135), ("CN4 [136:143]", 136, 143)],
    }

    ranges = connector_ranges.get(stn_idx)
    if not ranges:
        return {"all": ports}

    groups: dict[str, list[dict]] = {}
    unmatched: list[dict] = []
    for port in ports:
        pn = port.get("port_number", -1)
        placed = False
        for name, lo, hi in ranges:
            if lo <= pn <= hi:
                groups.setdefault(name, []).append(port)
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
