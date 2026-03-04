"""Discover Atlas3 PCIe switches and produce an inventory report.

This standalone script scans the PCIe bus for all Broadcom Atlas3 Gen6
switches (A0 and B0 silicon), prints a formatted summary table, and
optionally exports the inventory to a JSON file.

Usage:
    python discover_and_inventory.py
    python discover_and_inventory.py --output inventory.json
    python discover_and_inventory.py --include-downstream

Requirements:
    - Calypso must be installed (``pip install -e ".[dev]"``)
    - The PLX driver must be loaded (PlxSvc service on Windows,
      PlxSvc kernel module on Linux)
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from calypso.core.discovery import scan_devices
from calypso.hardware.atlas3 import BoardProfile, get_board_profile
from calypso.models.device_info import DeviceInfo
from calypso.transport.pcie import PcieTransport
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

# ChipID ranges that identify B0 silicon
_B0_CHIP_IDS = frozenset({0xA024, 0xA032, 0xA048, 0xA064, 0xA080, 0xA096})

# A0 silicon chip IDs
_A0_CHIP_IDS = frozenset({0x0144, 0x0080})


@dataclass(frozen=True)
class InventoryEntry:
    """Immutable snapshot of a discovered device for reporting."""

    index: int
    chip_name: str
    chip_id_hex: str
    silicon_rev: str
    station_count: int
    bdf: str
    family: str
    port_number: int


def _classify_silicon(device: DeviceInfo) -> str:
    """Determine silicon revision label from a device's chip ID."""
    if device.chip_id in _B0_CHIP_IDS:
        return "B0"
    if device.chip_id in _A0_CHIP_IDS:
        return "A0"
    # Fall back to chip_type for A0 devices that report via PlxChip
    if device.chip_type in (0xC040, 0xC044, 0x9080, 0x90A0):
        return "A0"
    return "??"


def _resolve_profile(device: DeviceInfo) -> BoardProfile:
    """Look up the board profile for a discovered device."""
    return get_board_profile(device.chip_type, chip_id=device.chip_id)


def _format_bdf(device: DeviceInfo) -> str:
    """Format a PCI Bus/Device/Function address string."""
    return f"{device.domain:04x}:{device.bus:02x}:{device.slot:02x}.{device.function}"


def build_inventory(devices: list[DeviceInfo]) -> list[InventoryEntry]:
    """Transform raw DeviceInfo list into immutable inventory entries."""
    entries: list[InventoryEntry] = []
    for idx, device in enumerate(devices):
        profile = _resolve_profile(device)
        entry = InventoryEntry(
            index=idx,
            chip_name=profile.chip_name,
            chip_id_hex=f"0x{device.chip_id:04X}",
            silicon_rev=_classify_silicon(device),
            station_count=len(profile.station_map),
            bdf=_format_bdf(device),
            family=device.chip_family,
            port_number=device.port_number,
        )
        entries = [*entries, entry]
    return entries


def print_inventory_table(entries: list[InventoryEntry]) -> None:
    """Print a formatted ASCII table of inventory entries to stdout."""
    if not entries:
        print("No Atlas3 devices found.")
        return

    # Column headers and widths
    headers = ("Idx", "Chip", "ChipID", "Rev", "Stations", "BDF", "Family", "Port")
    widths = (4, 12, 8, 4, 8, 16, 12, 5)

    header_line = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    separator = "  ".join("-" * w for w in widths)

    print(f"\n  Atlas3 PCIe Switch Inventory ({len(entries)} device(s))\n")
    print(f"  {header_line}")
    print(f"  {separator}")

    for entry in entries:
        row = (
            str(entry.index).rjust(widths[0]),
            entry.chip_name.ljust(widths[1]),
            entry.chip_id_hex.ljust(widths[2]),
            entry.silicon_rev.center(widths[3]),
            str(entry.station_count).center(widths[4]),
            entry.bdf.ljust(widths[5]),
            entry.family.ljust(widths[6]),
            str(entry.port_number).rjust(widths[7]),
        )
        print(f"  {'  '.join(row)}")

    print()


def export_inventory_json(
    entries: list[InventoryEntry],
    output_path: Path,
) -> None:
    """Serialize inventory entries to a JSON file."""
    records = [
        {
            "index": e.index,
            "chip_name": e.chip_name,
            "chip_id": e.chip_id_hex,
            "silicon_revision": e.silicon_rev,
            "station_count": e.station_count,
            "bdf": e.bdf,
            "family": e.family,
            "port_number": e.port_number,
        }
        for e in entries
    ]

    resolved = output_path.resolve()
    resolved.write_text(
        json.dumps({"devices": records, "count": len(records)}, indent=2),
        encoding="utf-8",
    )
    print(f"Inventory exported to {resolved}")


def discover_devices(include_downstream: bool = False) -> list[DeviceInfo]:
    """Connect to the PCIe transport and scan for Atlas3 switches.

    Returns:
        List of discovered DeviceInfo objects.

    Raises:
        SystemExit: If the PLX driver is not available.
    """
    transport = PcieTransport()
    try:
        transport.connect()
    except Exception as exc:
        logger.error("transport_connect_failed", error=str(exc))
        print(f"Error: Could not connect to PCIe transport: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    try:
        devices = scan_devices(transport, include_downstream=include_downstream)
        logger.info("discovery_complete", device_count=len(devices))
        return devices
    except Exception as exc:
        logger.error("scan_failed", error=str(exc))
        print(f"Error: Device scan failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        transport.disconnect()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Discover Atlas3 PCIe switches and report inventory.",
        epilog="Example: python discover_and_inventory.py --output inv.json",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Export inventory to a JSON file at the given path.",
    )
    parser.add_argument(
        "--include-downstream",
        action="store_true",
        default=False,
        help="Include downstream virtual ports (default: upstream only).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Entry point: discover devices, display table, optionally export."""
    args = parse_args(argv)

    print("Scanning PCIe bus for Atlas3 switches...")
    devices = discover_devices(include_downstream=args.include_downstream)

    inventory = build_inventory(devices)
    print_inventory_table(inventory)

    if args.output is not None:
        export_inventory_json(inventory, args.output)


if __name__ == "__main__":
    main()
