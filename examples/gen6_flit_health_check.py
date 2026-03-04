"""Gen6 Flit Health Check — verify 64 GT/s Flit mode readiness and error status.

Opens a device by index, iterates all ports, and for each port:
  1. Checks Gen6 64 GT/s support via Supported Link Speeds Vector
  2. Reads Physical Layer 64 GT/s Extended Capability (ExtCapID 0x0026)
  3. Checks Flit Mode Support / Equalization status
  4. Reads Flit Error Logging capability (ExtCapID 0x0032) — counter + log entries
  5. Reports per-port Flit readiness and accumulated flit-level errors

Prints a color-coded summary table and optionally exports to JSON.

Usage:
    python gen6_flit_health_check.py 0
    python gen6_flit_health_check.py 0 --output report.json

Prerequisites:
    - Calypso installed: ``pip install -e ".[dev]"``
    - PLX driver loaded (PlxSvc service on Windows, PlxSvc module on Linux)
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from calypso.bindings.constants import PlxApiMode
from calypso.bindings.types import PLX_MODE_PROP
from calypso.core.pcie_config import PcieConfigReader
from calypso.core.switch import SwitchDevice
from calypso.exceptions import CalypsoError
from calypso.models.pcie_config import (
    EqStatus64GT,
    FlitErrorCounter,
    FlitErrorLogEntry,
    FlitLoggingStatus,
)
from calypso.sdk import device as sdk_device
from calypso.transport.pcie import PcieTransport
from calypso.utils.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Status markers for terminal output
# ---------------------------------------------------------------------------

PASS = "[PASS]"
FAIL = "[FAIL]"
WARN = "[WARN]"
INFO = "[INFO]"


# ---------------------------------------------------------------------------
# Per-port result data
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PortFlitResult:
    """Immutable result of a single port's Gen6 Flit health check."""

    port_number: int
    is_link_up: bool
    current_speed: str
    current_width: int
    gen6_supported: bool
    flit_mode_supported: bool
    eq_complete: bool
    eq_phase1_ok: bool
    eq_phase2_ok: bool
    eq_phase3_ok: bool
    no_eq_needed: bool
    flit_logging_present: bool
    error_counter_enabled: bool
    error_count: int
    flit_error_entries: tuple[FlitErrorLogEntry, ...] = field(default_factory=tuple)
    raw_64gt_cap: int = 0
    raw_64gt_status: int = 0


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------


def _build_port_result_no_64gt(
    port_number: int,
    is_link_up: bool,
    current_speed: str,
    current_width: int,
    gen6_supported: bool,
) -> PortFlitResult:
    """Build a PortFlitResult when 64 GT/s capability is absent."""
    return PortFlitResult(
        port_number=port_number,
        is_link_up=is_link_up,
        current_speed=current_speed,
        current_width=current_width,
        gen6_supported=gen6_supported,
        flit_mode_supported=False,
        eq_complete=False,
        eq_phase1_ok=False,
        eq_phase2_ok=False,
        eq_phase3_ok=False,
        no_eq_needed=False,
        flit_logging_present=False,
        error_counter_enabled=False,
        error_count=0,
    )


def _build_port_result_with_64gt(
    port_number: int,
    is_link_up: bool,
    current_speed: str,
    current_width: int,
    eq_status: EqStatus64GT,
    flit_logging: FlitLoggingStatus | None,
    flit_error_entries: tuple[FlitErrorLogEntry, ...],
) -> PortFlitResult:
    """Build a PortFlitResult from 64 GT/s and Flit Logging data."""
    counter = flit_logging.error_counter if flit_logging else FlitErrorCounter()
    return PortFlitResult(
        port_number=port_number,
        is_link_up=is_link_up,
        current_speed=current_speed,
        current_width=current_width,
        gen6_supported=True,
        flit_mode_supported=eq_status.flit_mode_supported,
        eq_complete=eq_status.complete,
        eq_phase1_ok=eq_status.phase1_success,
        eq_phase2_ok=eq_status.phase2_success,
        eq_phase3_ok=eq_status.phase3_success,
        no_eq_needed=eq_status.no_eq_needed,
        flit_logging_present=flit_logging is not None,
        error_counter_enabled=counter.enable,
        error_count=counter.counter,
        flit_error_entries=flit_error_entries,
        raw_64gt_cap=eq_status.raw_capabilities,
        raw_64gt_status=eq_status.raw_status,
    )


