"""Bandwidth Monitor — live per-port bandwidth sampling on an Atlas3 PCIe switch.

Opens a device by index, initializes PerfMonitor on all ports, and
continuously samples bandwidth counters at a configurable interval.
Prints a live-updating table of per-port payload bytes/sec (ingress
and egress) with human-readable units.  On exit, optionally exports
the full time-series to CSV.

Usage:
    python bandwidth_monitor.py 0
    python bandwidth_monitor.py 0 --interval 0.5 --duration 30
    python bandwidth_monitor.py 0 --interval 2 --csv bw_log.csv

Prerequisites:
    - Calypso installed: ``pip install -e ".[dev]"``
    - PLX driver loaded (PlxSvc service on Windows, PlxSvc module on Linux)
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from calypso.core.perf_monitor import PerfMonitor
from calypso.core.switch import SwitchDevice
from calypso.exceptions import CalypsoError
from calypso.models.performance import PerfSnapshot
from calypso.transport.pcie import PcieTransport
from calypso.utils.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data structures (immutable records)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PortBandwidthRow:
    """A single row of per-port bandwidth data for display or export."""

    port_number: int
    ingress_payload_byte_rate: float
    egress_payload_byte_rate: float
    ingress_link_utilization: float
    egress_link_utilization: float


@dataclass(frozen=True)
class TimeSample:
    """One time-series sample capturing all port bandwidths at a point in time."""

    timestamp_s: float
    elapsed_ms: int
    rows: tuple[PortBandwidthRow, ...]


@dataclass(frozen=True)
class TimeSeriesLog:
    """Accumulated time-series data for CSV export."""

    samples: tuple[TimeSample, ...] = ()

    def append(self, sample: TimeSample) -> TimeSeriesLog:
        """Return a new log with the sample appended (no mutation)."""
        return TimeSeriesLog(samples=(*self.samples, sample))


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

# Column definitions: (header, width, alignment)
TABLE_COLUMNS: tuple[tuple[str, int, str], ...] = (
    ("Port", 6, ">"),
    ("Ingress B/s", 14, ">"),
    ("Egress B/s", 14, ">"),
    ("Ingress Util%", 14, ">"),
    ("Egress Util%", 14, ">"),
)


def _format_rate(bytes_per_sec: float) -> str:
    """Format a byte rate with human-readable units (B/s, KB/s, MB/s, GB/s)."""
    if bytes_per_sec < 1_000:
        return f"{bytes_per_sec:.0f} B/s"
    if bytes_per_sec < 1_000_000:
        return f"{bytes_per_sec / 1_000:.1f} KB/s"
    if bytes_per_sec < 1_000_000_000:
        return f"{bytes_per_sec / 1_000_000:.2f} MB/s"
    return f"{bytes_per_sec / 1_000_000_000:.2f} GB/s"


def _format_utilization(utilization: float) -> str:
    """Format link utilization as a percentage string (0.0 to 100.0)."""
    return f"{utilization * 100:.1f}%"


def _build_header_line() -> str:
    """Return the formatted header row."""
    parts = tuple(f"{name:{align}{width}}" for name, width, align in TABLE_COLUMNS)
    return "  ".join(parts)


def _build_separator_line() -> str:
    """Return a separator line matching the header width."""
    parts = tuple("-" * width for _, width, _ in TABLE_COLUMNS)
    return "  ".join(parts)


def _format_row(row: PortBandwidthRow) -> str:
    """Format a single port bandwidth row for the table."""
    return "  ".join(
        (
            f"{row.port_number:>6}",
            f"{_format_rate(row.ingress_payload_byte_rate):>14}",
            f"{_format_rate(row.egress_payload_byte_rate):>14}",
            f"{_format_utilization(row.ingress_link_utilization):>14}",
            f"{_format_utilization(row.egress_link_utilization):>14}",
        )
    )


# ---------------------------------------------------------------------------
# Snapshot to display model
# ---------------------------------------------------------------------------


def _extract_rows(snapshot: PerfSnapshot) -> tuple[PortBandwidthRow, ...]:
    """Convert a PerfSnapshot into a tuple of display rows."""
    return tuple(
        PortBandwidthRow(
            port_number=s.port_number,
            ingress_payload_byte_rate=s.ingress_payload_byte_rate,
            egress_payload_byte_rate=s.egress_payload_byte_rate,
            ingress_link_utilization=s.ingress_link_utilization,
            egress_link_utilization=s.egress_link_utilization,
        )
        for s in snapshot.port_stats
    )


def _snapshot_to_sample(snapshot: PerfSnapshot, wall_time: float) -> TimeSample:
    """Convert a PerfSnapshot plus wall-clock time into a TimeSample."""
    return TimeSample(
        timestamp_s=wall_time,
        elapsed_ms=snapshot.elapsed_ms,
        rows=_extract_rows(snapshot),
    )


# ---------------------------------------------------------------------------
# Terminal output
# ---------------------------------------------------------------------------

# ANSI escape: move cursor up N lines and clear each line.
_ANSI_CLEAR_LINE = "\033[2K"
_ANSI_CURSOR_UP = "\033[{n}A"
_ANSI_CURSOR_RESET = "\033[H"


def _print_table(
    rows: tuple[PortBandwidthRow, ...],
    elapsed_s: float,
    sample_count: int,
    *,
    first_draw: bool = False,
) -> int:
    """Print (or redraw) the bandwidth table.  Returns line count printed.

    On the first draw, prints normally.  On subsequent draws, moves the
    cursor up to overwrite the previous table in-place.
    """
    lines: list[str] = []
    lines.append(f"  Sample #{sample_count}  |  Elapsed: {elapsed_s:.1f}s")
    lines.append("")
    lines.append(_build_header_line())
    lines.append(_build_separator_line())
    for row in rows:
        lines.append(_format_row(row))
    lines.append(_build_separator_line())
    lines.append(f"  {len(rows)} port(s) monitored  |  Ctrl+C to stop")

    total_lines = len(lines)

    if not first_draw:
        # Move cursor up to overwrite previous output.
        sys.stdout.write(f"\033[{total_lines}A")

    for line in lines:
        sys.stdout.write(f"{_ANSI_CLEAR_LINE}{line}\n")

    sys.stdout.flush()
    return total_lines


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------


def write_csv(log: TimeSeriesLog, path: Path) -> Path:
    """Write accumulated time-series data to CSV.  Returns the resolved path."""
    resolved = path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = (
        "timestamp_s",
        "elapsed_ms",
        "port_number",
        "ingress_payload_byte_rate",
        "egress_payload_byte_rate",
        "ingress_link_utilization",
        "egress_link_utilization",
    )

    csv_rows = tuple(
        {
            "timestamp_s": f"{sample.timestamp_s:.3f}",
            "elapsed_ms": sample.elapsed_ms,
            "port_number": row.port_number,
            "ingress_payload_byte_rate": f"{row.ingress_payload_byte_rate:.2f}",
            "egress_payload_byte_rate": f"{row.egress_payload_byte_rate:.2f}",
            "ingress_link_utilization": f"{row.ingress_link_utilization:.6f}",
            "egress_link_utilization": f"{row.egress_link_utilization:.6f}",
        }
        for sample in log.samples
        for row in sample.rows
    )

    with resolved.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_rows)

    return resolved


# ---------------------------------------------------------------------------
# Monitoring loop
# ---------------------------------------------------------------------------


def run_monitor(
    device_index: int,
    interval: float,
    duration: float | None,
    csv_path: Path | None,
) -> int:
    """Open device, run bandwidth sampling loop, and optionally export CSV.

    Returns an exit code (0 for success, 1 for error).
    """
    transport = PcieTransport()
    device = SwitchDevice(transport)

    try:
        device.open(device_index)
    except CalypsoError as exc:
        logger.error("device_open_failed", detail=str(exc))
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    device_obj = device._require_open()
    device_key = device.device_key
    if device_key is None:
        device.close()
        print("Error: device key unavailable after open.", file=sys.stderr)
        return 1

    info = device.device_info
    chip_label = f"0x{info.chip_type:04X}" if info else "unknown"
    print(f"\n  Device {device_index} opened  |  Chip: {chip_label}\n")

    monitor = PerfMonitor(device_obj, device_key)
    port_count = monitor.initialize()
    if port_count == 0:
        print("Error: no ports available for monitoring.", file=sys.stderr)
        device.close()
        return 1

    print(f"  Initialized {port_count} port(s) for monitoring.")
    print(f"  Sampling every {interval}s", end="")
    if duration is not None:
        print(f" for {duration}s", end="")
    print(".\n")

    monitor.start()
    log = TimeSeriesLog()
    start_time = time.monotonic()
    sample_count = 0

    try:
        log = _sampling_loop(monitor, interval, duration, start_time, log)
    except KeyboardInterrupt:
        pass
    finally:
        sample_count = len(log.samples)
        monitor.stop()
        device.close()
        print(f"\n\n  Stopped after {sample_count} sample(s).\n")

    if csv_path is not None and sample_count > 0:
        resolved = write_csv(log, csv_path)
        print(f"  CSV written to {resolved}\n")

    return 0


def _sampling_loop(
    monitor: PerfMonitor,
    interval: float,
    duration: float | None,
    start_time: float,
    log: TimeSeriesLog,
) -> TimeSeriesLog:
    """Run the sampling loop, returning the accumulated time-series log.

    This function is separated from run_monitor so that KeyboardInterrupt
    can be caught cleanly in the caller.
    """
    first_draw = True
    sample_count = 0

    # Discard the first snapshot (counters need a baseline interval).
    time.sleep(interval)
    monitor.read_snapshot()

    while True:
        time.sleep(interval)
        wall_time = time.monotonic()
        elapsed_s = wall_time - start_time

        if duration is not None and elapsed_s >= duration:
            break

        snapshot = monitor.read_snapshot()
        sample_count += 1
        sample = _snapshot_to_sample(snapshot, elapsed_s)
        log = log.append(sample)

        _print_table(
            sample.rows,
            elapsed_s,
            sample_count,
            first_draw=first_draw,
        )
        first_draw = False

    return log


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Live per-port bandwidth monitor for Atlas3 PCIe switches. "
            "Samples ingress/egress payload byte rates and link utilization."
        ),
    )
    parser.add_argument(
        "device_index",
        type=int,
        help=("Zero-based index of the Atlas3 device to open (matches 'calypso scan' order)."),
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Sampling interval in seconds (default: 1.0).",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help=("Total monitoring duration in seconds.  If omitted, runs until Ctrl+C."),
    )
    parser.add_argument(
        "--csv",
        dest="csv_path",
        type=Path,
        default=None,
        help="Path to write a CSV file with the time-series data on exit.",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse args and run the bandwidth monitor."""
    args = parse_args(argv)

    if args.interval <= 0:
        print("Error: --interval must be positive.", file=sys.stderr)
        return 1

    if args.duration is not None and args.duration <= 0:
        print("Error: --duration must be positive.", file=sys.stderr)
        return 1

    return run_monitor(
        device_index=args.device_index,
        interval=args.interval,
        duration=args.duration,
        csv_path=args.csv_path,
    )


if __name__ == "__main__":
    raise SystemExit(main())
