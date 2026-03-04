"""Overnight Soak Test — continuous AER error, bandwidth, and link state monitoring.

Combines AER error polling, bandwidth monitoring, and link state checking
into a long-running soak test that samples all three data sources at a
configurable interval.  Results are logged to rotating CSV files and alerts
are printed to stderr when errors appear, bandwidth drops, or links go down.

Usage:
    python overnight_soak.py 0
    python overnight_soak.py 0 --interval 5 --duration 3600
    python overnight_soak.py 0 --min-bandwidth 100.0 --log-dir /tmp/soak

Prerequisites:
    - Calypso installed: ``pip install -e ".[dev]"``
    - PLX driver loaded (PlxSvc service on Windows, PlxSvc module on Linux)
"""

from __future__ import annotations

import argparse
import csv
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from calypso.core.pcie_config import PcieConfigReader
from calypso.core.perf_monitor import PerfMonitor
from calypso.core.port_manager import PortManager
from calypso.core.switch import SwitchDevice
from calypso.exceptions import CalypsoError
from calypso.models.pcie_config import AerStatus
from calypso.models.performance import PerfSnapshot
from calypso.models.port import PortStatus
from calypso.transport.pcie import PcieTransport
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

# Maximum CSV file size before rotation (10 MB).
MAX_CSV_BYTES: int = 10 * 1024 * 1024

# CSV column definitions for each log type.
LINK_CSV_FIELDS: tuple[str, ...] = (
    "timestamp",
    "port",
    "role",
    "link_up",
    "speed",
    "width",
    "mps",
)
PERF_CSV_FIELDS: tuple[str, ...] = (
    "timestamp",
    "port",
    "ingress_byte_rate",
    "egress_byte_rate",
    "ingress_util",
    "egress_util",
    "ingress_bw_mbps",
    "egress_bw_mbps",
)
AER_CSV_FIELDS: tuple[str, ...] = (
    "timestamp",
    "uncorrectable_raw",
    "correctable_raw",
    "first_error_pointer",
)


# ---------------------------------------------------------------------------
# Data structures (immutable snapshots)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SoakSample:
    """A single soak iteration's collected data."""

    timestamp: str
    iteration: int
    link_statuses: tuple[PortStatus, ...]
    perf_snapshot: PerfSnapshot | None
    aer_status: AerStatus | None


@dataclass(frozen=True)
class SoakSummary:
    """Accumulated counters for the final report."""

    total_iterations: int
    total_seconds: float
    uncorrectable_error_count: int
    correctable_error_count: int
    link_down_events: int
    bandwidth_alerts: int
    min_ingress_bw_mbps: float
    min_egress_bw_mbps: float
    max_ingress_bw_mbps: float
    max_egress_bw_mbps: float


@dataclass
class SoakCounters:
    """Mutable accumulator used during the soak loop.

    Converted to an immutable SoakSummary at the end of the run.
    """

    total_iterations: int = 0
    uncorrectable_error_count: int = 0
    correctable_error_count: int = 0
    link_down_events: int = 0
    bandwidth_alerts: int = 0
    min_ingress_bw_mbps: float = float("inf")
    min_egress_bw_mbps: float = float("inf")
    max_ingress_bw_mbps: float = 0.0
    max_egress_bw_mbps: float = 0.0
    prev_uncorr_raw: int = 0
    prev_corr_raw: int = 0
    prev_link_up_ports: frozenset[int] = field(default_factory=frozenset)


# ---------------------------------------------------------------------------
# CSV file management with rotation
# ---------------------------------------------------------------------------


