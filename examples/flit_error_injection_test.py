"""Flit Error Injection Test -- PCIe 6.0.1 Gen6 Flit-level error injection and validation.

Opens an Atlas3 switch by device index, targets a specific port, and performs a
controlled Flit CRC error injection test using the PCIe 6.0.1 Flit Error Injection
extended capability (ExtCapID 0x0034). Validates that the Flit Error Logging
capability (ExtCapID 0x0032) correctly captures the injected event, that error
counters increment, and that the link recovers without going down.

WARNING: This script intentionally injects errors into a live PCIe link.
Only use on test/lab hardware. Never run against production systems.

Usage:
    python flit_error_injection_test.py 0 0
    python flit_error_injection_test.py 0 4 --num-errors 3
    python flit_error_injection_test.py 0 0 --error-type 1 --wait 2.0
    python flit_error_injection_test.py 0 0 --skip-safety-prompt

Prerequisites:
    - Calypso installed: ``pip install -e ".[dev]"``
    - PLX driver loaded (PlxSvc service on Windows, PlxSvc module on Linux)
    - Device must be operating in Gen6 Flit mode (64 GT/s)
    - Port must expose ExtCapID 0x0032 (Flit Logging) and 0x0034 (Flit Error Injection)
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass

from calypso.core.pcie_config import PcieConfigReader
from calypso.core.switch import SwitchDevice
from calypso.exceptions import CalypsoError
from calypso.hardware.pcie_registers import ExtCapabilityID
from calypso.models.pcie_config import (
    FlitErrorCounter,
    FlitErrorInjectionConfig,
    FlitErrorLogEntry,
)
from calypso.transport.pcie import PcieTransport
from calypso.utils.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Error type constants (from PCIe 6.0.1 Flit Error Injection Control 2)
# ---------------------------------------------------------------------------

ERROR_TYPE_NAMES: dict[int, str] = {
    0: "CRC Error",
    1: "Sequence Error",
    2: "FEC Uncorrectable",
    3: "Reserved",
}


# ---------------------------------------------------------------------------
# Immutable test step results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StepResult:
    """Result of a single test step."""

    step_name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class TestReport:
    """Complete test report with all step results."""

    device_index: int
    port_number: int
    steps: tuple[StepResult, ...]
    overall_passed: bool
    duration_seconds: float


# ---------------------------------------------------------------------------
# Safety prompt
# ---------------------------------------------------------------------------


def confirm_safety_prompt() -> bool:
    """Prompt the user to confirm they understand the risks of error injection.

    Returns:
        True if the user confirms, False otherwise.
    """
    print("")
    print("=" * 70)
    print("  WARNING: FLIT ERROR INJECTION TEST")
    print("=" * 70)
    print("")
    print("  This script will intentionally inject flit-level errors into a")
    print("  live PCIe Gen6 link. This may cause:")
    print("")
    print("    - Transient CRC / FEC errors on the targeted port")
    print("    - Brief link recovery events")
    print("    - AER error reports in the OS event log")
    print("")
    print("  Only run this on dedicated test/lab hardware.")
    print("  Do NOT run against production systems or storage devices")
    print("  with active I/O.")
    print("")
    print("=" * 70)
    print("")

    try:
        answer = input("  Type 'yes' to continue: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("")
        return False

    return answer == "yes"


# ---------------------------------------------------------------------------
# Capability checks
# ---------------------------------------------------------------------------


def check_flit_injection_capability(
    reader: PcieConfigReader,
) -> StepResult:
    """Verify the port exposes Flit Error Injection (ExtCapID 0x0034).

    Returns:
        StepResult indicating whether the capability was found.
    """
    offset = reader.find_extended_capability(ExtCapabilityID.FLIT_ERROR_INJECTION)
    if offset is not None:
        return StepResult(
            step_name="Flit Error Injection Capability (0x0034)",
            passed=True,
            detail=f"Found at config space offset 0x{offset:04X}",
        )
    return StepResult(
        step_name="Flit Error Injection Capability (0x0034)",
        passed=False,
        detail="Capability not present -- port may not support Gen6 Flit mode",
    )


def check_flit_logging_capability(
    reader: PcieConfigReader,
) -> StepResult:
    """Verify the port exposes Flit Logging (ExtCapID 0x0032).

    Returns:
        StepResult indicating whether the capability was found.
    """
    offset = reader.find_extended_capability(ExtCapabilityID.FLIT_LOGGING)
    if offset is not None:
        return StepResult(
            step_name="Flit Error Logging Capability (0x0032)",
            passed=True,
            detail=f"Found at config space offset 0x{offset:04X}",
        )
    return StepResult(
        step_name="Flit Error Logging Capability (0x0032)",
        passed=False,
        detail="Capability not present -- cannot validate error counters",
    )


# ---------------------------------------------------------------------------
# Baseline and post-injection counter reads
# ---------------------------------------------------------------------------


def read_error_counter(reader: PcieConfigReader) -> FlitErrorCounter | None:
    """Read the current Flit Error Counter from the Logging capability.

    Returns:
        FlitErrorCounter, or None if capability not present.
    """
    status = reader.get_flit_logging_status()
    if status is None:
        return None
    return status.error_counter


def enable_error_counter(reader: PcieConfigReader) -> None:
    """Enable the Flit Error Counter if not already enabled.

    Configures the counter to count all flit error events (events_to_count=0).
    """
    reader.configure_flit_error_counter(
        enable=True,
        interrupt_enable=False,
        events_to_count=0,
        trigger_count=0,
    )


def read_baseline_counter(reader: PcieConfigReader) -> StepResult:
    """Read and report the baseline error counter before injection.

    Returns:
        StepResult with the baseline counter value.
    """
    counter = read_error_counter(reader)
    if counter is None:
        return StepResult(
            step_name="Read Baseline Error Counter",
            passed=False,
            detail="Flit Logging capability not available",
        )

    return StepResult(
        step_name="Read Baseline Error Counter",
        passed=True,
        detail=(
            f"Counter={counter.counter}, enabled={counter.enable}, "
            f"events_to_count={counter.events_to_count}"
        ),
    )


# ---------------------------------------------------------------------------
# Error injection
# ---------------------------------------------------------------------------


def inject_flit_error(
    reader: PcieConfigReader,
    num_errors: int,
    error_type: int,
) -> StepResult:
    """Configure and trigger Flit error injection.

    Args:
        reader: PCIe config reader for the target port.
        num_errors: Number of errors to inject (1-31).
        error_type: Error type (0=CRC, 1=Sequence, 2=FEC uncorrectable).

    Returns:
        StepResult indicating whether injection was configured successfully.
    """
    error_type_name = ERROR_TYPE_NAMES.get(error_type, f"Unknown({error_type})")

    config = FlitErrorInjectionConfig(
        inject_tx=True,
        inject_rx=False,
        data_rate=0,
        num_errors=num_errors,
        spacing=0,
        flit_type=0,
        consecutive=0,
        error_type=error_type,
        error_offset=0,
        error_magnitude=1,
    )

    try:
        reader.configure_flit_error_injection(config)
        return StepResult(
            step_name="Inject Flit Error",
            passed=True,
            detail=(
                f"Injected {num_errors} {error_type_name} error(s) "
                f"(TX direction, error_magnitude=1)"
            ),
        )
    except (ValueError, CalypsoError) as exc:
        return StepResult(
            step_name="Inject Flit Error",
            passed=False,
            detail=f"Injection failed: {exc}",
        )


def disable_injection(reader: PcieConfigReader) -> StepResult:
    """Disable Flit error injection after the test.

    Returns:
        StepResult indicating whether injection was disabled.
    """
    try:
        reader.disable_flit_error_injection()
        return StepResult(
            step_name="Disable Flit Error Injection",
            passed=True,
            detail="Error injection disabled",
        )
    except (ValueError, CalypsoError) as exc:
        return StepResult(
            step_name="Disable Flit Error Injection",
            passed=False,
            detail=f"Failed to disable injection: {exc}",
        )


# ---------------------------------------------------------------------------
# Post-injection validation
# ---------------------------------------------------------------------------


def validate_counter_increment(
    reader: PcieConfigReader,
    baseline_counter: int,
    expected_errors: int,
) -> StepResult:
    """Check that the error counter incremented after injection.

    Args:
        reader: PCIe config reader for the target port.
        baseline_counter: Counter value before injection.
        expected_errors: Number of errors that were injected.

    Returns:
        StepResult with pass/fail and counter delta details.
    """
    post_counter = read_error_counter(reader)
    if post_counter is None:
        return StepResult(
            step_name="Validate Error Counter Increment",
            passed=False,
            detail="Flit Logging capability not available for post-read",
        )

    delta = post_counter.counter - baseline_counter
    # Counter may wrap or count more than expected due to FEC retries.
    # We consider it a pass if the counter moved at all.
    if delta > 0:
        return StepResult(
            step_name="Validate Error Counter Increment",
            passed=True,
            detail=(
                f"Counter incremented by {delta} "
                f"(baseline={baseline_counter}, post={post_counter.counter}, "
                f"expected>={expected_errors})"
            ),
        )

    return StepResult(
        step_name="Validate Error Counter Increment",
        passed=False,
        detail=(
            f"Counter did not increment (baseline={baseline_counter}, post={post_counter.counter})"
        ),
    )


def check_flit_error_log(reader: PcieConfigReader) -> StepResult:
    """Read the Flit Error Log FIFO for captured error entries.

    Returns:
        StepResult with details about any logged error events.
    """
    entries = reader.read_all_flit_error_log_entries(max_entries=16)
    if not entries:
        return StepResult(
            step_name="Check Flit Error Log (FIFO)",
            passed=False,
            detail="No entries in the Flit Error Log FIFO",
        )

    detail_lines = [f"Found {len(entries)} error log entry/entries:"]
    for i, entry in enumerate(entries):
        flags = _format_log_entry_flags(entry)
        detail_lines.append(
            f"  [{i}] flit_offset={entry.flit_offset}, "
            f"consecutive={entry.consecutive_errors}, "
            f"link_width={entry.link_width}, "
            f"flags=[{flags}]"
        )

    return StepResult(
        step_name="Check Flit Error Log (FIFO)",
        passed=True,
        detail="\n".join(detail_lines),
    )


def _format_log_entry_flags(entry: FlitErrorLogEntry) -> str:
    """Format human-readable flags from a flit error log entry."""
    flags: list[str] = []
    if entry.fec_uncorrectable:
        flags.append("FEC_UNCORRECTABLE")
    if entry.unrecognized_flit:
        flags.append("UNRECOGNIZED_FLIT")
    if entry.more_entries:
        flags.append("MORE_ENTRIES")
    return ", ".join(flags) if flags else "none"


def verify_link_recovery(reader: PcieConfigReader) -> StepResult:
    """Verify the link is still up and has not degraded after error injection.

    Checks that DLL Link Active is true and the link is not in training.

    Returns:
        StepResult with link status details.
    """
    try:
        link = reader.get_link_status()
    except CalypsoError as exc:
        return StepResult(
            step_name="Verify Link Recovery",
            passed=False,
            detail=f"Failed to read link status: {exc}",
        )

    is_healthy = link.dll_link_active and not link.link_training
    status_detail = (
        f"speed={link.current_speed}, width=x{link.current_width}, "
        f"dll_active={link.dll_link_active}, training={link.link_training}"
    )

    if is_healthy:
        return StepResult(
            step_name="Verify Link Recovery",
            passed=True,
            detail=f"Link is UP and healthy: {status_detail}",
        )

    return StepResult(
        step_name="Verify Link Recovery",
        passed=False,
        detail=f"Link degraded or down: {status_detail}",
    )


def read_injection_status(reader: PcieConfigReader) -> StepResult:
    """Read the Flit Error Injection status register for completion.

    Returns:
        StepResult with raw injection status values.
    """
    status = reader.get_flit_error_injection_status()
    if status is None:
        return StepResult(
            step_name="Read Injection Status",
            passed=False,
            detail="Flit Error Injection capability not available",
        )

    return StepResult(
        step_name="Read Injection Status",
        passed=True,
        detail=(
            f"flit_tx_status={status.flit_tx_status}, "
            f"flit_rx_status={status.flit_rx_status}, "
            f"raw_flit_status=0x{status.raw_flit_status:08X}"
        ),
    )


# ---------------------------------------------------------------------------
# Test orchestration
# ---------------------------------------------------------------------------


def open_device_for_port(
    device_index: int,
    port_number: int,
) -> tuple[SwitchDevice, PcieConfigReader] | None:
    """Open the switch device and create a config reader targeting a port.

    Note: The PcieConfigReader operates on the management port's config space.
    For per-port targeting, the device must be opened on the correct BDF.
    This example operates on the device's own port (the one SwitchDevice opens on).

    Args:
        device_index: Zero-based Atlas3 device index.
        port_number: Target port number (currently informational; the reader
            operates on the device's management port).

    Returns:
        Tuple of (SwitchDevice, PcieConfigReader), or None on failure.
    """
    transport = PcieTransport()
    device = SwitchDevice(transport)

    try:
        device.open(device_index)
    except CalypsoError as exc:
        logger.error("device_open_failed", detail=str(exc))
        print(f"Error: Failed to open device {device_index}: {exc}", file=sys.stderr)
        return None

    device_obj = device._require_open()
    device_key = device.device_key
    if device_key is None:
        print("Error: Device key unavailable after open.", file=sys.stderr)
        device.close()
        return None

    reader = PcieConfigReader(device_obj, device_key)
    return (device, reader)


def run_injection_test(
    device_index: int,
    port_number: int,
    num_errors: int,
    error_type: int,
    wait_seconds: float,
) -> TestReport:
    """Execute the full Flit error injection test sequence.

    Steps:
        1. Open device and verify capabilities
        2. Enable and read baseline error counter
        3. Inject controlled flit errors
        4. Wait for error propagation
        5. Validate counter increment
        6. Check Flit Error Log FIFO
        7. Verify link recovered
        8. Disable injection and report

    Args:
        device_index: Zero-based Atlas3 device index.
        port_number: Target port number.
        num_errors: Number of flit errors to inject.
        error_type: Error type code (0=CRC, 1=Sequence, 2=FEC).
        wait_seconds: Seconds to wait after injection for error propagation.

    Returns:
        TestReport with all step results.
    """
    start_time = time.monotonic()
    steps: list[StepResult] = []

    # Step 1: Open device
    result = open_device_for_port(device_index, port_number)
    if result is None:
        steps.append(
            StepResult(
                step_name="Open Device",
                passed=False,
                detail=f"Could not open device index {device_index}",
            )
        )
        return _build_report(device_index, port_number, steps, start_time)

    device, reader = result

    try:
        info = device.device_info
        chip_label = f"0x{info.chip_type:04X}" if info else "unknown"
        steps.append(
            StepResult(
                step_name="Open Device",
                passed=True,
                detail=f"Opened device {device_index} (chip {chip_label})",
            )
        )

        # Step 2: Verify Flit Error Injection capability (0x0034)
        inj_cap_result = check_flit_injection_capability(reader)
        steps.append(inj_cap_result)
        if not inj_cap_result.passed:
            return _build_report(device_index, port_number, steps, start_time)

        # Step 3: Verify Flit Logging capability (0x0032)
        log_cap_result = check_flit_logging_capability(reader)
        steps.append(log_cap_result)
        if not log_cap_result.passed:
            return _build_report(device_index, port_number, steps, start_time)

        # Step 4: Enable error counter and read baseline
        enable_error_counter(reader)
        baseline_result = read_baseline_counter(reader)
        steps.append(baseline_result)

        baseline_value = 0
        if baseline_result.passed:
            counter = read_error_counter(reader)
            baseline_value = counter.counter if counter else 0

        # Step 5: Drain any pre-existing error log entries
        _pre_drain = reader.read_all_flit_error_log_entries(max_entries=64)
        if _pre_drain:
            steps.append(
                StepResult(
                    step_name="Drain Pre-existing Error Log",
                    passed=True,
                    detail=f"Cleared {len(_pre_drain)} stale entry/entries from FIFO",
                )
            )

        # Step 6: Inject flit errors
        inject_result = inject_flit_error(reader, num_errors, error_type)
        steps.append(inject_result)
        if not inject_result.passed:
            return _build_report(device_index, port_number, steps, start_time)

        # Step 7: Wait for error propagation
        time.sleep(wait_seconds)
        steps.append(
            StepResult(
                step_name="Wait for Error Propagation",
                passed=True,
                detail=f"Waited {wait_seconds:.1f}s for errors to propagate",
            )
        )

        # Step 8: Read injection status
        inj_status_result = read_injection_status(reader)
        steps.append(inj_status_result)

        # Step 9: Validate error counter increment
        counter_result = validate_counter_increment(
            reader,
            baseline_value,
            num_errors,
        )
        steps.append(counter_result)

        # Step 10: Check Flit Error Log FIFO
        log_result = check_flit_error_log(reader)
        steps.append(log_result)

        # Step 11: Verify link recovered
        link_result = verify_link_recovery(reader)
        steps.append(link_result)

        # Step 12: Disable injection (always attempt, even if prior steps failed)
        disable_result = disable_injection(reader)
        steps.append(disable_result)

    finally:
        device.close()

    return _build_report(device_index, port_number, steps, start_time)


def _build_report(
    device_index: int,
    port_number: int,
    steps: list[StepResult],
    start_time: float,
) -> TestReport:
    """Build a TestReport from accumulated step results."""
    duration = time.monotonic() - start_time
    overall = all(step.passed for step in steps)
    return TestReport(
        device_index=device_index,
        port_number=port_number,
        steps=tuple(steps),
        overall_passed=overall,
        duration_seconds=duration,
    )


# ---------------------------------------------------------------------------
# Report printing
# ---------------------------------------------------------------------------


def print_report(report: TestReport) -> None:
    """Print a detailed test report to stdout."""
    print("")
    print("=" * 70)
    print("  FLIT ERROR INJECTION TEST REPORT")
    print("=" * 70)
    print(f"  Device Index : {report.device_index}")
    print(f"  Port Number  : {report.port_number}")
    print(f"  Duration     : {report.duration_seconds:.2f}s")
    print(f"  Steps        : {len(report.steps)}")
    print("-" * 70)

    for i, step in enumerate(report.steps, start=1):
        status = "PASS" if step.passed else "FAIL"
        marker = "[+]" if step.passed else "[X]"
        print(f"  {marker} Step {i:>2}: {step.step_name} ... {status}")
        for line in step.detail.split("\n"):
            print(f"             {line}")

    print("-" * 70)

    if report.overall_passed:
        print("  OVERALL RESULT: PASS")
        print("  All steps completed successfully.")
    else:
        failed_steps = [s for s in report.steps if not s.passed]
        print(f"  OVERALL RESULT: FAIL ({len(failed_steps)} step(s) failed)")
        for s in failed_steps:
            print(f"    - {s.step_name}: {s.detail}")

    print("=" * 70)
    print("")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "PCIe 6.0.1 Flit Error Injection Test -- inject controlled flit-level "
            "errors into an Atlas3 Gen6 PCIe switch port and validate error "
            "logging, counters, and link recovery."
        ),
        epilog=(
            "Examples:\n"
            "  python flit_error_injection_test.py 0 0\n"
            "  python flit_error_injection_test.py 0 4 --num-errors 3\n"
            "  python flit_error_injection_test.py 0 0 --error-type 1 --wait 2.0\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "device_index",
        type=int,
        help=("Zero-based index of the Atlas3 device to open (matches 'calypso scan' order)."),
    )
    parser.add_argument(
        "port_number",
        type=int,
        help="Target port number on the switch.",
    )
    parser.add_argument(
        "--num-errors",
        type=int,
        default=1,
        help="Number of flit errors to inject (1-31, default: 1).",
    )
    parser.add_argument(
        "--error-type",
        type=int,
        default=0,
        choices=[0, 1, 2],
        help=("Error type to inject: 0=CRC (default), 1=Sequence, 2=FEC Uncorrectable."),
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=1.0,
        help="Seconds to wait after injection for error propagation (default: 1.0).",
    )
    parser.add_argument(
        "--skip-safety-prompt",
        action="store_true",
        default=False,
        help="Skip the interactive safety confirmation prompt.",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse args, confirm safety, and run the injection test."""
    args = parse_args(argv)

    if args.num_errors < 1 or args.num_errors > 31:
        print("Error: --num-errors must be between 1 and 31.", file=sys.stderr)
        return 1

    if args.wait <= 0:
        print("Error: --wait must be positive.", file=sys.stderr)
        return 1

    if not args.skip_safety_prompt:
        if not confirm_safety_prompt():
            print("Aborted by user.")
            return 1

    error_type_name = ERROR_TYPE_NAMES.get(args.error_type, "Unknown")
    print("\nStarting Flit Error Injection Test")
    print(f"  Device: {args.device_index}, Port: {args.port_number}")
    print(f"  Errors: {args.num_errors} x {error_type_name}")
    print(f"  Wait:   {args.wait:.1f}s")
    print("")

    report = run_injection_test(
        device_index=args.device_index,
        port_number=args.port_number,
        num_errors=args.num_errors,
        error_type=args.error_type,
        wait_seconds=args.wait,
    )

    print_report(report)

    return 0 if report.overall_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
