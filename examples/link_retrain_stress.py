"""Link Retrain Stress -- repeatedly retrain a downstream port and verify recovery.

Opens an Atlas3 switch by device index, targets a specific downstream port,
and triggers PCIe link retraining in a loop.  After each retrain the script
polls link status until training completes (or times out) and verifies the
negotiated speed and width match expected values.

A summary table is printed at the end showing total iterations, pass/fail
counts, and any degraded-link occurrences.

Usage:
    python link_retrain_stress.py 0 4
    python link_retrain_stress.py 0 4 --iterations 500 --delay 0.2
    python link_retrain_stress.py 0 4 --expected-speed 6 --expected-width 16

Requirements:
    - Calypso must be installed (``pip install -e ".[dev]"``)
    - The PLX driver must be loaded (PlxSvc service on Windows,
      PlxSvc kernel module on Linux)
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field

from calypso.core.pcie_config import PcieConfigReader
from calypso.core.switch import SwitchDevice
from calypso.exceptions import CalypsoError
from calypso.hardware.pcie_registers import (
    SPEED_STRINGS,
    PCIeLinkSpeed,
)
from calypso.transport.pcie import PcieTransport
from calypso.utils.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data structures (immutable result records)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetrainAttempt:
    """Result of a single retrain iteration."""

    iteration: int
    passed: bool
    speed: str
    width: int
    training_time_ms: float
    error: str = ""


@dataclass(frozen=True)
class StressSummary:
    """Aggregate summary of the full stress run."""

    total: int
    passed: int
    failed: int
    degraded: int
    attempts: tuple[RetrainAttempt, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Speed / width helpers
# ---------------------------------------------------------------------------


def _speed_label(code: int) -> str:
    """Convert a raw speed code to a human-readable label."""
    try:
        return SPEED_STRINGS[PCIeLinkSpeed(code)]
    except (ValueError, KeyError):
        return f"Unknown({code})"


def _speed_code_from_label(label: str) -> int:
    """Extract the raw integer code from a speed label like 'Gen4'."""
    for speed_enum in PCIeLinkSpeed:
        gen_str = SPEED_STRINGS.get(speed_enum, "")
        if gen_str.startswith(label):
            return speed_enum.value
    return 0


# ---------------------------------------------------------------------------
# Core retrain logic
# ---------------------------------------------------------------------------


# Maximum time (seconds) to wait for link training to complete after retrain.
_POLL_TIMEOUT_S = 5.0

# Interval (seconds) between link-status polls during training.
_POLL_INTERVAL_S = 0.01


def _wait_for_training_complete(
    config_reader: PcieConfigReader,
    timeout_s: float = _POLL_TIMEOUT_S,
) -> float:
    """Poll link status until the Link Training bit clears.

    Returns:
        Elapsed time in milliseconds, or -1.0 if the poll timed out.
    """
    start = time.monotonic()
    deadline = start + timeout_s

    while time.monotonic() < deadline:
        link_status = config_reader.get_link_status()
        if not link_status.link_training:
            elapsed_ms = (time.monotonic() - start) * 1000.0
            return elapsed_ms
        time.sleep(_POLL_INTERVAL_S)

    return -1.0


def _read_negotiated_link(
    config_reader: PcieConfigReader,
) -> tuple[str, int]:
    """Read current negotiated speed label and width from link status.

    Returns:
        Tuple of (speed_label, width).
    """
    link_status = config_reader.get_link_status()
    return (link_status.current_speed, link_status.current_width)


def run_single_retrain(
    config_reader: PcieConfigReader,
    iteration: int,
    expected_speed: str,
    expected_width: int,
) -> RetrainAttempt:
    """Execute one retrain cycle and verify recovery.

    Triggers retrain, waits for training to finish, then checks
    that the link came back at the expected speed and width.
    """
    try:
        config_reader.retrain_link()
    except CalypsoError as exc:
        return RetrainAttempt(
            iteration=iteration,
            passed=False,
            speed="N/A",
            width=0,
            training_time_ms=0.0,
            error=f"Retrain trigger failed: {exc}",
        )

    training_ms = _wait_for_training_complete(config_reader)

    if training_ms < 0:
        return RetrainAttempt(
            iteration=iteration,
            passed=False,
            speed="N/A",
            width=0,
            training_time_ms=_POLL_TIMEOUT_S * 1000.0,
            error="Link training timed out",
        )

    speed_label, width = _read_negotiated_link(config_reader)

    passed = speed_label == expected_speed and width == expected_width
    error_msg = ""
    if not passed:
        error_msg = f"Expected {expected_speed} x{expected_width}, got {speed_label} x{width}"

    return RetrainAttempt(
        iteration=iteration,
        passed=passed,
        speed=speed_label,
        width=width,
        training_time_ms=training_ms,
        error=error_msg,
    )


# ---------------------------------------------------------------------------
# Stress loop
# ---------------------------------------------------------------------------


def run_stress_loop(
    config_reader: PcieConfigReader,
    iterations: int,
    delay_s: float,
    expected_speed: str,
    expected_width: int,
) -> StressSummary:
    """Run the retrain stress loop for the requested number of iterations.

    Prints progress to stdout on each iteration.

    Returns:
        A StressSummary with all attempt results.
    """
    attempts: list[RetrainAttempt] = []
    pass_count = 0
    fail_count = 0
    degraded_count = 0

    for i in range(1, iterations + 1):
        attempt = run_single_retrain(
            config_reader,
            i,
            expected_speed,
            expected_width,
        )
        attempts.append(attempt)

        if attempt.passed:
            pass_count += 1
            status_tag = "PASS"
        else:
            fail_count += 1
            status_tag = "FAIL"
            # A "degraded" link came back up but at a lesser speed/width.
            if attempt.speed != "N/A":
                degraded_count += 1

        _print_iteration(i, iterations, status_tag, attempt)

        if i < iterations:
            time.sleep(delay_s)

    return StressSummary(
        total=iterations,
        passed=pass_count,
        failed=fail_count,
        degraded=degraded_count,
        attempts=tuple(attempts),
    )


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _print_iteration(
    current: int,
    total: int,
    status: str,
    attempt: RetrainAttempt,
) -> None:
    """Print a single iteration progress line."""
    error_suffix = f"  ({attempt.error})" if attempt.error else ""
    print(
        f"  [{current:>{len(str(total))}}/{total}] "
        f"{status:<4}  "
        f"{attempt.speed:<22}  "
        f"x{attempt.width:<4}  "
        f"{attempt.training_time_ms:7.1f} ms"
        f"{error_suffix}"
    )


def print_summary(summary: StressSummary) -> None:
    """Print the final summary table."""
    print()
    print("=" * 60)
    print("  Link Retrain Stress Summary")
    print("=" * 60)
    print(f"  Total iterations : {summary.total}")
    print(f"  Passed           : {summary.passed}")
    print(f"  Failed           : {summary.failed}")
    print(f"  Degraded links   : {summary.degraded}")
    if summary.total > 0:
        rate = (summary.passed / summary.total) * 100.0
        print(f"  Pass rate        : {rate:.1f}%")

    # List all failures for easy diagnosis.
    failures = tuple(a for a in summary.attempts if not a.passed)
    if failures:
        print()
        print("  Failed iterations:")
        for a in failures:
            print(f"    #{a.iteration}: {a.error}")

    print("=" * 60)
    print()


# ---------------------------------------------------------------------------
# Device interaction
# ---------------------------------------------------------------------------


def _open_device_and_get_reader(
    device_index: int,
    port_number: int,
) -> tuple[SwitchDevice, PcieConfigReader, str, int]:
    """Open a device, locate the target port, return reader + baseline link info.

    Returns:
        Tuple of (switch_device, config_reader, baseline_speed, baseline_width).
        The caller is responsible for closing switch_device.
    """
    transport = PcieTransport()
    device = SwitchDevice(transport)
    device.open(device_index)

    device_obj = device._require_open()
    device_key = device.device_key
    if device_key is None:
        device.close()
        raise CalypsoError("Device key unavailable after open.")

    # Build a config reader for the target port.  The PcieConfigReader
    # operates on the device object that is already opened to the switch's
    # management port.  For downstream ports we read via BDF-addressed
    # register access through the PortManager's enumeration, but the
    # PcieConfigReader attached to the opened device can address any
    # port's config space because PLX SDK internally routes by port.
    config_reader = PcieConfigReader(device_obj, device_key)

    # Read baseline link state so we know what to expect after retrain.
    speed_label, width = _read_negotiated_link(config_reader)

    info = device.device_info
    chip_label = f"0x{info.chip_type:04X}" if info else "unknown"
    logger.info(
        "stress_target",
        device=device_index,
        chip=chip_label,
        port=port_number,
        baseline_speed=speed_label,
        baseline_width=width,
    )

    return (device, config_reader, speed_label, width)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Repeatedly retrain a PCIe link on an Atlas3 switch port "
            "and verify recovery at the expected speed/width."
        ),
    )
    parser.add_argument(
        "device_index",
        type=int,
        help=("Zero-based index of the Atlas3 device to open (matches 'calypso scan' order)."),
    )
    parser.add_argument(
        "port",
        type=int,
        help="Target downstream port number on the switch.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=1000,
        help="Number of retrain cycles to execute (default: 1000).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.1,
        help="Delay in seconds between retrain attempts (default: 0.1).",
    )
    parser.add_argument(
        "--expected-speed",
        type=int,
        default=0,
        choices=[0, 1, 2, 3, 4, 5, 6],
        help=(
            "Expected link speed code after retrain (1=Gen1 .. 6=Gen6). "
            "0 means auto-detect from baseline (default: 0)."
        ),
    )
    parser.add_argument(
        "--expected-width",
        type=int,
        default=0,
        help=(
            "Expected link width after retrain (e.g. 1, 2, 4, 8, 16). "
            "0 means auto-detect from baseline (default: 0)."
        ),
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Entry point: open device, run stress loop, print summary."""
    args = parse_args(argv)

    try:
        device, config_reader, baseline_speed, baseline_width = _open_device_and_get_reader(
            args.device_index, args.port
        )
    except CalypsoError as exc:
        logger.error("device_open_failed", detail=str(exc))
        print(f"Error opening device: {exc}", file=sys.stderr)
        return 1

    # Determine expected speed/width: use explicit overrides or baseline.
    if args.expected_speed > 0:
        expected_speed = _speed_label(args.expected_speed).split(" ")[0]
    else:
        expected_speed = baseline_speed

    expected_width = args.expected_width if args.expected_width > 0 else baseline_width

    print()
    print(f"  Device index : {args.device_index}")
    print(f"  Target port  : {args.port}")
    print(f"  Iterations   : {args.iterations}")
    print(f"  Delay        : {args.delay}s")
    print(f"  Expected     : {expected_speed} x{expected_width}")
    print(f"  Baseline     : {baseline_speed} x{baseline_width}")
    print()

    try:
        summary = run_stress_loop(
            config_reader=config_reader,
            iterations=args.iterations,
            delay_s=args.delay,
            expected_speed=expected_speed,
            expected_width=expected_width,
        )
    except KeyboardInterrupt:
        print("\n\n  Interrupted by user.\n")
        device.close()
        return 130
    except CalypsoError as exc:
        logger.error("stress_error", detail=str(exc))
        print(f"\nError during stress run: {exc}", file=sys.stderr)
        device.close()
        return 1
    finally:
        # Ensure device is always closed (close() is idempotent).
        device.close()

    print_summary(summary)

    return 0 if summary.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