@dataclass
class RotatingCsvWriter:
    """Writes CSV rows, rotating to a new file when the size limit is hit."""

    base_path: Path
    fieldnames: tuple[str, ...]
    _file_index: int = 0
    _handle: TextIO | None = None
    _writer: csv.DictWriter | None = None  # type: ignore[type-arg]
    _bytes_written: int = 0

    def _current_path(self) -> Path:
        if self._file_index == 0:
            return self.base_path
        stem = self.base_path.stem
        suffix = self.base_path.suffix
        return self.base_path.with_name(f"{stem}.{self._file_index}{suffix}")

    def _open_new_file(self) -> None:
        self._close_current()
        path = self._current_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = path.open("w", newline="")
        self._writer = csv.DictWriter(self._handle, fieldnames=list(self.fieldnames))
        self._writer.writeheader()
        self._bytes_written = 0

    def _close_current(self) -> None:
        if self._handle is not None:
            self._handle.flush()
            self._handle.close()
            self._handle = None
            self._writer = None

    def write_row(self, row: dict[str, object]) -> None:
        """Write a single row, rotating the file if size exceeds the limit."""
        if self._writer is None:
            self._open_new_file()

        assert self._writer is not None
        assert self._handle is not None

        self._writer.writerow(row)
        self._handle.flush()
        self._bytes_written = self._handle.tell()

        if self._bytes_written >= MAX_CSV_BYTES:
            self._file_index += 1
            self._open_new_file()

    def close(self) -> None:
        """Flush and close the current file."""
        self._close_current()


# ---------------------------------------------------------------------------
# Data collection (one function per data source)
# ---------------------------------------------------------------------------


def collect_link_statuses(port_manager: PortManager) -> tuple[PortStatus, ...]:
    """Query all port statuses from the switch."""
    try:
        statuses = port_manager.get_all_port_statuses()
        return tuple(statuses)
    except CalypsoError as exc:
        logger.warning("link_status_failed", error=str(exc))
        return ()


def collect_perf_snapshot(perf_monitor: PerfMonitor) -> PerfSnapshot | None:
    """Read a performance counter snapshot."""
    try:
        return perf_monitor.read_snapshot()
    except CalypsoError as exc:
        logger.warning("perf_read_failed", error=str(exc))
        return None


def collect_aer_status(config_reader: PcieConfigReader) -> AerStatus | None:
    """Read AER error status registers."""
    try:
        return config_reader.get_aer_status()
    except CalypsoError as exc:
        logger.warning("aer_read_failed", error=str(exc))
        return None


def take_sample(
    iteration: int,
    port_manager: PortManager,
    perf_monitor: PerfMonitor,
    config_reader: PcieConfigReader,
) -> SoakSample:
    """Collect all three data sources into a single immutable sample."""
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    return SoakSample(
        timestamp=ts,
        iteration=iteration,
        link_statuses=collect_link_statuses(port_manager),
        perf_snapshot=collect_perf_snapshot(perf_monitor),
        aer_status=collect_aer_status(config_reader),
    )


# ---------------------------------------------------------------------------
# CSV logging (one function per log type)
# ---------------------------------------------------------------------------


def log_link_rows(
    writer: RotatingCsvWriter,
    timestamp: str,
    statuses: tuple[PortStatus, ...],
) -> None:
    """Write one CSV row per port for link status."""
    for s in statuses:
        writer.write_row(
            {
                "timestamp": timestamp,
                "port": s.port_number,
                "role": s.role.value,
                "link_up": s.is_link_up,
                "speed": s.link_speed.value if s.is_link_up else "",
                "width": s.link_width if s.is_link_up else "",
                "mps": s.max_payload_size if s.is_link_up else "",
            }
        )


def log_perf_rows(
    writer: RotatingCsvWriter,
    timestamp: str,
    snapshot: PerfSnapshot,
) -> None:
    """Write one CSV row per port for performance counters."""
    for ps in snapshot.port_stats:
        writer.write_row(
            {
                "timestamp": timestamp,
                "port": ps.port_number,
                "ingress_byte_rate": f"{ps.ingress_payload_byte_rate:.2f}",
                "egress_byte_rate": f"{ps.egress_payload_byte_rate:.2f}",
                "ingress_util": f"{ps.ingress_link_utilization:.4f}",
                "egress_util": f"{ps.egress_link_utilization:.4f}",
                "ingress_bw_mbps": f"{ps.ingress_bandwidth_mbps:.2f}",
                "egress_bw_mbps": f"{ps.egress_bandwidth_mbps:.2f}",
            }
        )


