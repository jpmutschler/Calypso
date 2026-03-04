"""Speed Downshift Sweep — systematically test link operation at each PCIe speed tier.

Opens a device by index, targets a specific port, and walks the link speed
from Gen6 (64 GT/s) down to Gen1 (2.5 GT/s).  At each speed tier the script:

  1. Writes the Target Link Speed to Link Control 2
  2. Triggers a link retrain via Link Control
  3. Validates the link comes up at the expected speed and width
  4. Runs a short bandwidth measurement
  5. Checks AER for errors introduced by the speed change
  6. Records PASS / FAIL per tier

A summary table is printed at the end and optionally saved to JSON.

Usage:
    python speed_downshift_sweep.py 0 0
    python speed_downshift_sweep.py 0 0 --settle 2.0 --sample-time 1.5
    python speed_downshift_sweep.py 0 0 --output results.json

Prerequisites:
    - Calypso installed: ``pip install -e ".[dev]"``
    - PLX driver loaded (PlxSvc service on Windows, PlxSvc module on Linux)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from calypso.core.pcie_config import PcieConfigReader
from calypso.core.perf_monitor import PerfMonitor
from calypso.core.switch import SwitchDevice
from calypso.exceptions import CalypsoError
from calypso.models.pcie_config import AerStatus, SupportedSpeedsVector
from calypso.transport.pcie import PcieTransport
from calypso.utils.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Speed tier definitions
# ---------------------------------------------------------------------------

# Speed code -> (generation label, line rate string)
SPEED_TIERS: tuple[tuple[int, str, str], ...] = (
    (6, "Gen6", "64.0 GT/s"),
    (5, "Gen5", "32.0 GT/s"),
    (4, "Gen4", "16.0 GT/s"),
    (3, "Gen3", "8.0 GT/s"),
    (2, "Gen2", "5.0 GT/s"),
    (1, "Gen1", "2.5 GT/s"),
)


# ---------------------------------------------------------------------------
# Immutable result records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BandwidthSample:
    """Bandwidth measurement captured at a specific speed tier."""

    ingress_byte_rate: float = 0.0
    egress_byte_rate: float = 0.0
    ingress_utilization: float = 0.0
    egress_utilization: float = 0.0


@dataclass(frozen=True)
class AerSnapshot:
    """AER error state captured after a speed change."""

    uncorrectable_raw: int = 0
    correctable_raw: int = 0
    has_errors: bool = False


@dataclass(frozen=True)
class SpeedTierResult:
    """Result of testing a single speed tier."""

    speed_code: int
    gen_label: str
    rate_label: str
    supported: bool
    passed: bool
    actual_speed: str = ""
    actual_width: int = 0
    link_up: bool = False
    bandwidth: BandwidthSample = field(default_factory=BandwidthSample)
    aer: AerSnapshot = field(default_factory=AerSnapshot)
    error_detail: str = ""


@dataclass(frozen=True)
class SweepResult:
    """Complete sweep result across all speed tiers."""

    device_index: int
    port_number: int
    chip_type: str
    tiers: tuple[SpeedTierResult, ...] = ()


# ---------------------------------------------------------------------------
# Helpers — supported speed detection
# ---------------------------------------------------------------------------


def _get_supported_speed_codes(speeds: SupportedSpeedsVector) -> frozenset[int]:
    """Extract the set of supported speed codes from the capability vector."""
    flags = {
        1: speeds.gen1,
        2: speeds.gen2,
        3: speeds.gen3,
        4: speeds.gen4,
        5: speeds.gen5,
        6: speeds.gen6,
    }
    return frozenset(code for code, supported in flags.items() if supported)


# ---------------------------------------------------------------------------
# Helpers — AER checking
# ---------------------------------------------------------------------------


def _capture_aer(reader: PcieConfigReader) -> AerSnapshot:
    """Read AER status and return an immutable snapshot."""
    aer: AerStatus | None = reader.get_aer_status()
    if aer is None:
        return AerSnapshot()
    return AerSnapshot(
        uncorrectable_raw=aer.uncorrectable.raw_value,
        correctable_raw=aer.correctable.raw_value,
        has_errors=(aer.uncorrectable.raw_value != 0 or aer.correctable.raw_value != 0),
    )


# ---------------------------------------------------------------------------
# Helpers — bandwidth sampling
# ---------------------------------------------------------------------------


def _measure_bandwidth(
    monitor: PerfMonitor,
    port_number: int,
    sample_time: float,
) -> BandwidthSample:
    """Run a short bandwidth sample and return the result for the target port.

    Takes two snapshots separated by ``sample_time`` seconds so the SDK
    counters accumulate a measurable delta.
    """
    monitor.start()
    # Discard initial baseline snapshot.
    monitor.read_snapshot()
    time.sleep(sample_time)
    snapshot = monitor.read_snapshot()
    monitor.stop()

    for stats in snapshot.port_stats:
        if stats.port_number == port_number:
            return BandwidthSample(
                ingress_byte_rate=stats.ingress_payload_byte_rate,
                egress_byte_rate=stats.egress_payload_byte_rate,
                ingress_utilization=stats.ingress_link_utilization,
                egress_utilization=stats.egress_link_utilization,
            )

    return BandwidthSample()


# ---------------------------------------------------------------------------
# Core — test a single speed tier
# ---------------------------------------------------------------------------


def _test_speed_tier(
    reader: PcieConfigReader,
    monitor: PerfMonitor,
    speed_code: int,
    gen_label: str,
    rate_label: str,
    supported_codes: frozenset[int],
    port_number: int,
    settle_time: float,
    sample_time: float,
) -> SpeedTierResult:
    """Set target link speed, retrain, validate, measure, and check AER."""
    if speed_code not in supported_codes:
        return SpeedTierResult(
            speed_code=speed_code,
            gen_label=gen_label,
            rate_label=rate_label,
            supported=False,
            passed=False,
            error_detail="Speed not supported by device",
        )

    # Clear AER before the speed change so we only see new errors.
    reader.clear_aer_errors()

    try:
        reader.set_target_link_speed(speed_code)
        reader.retrain_link()
    except CalypsoError as exc:
        return SpeedTierResult(
            speed_code=speed_code,
            gen_label=gen_label,
            rate_label=rate_label,
            supported=True,
            passed=False,
            error_detail=f"Retrain failed: {exc}",
        )

    # Wait for link training to settle.
    time.sleep(settle_time)

    # Read back link status.
    link_status = reader.get_link_status()
    actual_speed = link_status.current_speed
    actual_width = link_status.current_width
    link_up = actual_width > 0

    # Check AER for errors caused by the speed change.
    aer = _capture_aer(reader)

    # Measure bandwidth (only meaningful if link is up).
    bandwidth = BandwidthSample()
    if link_up:
        try:
            bandwidth = _measure_bandwidth(monitor, port_number, sample_time)
        except CalypsoError:
            logger.warning("bandwidth_measure_failed", speed=gen_label)

    # Determine pass/fail: link must be up at the requested speed, no uncorrectable errors.
    speed_ok = actual_speed == gen_label
    passed = link_up and speed_ok and (aer.uncorrectable_raw == 0)

    error_parts: list[str] = []
    if not link_up:
        error_parts.append("Link down")
    if not speed_ok:
        error_parts.append(f"Speed mismatch (got {actual_speed})")
    if aer.uncorrectable_raw != 0:
        error_parts.append(f"Uncorrectable AER 0x{aer.uncorrectable_raw:08X}")
    if aer.correctable_raw != 0:
        error_parts.append(f"Correctable AER 0x{aer.correctable_raw:08X}")

    return SpeedTierResult(
        speed_code=speed_code,
        gen_label=gen_label,
        rate_label=rate_label,
        supported=True,
        passed=passed,
        actual_speed=actual_speed,
        actual_width=actual_width,
        link_up=link_up,
        bandwidth=bandwidth,
        aer=aer,
        error_detail="; ".join(error_parts),
    )


# ---------------------------------------------------------------------------
# Display — summary table
# ---------------------------------------------------------------------------

SUMMARY_COLUMNS: tuple[tuple[str, int, str], ...] = (
    ("Result", 8, "<"),
    ("Speed", 8, "<"),
    ("Rate", 12, "<"),
    ("Width", 7, ">"),
    ("Ingress B/s", 14, ">"),
    ("Egress B/s", 14, ">"),
    ("AER Uncorr", 12, ">"),
    ("AER Corr", 12, ">"),
    ("Detail", 40, "<"),
)


def _format_rate(bytes_per_sec: float) -> str:
    """Format a byte rate with human-readable units."""
    if bytes_per_sec < 1_000:
        return f"{bytes_per_sec:.0f} B/s"
    if bytes_per_sec < 1_000_000:
        return f"{bytes_per_sec / 1_000:.1f} KB/s"
    if bytes_per_sec < 1_000_000_000:
        return f"{bytes_per_sec / 1_000_000:.2f} MB/s"
    return f"{bytes_per_sec / 1_000_000_000:.2f} GB/s"


def _build_summary_header() -> str:
    """Build the column header row."""
    parts = tuple(f"{name:{align}{width}}" for name, width, align in SUMMARY_COLUMNS)
    return "  ".join(parts)


def _build_summary_separator() -> str:
    """Build a separator matching the header width."""
    parts = tuple("-" * width for _, width, _ in SUMMARY_COLUMNS)
    return "  ".join(parts)


def _format_tier_row(tier: SpeedTierResult) -> str:
    """Format a single speed tier result as a table row."""
    tag = "PASS" if tier.passed else ("SKIP" if not tier.supported else "FAIL")
    width_str = f"x{tier.actual_width}" if tier.link_up else "---"
    ingress_str = _format_rate(tier.bandwidth.ingress_byte_rate) if tier.link_up else "---"
    egress_str = _format_rate(tier.bandwidth.egress_byte_rate) if tier.link_up else "---"
    uncorr_str = f"0x{tier.aer.uncorrectable_raw:08X}" if tier.supported else "---"
    corr_str = f"0x{tier.aer.correctable_raw:08X}" if tier.supported else "---"
    detail = tier.error_detail[:40] if tier.error_detail else ""

    return "  ".join(
        (
            f"{tag:<8}",
            f"{tier.gen_label:<8}",
            f"{tier.rate_label:<12}",
            f"{width_str:>7}",
            f"{ingress_str:>14}",
            f"{egress_str:>14}",
            f"{uncorr_str:>12}",
            f"{corr_str:>12}",
            f"{detail:<40}",
        )
    )


def print_summary(result: SweepResult) -> None:
    """Print the full sweep summary table to stdout."""
    print(
        f"\n  Speed Downshift Sweep — Device {result.device_index}, "
        f"Port {result.port_number}, Chip {result.chip_type}"
    )
    print()
    print(f"  {_build_summary_header()}")
    print(f"  {_build_summary_separator()}")
    for tier in result.tiers:
        print(f"  {_format_tier_row(tier)}")
    print(f"  {_build_summary_separator()}")

    passed = sum(1 for t in result.tiers if t.passed)
    tested = sum(1 for t in result.tiers if t.supported)
    skipped = sum(1 for t in result.tiers if not t.supported)
    failed = tested - passed
    print(f"\n  {passed} passed, {failed} failed, {skipped} skipped ({tested} tiers tested)\n")


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------


def _tier_to_dict(tier: SpeedTierResult) -> dict[str, object]:
    """Convert a SpeedTierResult to a JSON-serializable dict."""
    return {
        "speed_code": tier.speed_code,
        "gen_label": tier.gen_label,
        "rate_label": tier.rate_label,
        "supported": tier.supported,
        "passed": tier.passed,
        "actual_speed": tier.actual_speed,
        "actual_width": tier.actual_width,
        "link_up": tier.link_up,
        "bandwidth": {
            "ingress_byte_rate": tier.bandwidth.ingress_byte_rate,
            "egress_byte_rate": tier.bandwidth.egress_byte_rate,
            "ingress_utilization": tier.bandwidth.ingress_utilization,
            "egress_utilization": tier.bandwidth.egress_utilization,
        },
        "aer": {
            "uncorrectable_raw": f"0x{tier.aer.uncorrectable_raw:08X}",
            "correctable_raw": f"0x{tier.aer.correctable_raw:08X}",
            "has_errors": tier.aer.has_errors,
        },
        "error_detail": tier.error_detail,
    }


def write_json(result: SweepResult, path: Path) -> Path:
    """Write the sweep result to a JSON file. Returns the resolved path."""
    resolved = path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "device_index": result.device_index,
        "port_number": result.port_number,
        "chip_type": result.chip_type,
        "tiers": [_tier_to_dict(t) for t in result.tiers],
    }

    with resolved.open("w") as fh:
        json.dump(payload, fh, indent=2)

    return resolved


# ---------------------------------------------------------------------------
# Sweep orchestration
# ---------------------------------------------------------------------------


def run_sweep(
    device_index: int,
    port_number: int,
    settle_time: float,
    sample_time: float,
    output_path: Path | None,
) -> int:
    """Execute the full speed downshift sweep. Returns an exit code."""
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
    print(f"\n  Device {device_index} opened  |  Chip: {chip_label}")
    print(f"  Target port: {port_number}")
    print(f"  Settle time: {settle_time}s  |  Sample time: {sample_time}s\n")

    reader = PcieConfigReader(device_obj, device_key)
    monitor = PerfMonitor(device_obj, device_key)
    monitor.initialize()

    # Determine which speeds the device supports.
    supported_speeds = reader.get_supported_speeds()
    supported_codes = _get_supported_speed_codes(supported_speeds)
    print(f"  Supported speeds: {supported_speeds.max_supported} and below")
    print(f"  Speed vector: {', '.join(f'Gen{c}' for c in sorted(supported_codes))}\n")

    # Record the original link state so we can restore it at the end.
    original_link = reader.get_link_status()
    original_target_code = _parse_gen_to_code(original_link.target_speed)

    # Walk each tier from highest to lowest.
    tier_results: list[SpeedTierResult] = []
    for speed_code, gen_label, rate_label in SPEED_TIERS:
        print(f"  [{gen_label}] Testing {rate_label} ...", end="", flush=True)

        result = _test_speed_tier(
            reader=reader,
            monitor=monitor,
            speed_code=speed_code,
            gen_label=gen_label,
            rate_label=rate_label,
            supported_codes=supported_codes,
            port_number=port_number,
            settle_time=settle_time,
            sample_time=sample_time,
        )
        tier_results.append(result)

        tag = "PASS" if result.passed else ("SKIP" if not result.supported else "FAIL")
        print(f" {tag}")

    # Restore original target speed.
    _restore_original_speed(reader, original_target_code)

    sweep = SweepResult(
        device_index=device_index,
        port_number=port_number,
        chip_type=chip_label,
        tiers=tuple(tier_results),
    )

    device.close()

    print_summary(sweep)

    if output_path is not None:
        resolved = write_json(sweep, output_path)
        print(f"  JSON results written to {resolved}\n")

    return 0


def _parse_gen_to_code(gen_label: str) -> int:
    """Convert a generation label (e.g. 'Gen4') to a speed code (e.g. 4)."""
    gen_map = {"Gen1": 1, "Gen2": 2, "Gen3": 3, "Gen4": 4, "Gen5": 5, "Gen6": 6}
    return gen_map.get(gen_label, 6)


def _restore_original_speed(reader: PcieConfigReader, speed_code: int) -> None:
    """Best-effort restore of the original target link speed and retrain."""
    try:
        reader.set_target_link_speed(speed_code)
        reader.retrain_link()
    except CalypsoError:
        logger.warning("restore_speed_failed", target=speed_code)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Speed Downshift Sweep for Atlas3 PCIe switches. "
            "Tests link operation at each supported speed tier from Gen6 down to Gen1."
        ),
    )
    parser.add_argument(
        "device_index",
        type=int,
        help="Zero-based index of the Atlas3 device (matches 'calypso scan' order).",
    )
    parser.add_argument(
        "port_number",
        type=int,
        help="Port number to target for the speed sweep.",
    )
    parser.add_argument(
        "--settle",
        type=float,
        default=2.0,
        help="Seconds to wait after retrain for link to settle (default: 2.0).",
    )
    parser.add_argument(
        "--sample-time",
        type=float,
        default=1.0,
        help="Seconds for each bandwidth sample interval (default: 1.0).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path to write JSON results file.",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse args and run the speed downshift sweep."""
    args = parse_args(argv)

    if args.settle <= 0:
        print("Error: --settle must be positive.", file=sys.stderr)
        return 1

    if args.sample_time <= 0:
        print("Error: --sample-time must be positive.", file=sys.stderr)
        return 1

    return run_sweep(
        device_index=args.device_index,
        port_number=args.port_number,
        settle_time=args.settle,
        sample_time=args.sample_time,
        output_path=args.output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
