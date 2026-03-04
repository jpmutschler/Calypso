"""Port Status Snapshot — enumerate all ports on an Atlas3 switch and print a summary table.

Opens a device by index, queries every port via PortManager, and prints
a human-readable table showing port number, role, link state, negotiated
speed, negotiated width, and MPS.  Optionally writes the same data to CSV.

Usage:
    python port_status_snapshot.py 0
    python port_status_snapshot.py 0 --csv ports.csv

Prerequisites:
    - Calypso installed: ``pip install -e ".[dev]"``
    - PLX driver loaded (PlxSvc service on Windows, PlxSvc module on Linux)
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from calypso.core.port_manager import PortManager
from calypso.core.switch import SwitchDevice
from calypso.exceptions import CalypsoError
from calypso.models.port import PortStatus
from calypso.transport.pcie import PcieTransport
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

# Column definitions for the output table.
# Each tuple is (header, width, alignment) where alignment is "<" or ">".
TABLE_COLUMNS: tuple[tuple[str, int, str], ...] = (
    ("Port", 6, ">"),
    ("Role", 14, "<"),
    ("Link", 6, "<"),
    ("Speed", 12, "<"),
    ("Width", 7, ">"),
    ("MPS", 6, ">"),
)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _build_header_line() -> str:
    """Return the formatted header row."""
    parts = tuple(f"{name:{align}{width}}" for name, width, align in TABLE_COLUMNS)
    return "  ".join(parts)


def _build_separator_line() -> str:
    """Return a separator line matching the header width."""
    parts = tuple("-" * width for _, width, _ in TABLE_COLUMNS)
    return "  ".join(parts)


def _format_row(status: PortStatus) -> str:
    """Format a single PortStatus into a fixed-width table row."""
    link_state = "UP" if status.is_link_up else "DOWN"
    width_str = f"x{status.link_width}" if status.is_link_up else "-"
    speed_str = str(status.link_speed.value) if status.is_link_up else "-"
    mps_str = str(status.max_payload_size) if status.is_link_up else "-"

    values = (
        f"{status.port_number:>6}",
        f"{status.role.value:<14}",
        f"{link_state:<6}",
        f"{speed_str:<12}",
        f"{width_str:>7}",
        f"{mps_str:>6}",
    )
    return "  ".join(values)


# ---------------------------------------------------------------------------
# Table output
# ---------------------------------------------------------------------------


def print_port_table(statuses: tuple[PortStatus, ...]) -> None:
    """Print a formatted table of port statuses to stdout."""
    print()
    print(_build_header_line())
    print(_build_separator_line())
    for status in statuses:
        print(_format_row(status))

    up_count = sum(1 for s in statuses if s.is_link_up)
    print(_build_separator_line())
    print(f"\n  {len(statuses)} port(s) total, {up_count} link(s) up\n")


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------


def write_csv(statuses: tuple[PortStatus, ...], path: Path) -> Path:
    """Write port statuses to a CSV file and return the resolved path.

    Creates parent directories if they do not exist.
    """
    resolved = path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)

    rows = tuple(
        {
            "port_number": s.port_number,
            "role": s.role.value,
            "link_up": s.is_link_up,
            "link_speed": s.link_speed.value if s.is_link_up else "",
            "link_width": s.link_width if s.is_link_up else "",
            "max_payload_size": s.max_payload_size if s.is_link_up else "",
        }
        for s in statuses
    )

    fieldnames = ("port_number", "role", "link_up", "link_speed", "link_width", "max_payload_size")
    with resolved.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return resolved


# ---------------------------------------------------------------------------
# Device interaction
# ---------------------------------------------------------------------------


def collect_port_statuses(device_index: int) -> tuple[PortStatus, ...]:
    """Open a device by index, enumerate ports, and return their statuses.

    The device is opened inside a context manager so resources are always
    released, even on error.
    """
    transport = PcieTransport()
    device = SwitchDevice(transport)
    device.open(device_index)

    try:
        device_obj = device._require_open()
        device_key = device.device_key
        if device_key is None:
            raise CalypsoError("Device key unavailable after open.")

        info = device.device_info
        chip_label = f"0x{info.chip_type:04X}" if info else "unknown"
        logger.info("device_opened", index=device_index, chip=chip_label)

        manager = PortManager(device_obj, device_key)
        statuses = manager.get_all_port_statuses()
    finally:
        device.close()

    return tuple(statuses)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Snapshot port statuses on an Atlas3 PCIe switch.",
    )
    parser.add_argument(
        "device_index",
        type=int,
        help="Zero-based index of the Atlas3 device to open (matches 'calypso scan' order).",
    )
    parser.add_argument(
        "--csv",
        dest="csv_path",
        type=Path,
        default=None,
        help="Optional path to write a CSV file with the port data.",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Entry point: collect port statuses, display table, optionally save CSV."""
    args = parse_args(argv)

    try:
        statuses = collect_port_statuses(args.device_index)
    except CalypsoError as exc:
        logger.error("device_error", detail=str(exc))
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130

    if not statuses:
        print("No ports found on the device.", file=sys.stderr)
        return 1

    print_port_table(statuses)

    if args.csv_path is not None:
        resolved = write_csv(statuses, args.csv_path)
        print(f"  CSV written to {resolved}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