def log_aer_row(
    writer: RotatingCsvWriter,
    timestamp: str,
    aer: AerStatus,
) -> None:
    """Write a single CSV row for AER status."""
    writer.write_row(
        {
            "timestamp": timestamp,
            "uncorrectable_raw": f"0x{aer.uncorrectable.raw_value:08X}",
            "correctable_raw": f"0x{aer.correctable.raw_value:08X}",
            "first_error_pointer": aer.first_error_pointer,
        }
    )


# ---------------------------------------------------------------------------
# Alert checking
# ---------------------------------------------------------------------------


def check_aer_alerts(
    aer: AerStatus | None,
    counters: SoakCounters,
    timestamp: str,
) -> SoakCounters:
    """Check for new AER errors and emit alerts. Returns updated counters."""
    if aer is None:
        return counters

    new_uncorr = aer.uncorrectable.raw_value & ~counters.prev_uncorr_raw
    new_corr = aer.correctable.raw_value & ~counters.prev_corr_raw

    uncorr_delta = 0
    corr_delta = 0

    if new_uncorr:
        uncorr_delta = bin(new_uncorr).count("1")
        _alert(
            timestamp,
            f"UNCORRECTABLE AER ERROR detected "
            f"(new bits: 0x{new_uncorr:08X}, total raw: 0x{aer.uncorrectable.raw_value:08X})",
        )

    if new_corr:
        corr_delta = bin(new_corr).count("1")
        _alert(
            timestamp,
            f"Correctable AER error detected "
            f"(new bits: 0x{new_corr:08X}, total raw: 0x{aer.correctable.raw_value:08X})",
        )

    return SoakCounters(
        total_iterations=counters.total_iterations,
        uncorrectable_error_count=counters.uncorrectable_error_count + uncorr_delta,
        correctable_error_count=counters.correctable_error_count + corr_delta,
        link_down_events=counters.link_down_events,
        bandwidth_alerts=counters.bandwidth_alerts,
        min_ingress_bw_mbps=counters.min_ingress_bw_mbps,
        min_egress_bw_mbps=counters.min_egress_bw_mbps,
        max_ingress_bw_mbps=counters.max_ingress_bw_mbps,
        max_egress_bw_mbps=counters.max_egress_bw_mbps,
        prev_uncorr_raw=aer.uncorrectable.raw_value,
        prev_corr_raw=aer.correctable.raw_value,
        prev_link_up_ports=counters.prev_link_up_ports,
    )


def check_link_alerts(
    statuses: tuple[PortStatus, ...],
    counters: SoakCounters,
    timestamp: str,
) -> SoakCounters:
    """Check for link-down events and emit alerts. Returns updated counters."""
    current_up = frozenset(s.port_number for s in statuses if s.is_link_up)
    newly_down = counters.prev_link_up_ports - current_up
    down_events = 0

    for port in sorted(newly_down):
        down_events += 1
        _alert(timestamp, f"Link DOWN on port {port}")

    return SoakCounters(
        total_iterations=counters.total_iterations,
        uncorrectable_error_count=counters.uncorrectable_error_count,
        correctable_error_count=counters.correctable_error_count,
        link_down_events=counters.link_down_events + down_events,
        bandwidth_alerts=counters.bandwidth_alerts,
        min_ingress_bw_mbps=counters.min_ingress_bw_mbps,
        min_egress_bw_mbps=counters.min_egress_bw_mbps,
        max_ingress_bw_mbps=counters.max_ingress_bw_mbps,
        max_egress_bw_mbps=counters.max_egress_bw_mbps,
        prev_uncorr_raw=counters.prev_uncorr_raw,
        prev_corr_raw=counters.prev_corr_raw,
        prev_link_up_ports=current_up,
    )


