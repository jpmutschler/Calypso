"""Dump the full switch fabric topology for an Atlas3 PCIe Gen6 switch.

Discovers stations, ports, connected downstream devices, and physical
connector mappings.  Prints a human-readable tree to stdout and optionally
exports the topology to JSON.

Usage:
    python examples/topology_dump.py 0
    python examples/topology_dump.py 0 --output topology.json

Prerequisites:
    - PLX driver loaded (PlxSvc service on Windows, kernel module on Linux)
    - At least one Atlas3 device visible on the PCIe bus
    - Calypso installed: ``pip install -e ".[dev]"``
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from calypso.core.switch import SwitchDevice
from calypso.core.topology import TopologyMapper
from calypso.hardware.atlas3 import BoardProfile, get_board_profile
from calypso.models.port import PortRole
from calypso.models.topology import TopologyMap, TopologyPort, TopologyStation
from calypso.transport.pcie import PcieTransport
from calypso.utils.logging import get_logger

logger = get_logger(__name__)


# -- CLI setup ---------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the topology dump script."""
    parser = argparse.ArgumentParser(
        description="Dump Atlas3 PCIe switch fabric topology.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python examples/topology_dump.py 0\n"
            "  python examples/topology_dump.py 0 --output topology.json\n"
        ),
    )
    parser.add_argument(
        "device_index",
        type=int,
        help="Zero-based index of the Atlas3 device to open.",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Path to write JSON export (omit for stdout-only).",
    )
    return parser


# -- Topology retrieval ------------------------------------------------------


def open_device_and_build_topology(device_index: int) -> TopologyMap:
    """Open the device, build topology, and close cleanly.

    Uses a context manager to ensure the device is always released,
    even when an error occurs during topology discovery.
    """
    transport = PcieTransport()
    dev = SwitchDevice(transport)

    dev.open(device_index=device_index)
    try:
        device_obj = dev._require_open()
        device_key = dev.device_key

        mapper = TopologyMapper(device=device_obj, device_key=device_key)
        topology = mapper.build_topology()
    finally:
        dev.close()

    return topology


def resolve_board_profile(topology: TopologyMap) -> BoardProfile:
    """Resolve the board profile from the topology chip identifiers."""
    return get_board_profile(topology.chip_id, chip_id=topology.real_chip_id)


# -- Formatting helpers ------------------------------------------------------


def format_chip_header(topology: TopologyMap, profile: BoardProfile) -> str:
    """Format a summary header for the switch chip."""
    lines = [
        "=" * 72,
        f"  Atlas3 Topology: {profile.chip_name} ({profile.name})",
        f"  Chip Family: {topology.chip_family}",
        f"  Chip ID: 0x{topology.chip_id:04X}  (real: 0x{topology.real_chip_id:04X})",
        f"  Stations: {topology.station_count}   |   Total Ports: {topology.total_ports}",
        f"  Upstream ports: {topology.upstream_ports or 'none'}",
        f"  Downstream ports: {topology.downstream_ports or 'none'}",
        "=" * 72,
    ]
    return "\n".join(lines)


def format_port_line(port: TopologyPort) -> str:
    """Format a single port as a compact one-liner."""
    role_tag = port.role.value if port.role != PortRole.UNKNOWN else "---"

    # Link status from the embedded PortStatus, if available
    if port.status is not None:
        link = "UP" if port.status.is_link_up else "down"
        width = f"x{port.status.link_width}"
        speed = port.status.link_speed.value
        link_info = f"{link} {width} @ {speed}"
    else:
        link_info = "no status"

    line = f"    Port {port.port_number:>3d}  [{role_tag:<12s}]  {link_info}"

    # Append connected device info when present
    if port.connected_device is not None:
        cd = port.connected_device
        line += (
            f"  ->  {cd.device_type} [{cd.bdf}] (VID:0x{cd.vendor_id:04X} DID:0x{cd.device_id:04X})"
        )

    return line


def format_station_block(station: TopologyStation) -> str:
    """Format a station with its hardware mapping and port table."""
    # Station heading
    heading_parts = [f"Station {station.station_index}"]
    if station.label:
        heading_parts.append(f'"{station.label}"')
    if station.connector_name:
        heading_parts.append(f"connector={station.connector_name}")
    if station.lane_range:
        low, high = station.lane_range
        heading_parts.append(f"ports {low}-{high}")

    heading = "  " + "  |  ".join(heading_parts)
    separator = "  " + "-" * 68

    port_lines = [format_port_line(p) for p in station.ports]

    return "\n".join([heading, separator, *port_lines])


def format_connector_table(profile: BoardProfile) -> str:
    """Format the physical connector mapping as a table."""
    if not profile.connector_map:
        return "  (no connector mapping available for this chip variant)"

    header = f"  {'Connector':<12s} {'Lanes':<14s} {'Station':>7s}  {'Type'}"
    separator = "  " + "-" * 50
    rows: list[str] = []
    for name, info in sorted(profile.connector_map.items()):
        lane_str = f"{info.lanes[0]}-{info.lanes[1]}"
        ctype = info.connector_type or ""
        rows.append(f"  {name:<12s} {lane_str:<14s} {info.station:>7d}  {ctype}")

    return "\n".join([header, separator, *rows])


# -- Output ------------------------------------------------------------------


def print_topology(topology: TopologyMap, profile: BoardProfile) -> None:
    """Print the full topology tree and connector table to stdout."""
    print(format_chip_header(topology, profile))
    print()

    for station in topology.stations:
        print(format_station_block(station))
        print()

    print("Physical Connectors:")
    print(format_connector_table(profile))
    print()


def export_topology_json(
    topology: TopologyMap,
    output_path: str,
) -> Path:
    """Serialize the topology to a JSON file.

    Returns the resolved output path.
    """
    resolved = Path(output_path).resolve()

    # Pydantic v2 model serialization
    data = json.loads(topology.model_dump_json())

    resolved.write_text(
        json.dumps(data, indent=2, sort_keys=False),
        encoding="utf-8",
    )
    return resolved


# -- Entry point -------------------------------------------------------------


def main() -> None:
    """Script entry point: parse args, dump topology, optionally export."""
    parser = build_parser()
    args = parser.parse_args()

    logger.info(
        "topology_dump_start",
        device_index=args.device_index,
    )

    try:
        topology = open_device_and_build_topology(args.device_index)
    except Exception as exc:
        logger.exception("topology_dump_failed")
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    profile = resolve_board_profile(topology)
    print_topology(topology, profile)

    if args.output is not None:
        try:
            saved_path = export_topology_json(topology, args.output)
            print(f"Topology exported to: {saved_path}")
            logger.info("topology_exported", path=str(saved_path))
        except OSError as exc:
            logger.exception("topology_export_failed")
            print(f"Error writing JSON: {exc}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