def inspect_port(reader: PcieConfigReader) -> PortFlitResult:
    """Inspect a single port for Gen6 Flit readiness and errors.

    Reads link status, 64 GT/s capability, and Flit error logging
    from the given port's config space.
    """
    link_caps = reader.get_link_capabilities()
    link_status = reader.get_link_status()
    speeds = reader.get_supported_speeds()

    port_number = link_caps.port_number
    is_link_up = link_status.dll_link_active
    current_speed = link_status.current_speed
    current_width = link_status.current_width

    # Step 1: Check Gen6 in Supported Speeds Vector
    if not speeds.gen6:
        return _build_port_result_no_64gt(
            port_number, is_link_up, current_speed, current_width, gen6_supported=False
        )

    # Step 2: Read Physical Layer 64 GT/s Extended Capability (0x0026)
    eq_status = reader.get_eq_status_64gt()
    if eq_status is None:
        return _build_port_result_no_64gt(
            port_number, is_link_up, current_speed, current_width, gen6_supported=True
        )

    # Step 3: Read Flit Error Logging (0x0032)
    flit_logging = reader.get_flit_logging_status()
    flit_entries = tuple(reader.read_all_flit_error_log_entries(max_entries=64))

    return _build_port_result_with_64gt(
        port_number=port_number,
        is_link_up=is_link_up,
        current_speed=current_speed,
        current_width=current_width,
        eq_status=eq_status,
        flit_logging=flit_logging,
        flit_error_entries=flit_entries,
    )


def collect_all_ports(device_index: int) -> tuple[str, tuple[PortFlitResult, ...]]:
    """Open a device, enumerate all ports, and inspect each for Gen6 Flit health.

    Returns:
        Tuple of (chip_label, results) where results is a tuple of PortFlitResult.
    """
    transport = PcieTransport()
    device = SwitchDevice(transport)
    device.open(device_index)

    try:
        device._require_open()  # Validate device is open
        device_key = device.device_key
        if device_key is None:
            raise CalypsoError("Device key unavailable after open.")

        info = device.device_info
        chip_label = f"0x{info.chip_type:04X}" if info else "unknown"

        # Discover all ports via the same transport
        api_mode = PlxApiMode(device_key.ApiMode)
        mode_prop = PLX_MODE_PROP() if api_mode != PlxApiMode.PCI else None
        all_keys = sdk_device.find_devices(api_mode=api_mode, mode_prop=mode_prop)

        results: list[PortFlitResult] = []
        for key in all_keys:
            try:
                dev = sdk_device.open_device(key)
                try:
                    reader = PcieConfigReader(dev, key)
                    result = inspect_port(reader)
                    results.append(result)
                finally:
                    sdk_device.close_device(dev)
            except Exception as exc:
                logger.warning("port_inspect_failed", port=key.PlxPort, error=str(exc))
                continue

        sorted_results = sorted(results, key=lambda r: r.port_number)
    finally:
        device.close()

    return chip_label, tuple(sorted_results)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _flit_status_marker(result: PortFlitResult) -> str:
    """Return PASS/FAIL/WARN marker based on Flit mode state."""
    if not result.gen6_supported:
        return INFO
    if not result.flit_mode_supported:
        return WARN
    if result.error_count > 0 or len(result.flit_error_entries) > 0:
        return FAIL
    if result.eq_complete or result.no_eq_needed:
        return PASS
    return WARN


def _eq_summary(result: PortFlitResult) -> str:
    """Summarize equalization status as a compact string."""
    if result.no_eq_needed:
        return "no-eq-needed"
    if not result.eq_complete:
        return "incomplete"
    phases = []
    if result.eq_phase1_ok:
        phases.append("P1")
    if result.eq_phase2_ok:
        phases.append("P2")
    if result.eq_phase3_ok:
        phases.append("P3")
    return f"complete ({'/'.join(phases)})" if phases else "complete (no phases)"