def check_bandwidth_alerts(
    snapshot: PerfSnapshot | None,
    counters: SoakCounters,
    min_bandwidth: float,
    timestamp: str,
) -> SoakCounters:
    """Check for bandwidth drops and update min/max tracking. Returns updated counters."""
    if snapshot is None or not snapshot.port_stats:
        return counters

    bw_alerts = 0
    min_in = counters.min_ingress_bw_mbps
    min_eg = counters.min_egress_bw_mbps
    max_in = counters.max_ingress_bw_mbps
    max_eg = counters.max_egress_bw_mbps

    for ps in snapshot.port_stats:
        in_mbps = ps.ingress_bandwidth_mbps
        eg_mbps = ps.egress_bandwidth_mbps

        min_in = min(min_in, in_mbps)
        min_eg = min(min_eg, eg_mbps)
        max_in = max(max_in, in_mbps)
        max_eg = max(max_eg, eg_mbps)

        if min_bandwidth > 0 and in_mbps < min_bandwidth:
            bw_alerts += 1
            _alert(
                timestamp,
                f"Ingress bandwidth LOW on port {ps.port_number}: "
                f"{in_mbps:.2f} MB/s < {min_bandwidth:.2f} MB/s threshold",
            )
        if min_bandwidth > 0 and eg_mbps < min_bandwidth:
            bw_alerts += 1
            _alert(
                timestamp,
                f"Egress bandwidth LOW on port {ps.port_number}: "
                f"{eg_mbps:.2f} MB/s < {min_bandwidth:.2f} MB/s threshold",
            )

    return SoakCounters(
        total_iterations=counters.total_iterations,
        uncorrectable_error_count=counters.uncorrectable_error_count,
        correctable_error_count=counters.correctable_error_count,
        link_down_events=counters.link_down_events,
        bandwidth_alerts=counters.bandwidth_alerts + bw_alerts,
        min_ingress_bw_mbps=min_in,
        min_egress_bw_mbps=min_eg,
        max_ingress_bw_mbps=max_in,
        max_egress_bw_mbps=max_eg,
        prev_uncorr_raw=counters.prev_uncorr_raw,
        prev_corr_raw=counters.prev_corr_raw,
        prev_link_up_ports=counters.prev_link_up_ports,
    )


def _alert(timestamp: str, message: str) -> None:
    """Print an alert to stderr with a timestamp prefix."""
    print(f"[ALERT {timestamp}] {message}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def build_summary(counters: SoakCounters, elapsed: float) -> SoakSummary:
    """Convert mutable counters to a frozen summary."""
    return SoakSummary(
        total_iterations=counters.total_iterations,
        total_seconds=elapsed,
        uncorrectable_error_count=counters.uncorrectable_error_count,
        correctable_error_count=counters.correctable_error_count,
        link_down_events=counters.link_down_events,
        bandwidth_alerts=counters.bandwidth_alerts,
        min_ingress_bw_mbps=(
            counters.min_ingress_bw_mbps if counters.min_ingress_bw_mbps != float("inf") else 0.0
        ),
        min_egress_bw_mbps=(
            counters.min_egress_bw_mbps if counters.min_egress_bw_mbps != float("inf") else 0.0
        ),
        max_ingress_bw_mbps=counters.max_ingress_bw_mbps,
        max_egress_bw_mbps=counters.max_egress_bw_mbps,
    )


def print_summary(summary: SoakSummary) -> None:
    """Print the final soak test summary to stdout."""
    hours = summary.total_seconds / 3600
    minutes = (summary.total_seconds % 3600) / 60

    print("\n" + "=" * 60)
    print("  OVERNIGHT SOAK TEST SUMMARY")
    print("=" * 60)
    print(f"  Duration .............. {hours:.1f}h {minutes:.0f}m ({summary.total_seconds:.0f}s)")
    print(f"  Iterations ............ {summary.total_iterations}")
    print(f"  Uncorrectable errors .. {summary.uncorrectable_error_count}")
    print(f"  Correctable errors .... {summary.correctable_error_count}")
    print(f"  Link-down events ...... {summary.link_down_events}")
    print(f"  Bandwidth alerts ...... {summary.bandwidth_alerts}")
    print(
        f"  Ingress BW (MB/s) .... min={summary.min_ingress_bw_mbps:.2f}  "
        f"max={summary.max_ingress_bw_mbps:.2f}"
    )
    print(
        f"  Egress BW (MB/s) ..... min={summary.min_egress_bw_mbps:.2f}  "
        f"max={summary.max_egress_bw_mbps:.2f}"
    )
    print("=" * 60)

    if summary.uncorrectable_error_count > 0 or summary.link_down_events > 0:
        print("  RESULT: FAIL -- errors or link-down events detected")
    else:
        print("  RESULT: PASS")
    print("=" * 60 + "\n")


# ---------------------------------------------------------------------------
# Soak loop
# ---------------------------------------------------------------------------


def open_device(device_index: int) -> SwitchDevice:
    """Create and open a SwitchDevice for the given index."""
    transport = PcieTransport()
    device = SwitchDevice(transport)
    device.open(device_index)
    return device


def create_csv_writers(
    log_dir: Path,
) -> tuple[RotatingCsvWriter, RotatingCsvWriter, RotatingCsvWriter]:
    """Create rotating CSV writers for link, perf, and AER logs."""
    resolved = log_dir.resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return (
        RotatingCsvWriter(base_path=resolved / "link_status.csv", fieldnames=LINK_CSV_FIELDS),
        RotatingCsvWriter(base_path=resolved / "perf_counters.csv", fieldnames=PERF_CSV_FIELDS),
        RotatingCsvWriter(base_path=resolved / "aer_errors.csv", fieldnames=AER_CSV_FIELDS),
    )


def process_sample(
    sample: SoakSample,
    counters: SoakCounters,
    min_bandwidth: float,
    link_writer: RotatingCsvWriter,
    perf_writer: RotatingCsvWriter,
    aer_writer: RotatingCsvWriter,
) -> SoakCounters:
    """Log a sample to CSV and check all alert conditions. Returns updated counters."""
    # Log to CSV files.
    log_link_rows(link_writer, sample.timestamp, sample.link_statuses)

    if sample.perf_snapshot is not None:
        log_perf_rows(perf_writer, sample.timestamp, sample.perf_snapshot)

    if sample.aer_status is not None:
        log_aer_row(aer_writer, sample.timestamp, sample.aer_status)

    # Run alert checks (each returns a new counters instance).
    updated = check_aer_alerts(sample.aer_status, counters, sample.timestamp)
    updated = check_link_alerts(sample.link_statuses, updated, sample.timestamp)
    updated = check_bandwidth_alerts(
        sample.perf_snapshot,
        updated,
        min_bandwidth,
        sample.timestamp,
    )

    # Increment iteration count.
    return SoakCounters(
        total_iterations=updated.total_iterations + 1,
        uncorrectable_error_count=updated.uncorrectable_error_count,
        correctable_error_count=updated.correctable_error_count,
        link_down_events=updated.link_down_events,
        bandwidth_alerts=updated.bandwidth_alerts,
        min_ingress_bw_mbps=updated.min_ingress_bw_mbps,
        min_egress_bw_mbps=updated.min_egress_bw_mbps,
        max_ingress_bw_mbps=updated.max_ingress_bw_mbps,
        max_egress_bw_mbps=updated.max_egress_bw_mbps,
        prev_uncorr_raw=updated.prev_uncorr_raw,
        prev_corr_raw=updated.prev_corr_raw,
        prev_link_up_ports=updated.prev_link_up_ports,
    )


def should_stop(start_time: float, duration: float | None, stop_flag: list[bool]) -> bool:
    """Check whether the soak loop should terminate."""
    if stop_flag[0]:
        return True
    if duration is not None and (time.monotonic() - start_time) >= duration:
        return True
    return False


def run_soak(
    device_index: int,
    interval: float,
    duration: float | None,
    min_bandwidth: float,
    log_dir: Path,
) -> SoakSummary:
    """Execute the soak test loop until interrupted or duration expires.

    Opens the device, initializes monitors, and samples in a loop.
    Always closes the device and flushes CSV files on exit.
    """
    # Mutable flag toggled by the signal handler.
    stop_flag: list[bool] = [False]

    def _handle_sigint(signum: int, frame: object) -> None:
        print("\nReceived Ctrl+C, finishing current iteration...", file=sys.stderr)
        stop_flag[0] = True

    # Install Ctrl+C handler.
    original_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, _handle_sigint)

    link_writer, perf_writer, aer_writer = create_csv_writers(log_dir)
    device: SwitchDevice | None = None
    counters = SoakCounters()
    start_time = time.monotonic()

    try:
        # Open device and build managers.
        device = open_device(device_index)
        device_obj = device._require_open()
        device_key = device.device_key

        if device_key is None:
            raise CalypsoError("Device key unavailable after open.")

        info = device.device_info
        chip_label = f"0x{info.chip_type:04X}" if info else "unknown"
        print(f"Soak test started on device {device_index} (chip {chip_label})")
        print(f"  Interval: {interval}s | Min BW: {min_bandwidth} MB/s | Logs: {log_dir.resolve()}")
        if duration is not None:
            print(f"  Duration limit: {duration}s")
        print("  Press Ctrl+C to stop.\n")

        port_manager = PortManager(device_obj, device_key)
        config_reader = PcieConfigReader(device_obj, device_key)
        perf_monitor = PerfMonitor(device_obj, device_key)

        # Initialize and start performance counters.
        perf_monitor.initialize()
        perf_monitor.start()

        # Capture initial link-up set so first iteration does not
        # false-alert on ports that were already down.
        initial_statuses = collect_link_statuses(port_manager)
        counters = SoakCounters(
            prev_link_up_ports=frozenset(s.port_number for s in initial_statuses if s.is_link_up),
        )

        # Main sampling loop.
        iteration = 0
        while not should_stop(start_time, duration, stop_flag):
            sample = take_sample(iteration, port_manager, perf_monitor, config_reader)

            counters = process_sample(
                sample,
                counters,
                min_bandwidth,
                link_writer,
                perf_writer,
                aer_writer,
            )

            print(
                f"  [{sample.timestamp}] iteration={iteration}  "
                f"ports={len(sample.link_statuses)}  "
                f"uncorr=0x{counters.prev_uncorr_raw:08X}  "
                f"corr=0x{counters.prev_corr_raw:08X}"
            )

            iteration += 1

            # Sleep in small increments so Ctrl+C is responsive.
            sleep_until = time.monotonic() + interval
            while time.monotonic() < sleep_until:
                if stop_flag[0]:
                    break
                time.sleep(min(0.5, interval))

    except CalypsoError as exc:
        logger.error("soak_error", detail=str(exc))
        print(f"Error: {exc}", file=sys.stderr)
    finally:
        # Always flush CSV and close the device.
        link_writer.close()
        perf_writer.close()
        aer_writer.close()

        if device is not None:
            try:
                perf_monitor.stop()
            except Exception:
                pass
            device.close()

        signal.signal(signal.SIGINT, original_handler)

    elapsed = time.monotonic() - start_time
    return build_summary(counters, elapsed)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the overnight soak test."""
    parser = argparse.ArgumentParser(
        description=(
            "Overnight soak test for Atlas3 PCIe switches. "
            "Monitors AER errors, bandwidth, and link state continuously."
        ),
    )
    parser.add_argument(
        "device_index",
        type=int,
        help="Zero-based index of the Atlas3 device (matches 'calypso scan' order).",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=10.0,
        help="Sampling interval in seconds (default: 10).",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Maximum test duration in seconds. Runs until Ctrl+C if omitted.",
    )
    parser.add_argument(
        "--min-bandwidth",
        type=float,
        default=0.0,
        help="Minimum bandwidth threshold in MB/s. Alerts if any port drops below.",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=Path("./soak_logs"),
        help="Directory for rotating CSV log files (default: ./soak_logs/).",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Entry point: run the overnight soak test and print a summary."""
    args = parse_args(argv)

    try:
        summary = run_soak(
            device_index=args.device_index,
            interval=args.interval,
            duration=args.duration,
            min_bandwidth=args.min_bandwidth,
            log_dir=args.log_dir,
        )
    except KeyboardInterrupt:
        # Fallback if signal handler was not yet installed.
        print("\nInterrupted before soak loop started.", file=sys.stderr)
        return 130

    print_summary(summary)

    # Exit code 1 if any critical issues were detected.
    if summary.uncorrectable_error_count > 0 or summary.link_down_events > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