# Summary table columns: (header, width, alignment)
TABLE_COLUMNS: tuple[tuple[str, int, str], ...] = (
    ("Status", 8, "<"),
    ("Port", 6, ">"),
    ("Link", 6, "<"),
    ("Speed", 12, "<"),
    ("Width", 7, ">"),
    ("Gen6", 6, "<"),
    ("Flit", 6, "<"),
    ("EQ", 22, "<"),
    ("Errors", 8, ">"),
)


def _build_header() -> str:
    """Return the formatted header row."""
    parts = tuple(f"{name:{align}{width}}" for name, width, align in TABLE_COLUMNS)
    return "  ".join(parts)


def _build_separator() -> str:
    """Return a separator line matching the header width."""
    parts = tuple("-" * width for _, width, _ in TABLE_COLUMNS)
    return "  ".join(parts)


def _format_result_row(result: PortFlitResult) -> str:
    """Format a single PortFlitResult into a table row."""
    marker = _flit_status_marker(result)
    link = "UP" if result.is_link_up else "DOWN"
    speed = result.current_speed if result.is_link_up else "-"
    width = f"x{result.current_width}" if result.is_link_up else "-"
    gen6 = "Yes" if result.gen6_supported else "No"
    flit = "Yes" if result.flit_mode_supported else "No"
    eq = _eq_summary(result) if result.gen6_supported else "-"
    errors = str(result.error_count) if result.flit_logging_present else "-"

    values = (
        f"{marker:<8}",
        f"{result.port_number:>6}",
        f"{link:<6}",
        f"{speed:<12}",
        f"{width:>7}",
        f"{gen6:<6}",
        f"{flit:<6}",
        f"{eq:<22}",
        f"{errors:>8}",
    )
    return "  ".join(values)


# ---------------------------------------------------------------------------
# Table and detail output
# ---------------------------------------------------------------------------


def print_summary_table(chip_label: str, results: tuple[PortFlitResult, ...]) -> None:
    """Print the main summary table to stdout."""
    print()
    print(f"  Gen6 Flit Health Check  --  Chip: {chip_label}")
    print(f"  Ports inspected: {len(results)}")
    print()
    print(f"  {_build_header()}")
    print(f"  {_build_separator()}")

    for result in results:
        print(f"  {_format_result_row(result)}")

    print(f"  {_build_separator()}")
    _print_totals(results)


def _print_totals(results: tuple[PortFlitResult, ...]) -> None:
    """Print aggregate totals below the table."""
    gen6_count = sum(1 for r in results if r.gen6_supported)
    flit_count = sum(1 for r in results if r.flit_mode_supported)
    eq_ok_count = sum(1 for r in results if r.eq_complete or r.no_eq_needed)
    error_ports = sum(1 for r in results if r.error_count > 0 or len(r.flit_error_entries) > 0)
    total_errors = sum(r.error_count for r in results)
    total_log_entries = sum(len(r.flit_error_entries) for r in results)

    print()
    print(f"  Gen6 capable ports:    {gen6_count}/{len(results)}")
    print(f"  Flit mode supported:   {flit_count}/{len(results)}")
    print(f"  EQ complete/no-eq:     {eq_ok_count}/{gen6_count}" if gen6_count else "")
    print(f"  Ports with errors:     {error_ports}")
    print(f"  Total error counter:   {total_errors}")
    print(f"  Total log entries:     {total_log_entries}")
    print()


def print_error_details(results: tuple[PortFlitResult, ...]) -> None:
    """Print detailed Flit Error Log entries for ports that have errors."""
    ports_with_entries = tuple(r for r in results if len(r.flit_error_entries) > 0)
    if not ports_with_entries:
        return

    print("  Flit Error Log Details")
    print("  " + "=" * 70)

    for result in ports_with_entries:
        print(f"\n  Port {result.port_number}  ({len(result.flit_error_entries)} entries)")
        print("  " + "-" * 60)

        for i, entry in enumerate(result.flit_error_entries):
            _print_single_log_entry(i, entry)

    print()


def _print_single_log_entry(index: int, entry: FlitErrorLogEntry) -> None:
    """Print a single Flit Error Log entry."""
    fec_flag = " FEC-UNCORR" if entry.fec_uncorrectable else ""
    unrec_flag = " UNRECOGNIZED" if entry.unrecognized_flit else ""
    more_flag = " [more]" if entry.more_entries else ""

    print(
        f"    [{index:>2}] width=x{entry.link_width}  offset={entry.flit_offset}"
        f"  consecutive={entry.consecutive_errors}{fec_flag}{unrec_flag}{more_flag}"
    )
    print(
        f"         syndromes=[{entry.syndrome_0:#x}, {entry.syndrome_1:#x},"
        f" {entry.syndrome_2:#x}, {entry.syndrome_3:#x}]"
        f"  raw=({entry.raw_log1:#010x}, {entry.raw_log2:#010x})"
    )


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------


def _result_to_dict(result: PortFlitResult) -> dict:
    """Convert a PortFlitResult to a JSON-serializable dict."""
    return {
        "port_number": result.port_number,
        "is_link_up": result.is_link_up,
        "current_speed": result.current_speed,
        "current_width": result.current_width,
        "gen6_supported": result.gen6_supported,
        "flit_mode_supported": result.flit_mode_supported,
        "equalization": {
            "complete": result.eq_complete,
            "phase1_ok": result.eq_phase1_ok,
            "phase2_ok": result.eq_phase2_ok,
            "phase3_ok": result.eq_phase3_ok,
            "no_eq_needed": result.no_eq_needed,
        },
        "flit_logging": {
            "present": result.flit_logging_present,
            "counter_enabled": result.error_counter_enabled,
            "error_count": result.error_count,
        },
        "flit_error_entries": [
            {
                "link_width": e.link_width,
                "flit_offset": e.flit_offset,
                "consecutive_errors": e.consecutive_errors,
                "fec_uncorrectable": e.fec_uncorrectable,
                "unrecognized_flit": e.unrecognized_flit,
                "syndromes": [e.syndrome_0, e.syndrome_1, e.syndrome_2, e.syndrome_3],
                "raw_log1": e.raw_log1,
                "raw_log2": e.raw_log2,
            }
            for e in result.flit_error_entries
        ],
        "raw_64gt_cap": result.raw_64gt_cap,
        "raw_64gt_status": result.raw_64gt_status,
    }


def export_json(
    chip_label: str,
    results: tuple[PortFlitResult, ...],
    path: Path,
) -> Path:
    """Write results to a JSON file and return the resolved path."""
    resolved = path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)

    report = {
        "chip": chip_label,
        "port_count": len(results),
        "gen6_capable_count": sum(1 for r in results if r.gen6_supported),
        "flit_supported_count": sum(1 for r in results if r.flit_mode_supported),
        "total_error_count": sum(r.error_count for r in results),
        "ports": [_result_to_dict(r) for r in results],
    }

    with resolved.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    return resolved


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Check Gen6 64 GT/s Flit mode readiness and error status "
            "on all ports of an Atlas3 PCIe switch."
        ),
    )
    parser.add_argument(
        "device_index",
        type=int,
        help="Zero-based index of the Atlas3 device (matches 'calypso scan' order).",
    )
    parser.add_argument(
        "--output",
        dest="output_path",
        type=Path,
        default=None,
        help="Optional path to write a JSON report file.",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Entry point: inspect all ports for Gen6 Flit health, print results."""
    args = parse_args(argv)

    try:
        chip_label, results = collect_all_ports(args.device_index)
    except CalypsoError as exc:
        logger.error("device_error", detail=str(exc))
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130

    if not results:
        print("No ports found on the device.", file=sys.stderr)
        return 1

    print_summary_table(chip_label, results)
    print_error_details(results)

    if args.output_path is not None:
        resolved = export_json(chip_label, results, args.output_path)
        print(f"  JSON report written to {resolved}\n")

    # Non-zero exit if any port has flit errors
    has_errors = any(r.error_count > 0 or len(r.flit_error_entries) > 0 for r in results)
    return 1 if has_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
