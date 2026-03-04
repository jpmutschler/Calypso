"""PTrace Capture — configure, arm, and dump Atlas3 protocol trace buffers.

Opens an Atlas3 device by index, configures the PTrace hardware analyzer
on a specified port, arms a trigger, waits for capture to complete (or
times out), and dumps the trace buffer to a JSON file.

The Atlas3 PTrace block is a per-station protocol analyzer with 4096-row
trace buffers for both ingress and egress directions.  Each row captures
600 bits (19 DWORDs) of packet/flit data plus timestamps.

Usage:
    # Immediate capture on port 0, ingress, dump to default file
    python ptrace_capture.py 0 --port 0

    # Error-triggered capture on port 16 (station 1), egress direction
    python ptrace_capture.py 0 --port 16 --direction egress --trigger error

    # Immediate capture with custom output and 30s timeout
    python ptrace_capture.py 0 --port 0 --output my_trace.json --timeout 30

    # Manual trigger (arm then force-trigger immediately)
    python ptrace_capture.py 0 --port 0 --trigger manual

Trigger modes:
    immediate  - Start capture without waiting for a trigger condition.
                 Fills the buffer then stops.
    error      - Trigger on any port error (28-bit error mask = all ones).
    manual     - Arm the analyzer, then issue a manual trigger pulse.

Prerequisites:
    - Calypso installed: ``pip install -e ".[dev]"``
    - PLX driver loaded (PlxSvc service on Windows, PlxSvc module on Linux)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from calypso.core.ptrace import PTraceEngine
from calypso.core.switch import SwitchDevice
from calypso.exceptions import CalypsoError
from calypso.models.ptrace import (
    PTraceBufferResult,
    PTraceCaptureCfg,
    PTraceDirection,
    PTracePostTriggerCfg,
    PTraceStatus,
    PTraceTriggerCfg,
)
from calypso.transport.pcie import PcieTransport
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

# Trigger source constants (from Atlas3 PTrace register spec)
TRIGGER_SRC_IMMEDIATE = 0  # No trigger condition — capture runs freely
TRIGGER_SRC_COND0 = 1  # Trigger when condition 0 matches
TRIGGER_SRC_ERROR = 2  # Trigger on port error

# Error mask covering all 28 detectable port errors
ALL_ERRORS_MASK = 0x0FFFFFFF

# Default polling interval when waiting for trigger (seconds)
POLL_INTERVAL_S = 0.25

# Default maximum rows to read from the trace buffer
MAX_BUFFER_ROWS = 4096


# ---------------------------------------------------------------------------
# Configuration builders
# ---------------------------------------------------------------------------


def build_capture_cfg(
    port_number: int,
    direction: PTraceDirection,
) -> PTraceCaptureCfg:
    """Build a PTrace capture configuration for the given port and direction.

    Uses default trace point (Accumulator/Distributor), lane 0, no
    filtering or compression.  Suitable for a quick protocol capture.
    """
    return PTraceCaptureCfg(
        direction=direction,
        port_number=port_number,
        lane=0,
        filter_en=False,
        compress_en=False,
        nop_filt=True,
        idle_filt=True,
    )


def build_trigger_cfg(trigger_mode: str) -> PTraceTriggerCfg:
    """Build a trigger configuration for the requested mode.

    Args:
        trigger_mode: One of 'immediate', 'error', or 'manual'.

    Returns:
        A PTraceTriggerCfg with the appropriate trigger source.
    """
    if trigger_mode == "immediate":
        return PTraceTriggerCfg(trigger_src=TRIGGER_SRC_IMMEDIATE)

    if trigger_mode == "error":
        return PTraceTriggerCfg(trigger_src=TRIGGER_SRC_ERROR)

    # 'manual' — arm with condition 0 (we will force-trigger after arming)
    return PTraceTriggerCfg(trigger_src=TRIGGER_SRC_COND0)


def build_post_trigger_cfg() -> PTracePostTriggerCfg:
    """Build a default post-trigger configuration.

    Captures the full buffer after trigger (clock_count=0 means no limit).
    """
    return PTracePostTriggerCfg(
        clock_count=0,
        cap_count=0,
        clock_cnt_mult=0,
        count_type=0,
    )


# ---------------------------------------------------------------------------
# Capture orchestration
# ---------------------------------------------------------------------------


def configure_and_arm(
    engine: PTraceEngine,
    direction: PTraceDirection,
    trigger_mode: str,
    port_number: int,
) -> None:
    """Disable, configure, and arm the PTrace analyzer.

    For 'manual' mode, also issues a manual trigger pulse after arming.
    """
    capture_cfg = build_capture_cfg(port_number, direction)
    trigger_cfg = build_trigger_cfg(trigger_mode)
    post_trigger_cfg = build_post_trigger_cfg()

    logger.info(
        "ptrace_configuring",
        port=port_number,
        direction=direction.value,
        trigger=trigger_mode,
    )

    engine.full_configure(
        direction=direction,
        capture=capture_cfg,
        trigger=trigger_cfg,
        post_trigger=post_trigger_cfg,
    )

    # Start capture
    engine.start_capture(direction)
    logger.info("ptrace_armed", trigger=trigger_mode)

    # For manual mode, immediately issue a trigger pulse
    if trigger_mode == "manual":
        engine.manual_trigger(direction)
        logger.info("ptrace_manual_trigger_issued")


def wait_for_capture(
    engine: PTraceEngine,
    direction: PTraceDirection,
    timeout_s: float,
) -> PTraceStatus:
    """Poll capture status until triggered or timeout.

    For immediate-mode captures the buffer fills and capture_in_progress
    goes False.  For triggered modes we wait for the triggered flag.

    Returns:
        Final PTraceStatus after capture completes or timeout.

    Raises:
        CalypsoError: If capture does not complete within the timeout.
    """
    deadline = time.monotonic() + timeout_s

    while time.monotonic() < deadline:
        status = engine.read_status(direction)

        # Capture finished: either triggered or buffer full (not in progress)
        if status.triggered or not status.capture_in_progress:
            logger.info(
                "ptrace_capture_complete",
                triggered=status.triggered,
                tbuf_wrapped=status.tbuf_wrapped,
            )
            return status

        time.sleep(POLL_INTERVAL_S)

    # Timed out -- stop capture manually and return what we have
    engine.stop_capture(direction)
    logger.warning("ptrace_capture_timeout", timeout_s=timeout_s)
    return engine.read_status(direction)


def read_and_dump(
    engine: PTraceEngine,
    direction: PTraceDirection,
    output_path: Path,
) -> PTraceBufferResult:
    """Read the trace buffer and write it to a JSON file.

    Returns:
        The PTraceBufferResult for summary printing.
    """
    logger.info("ptrace_reading_buffer")
    result = engine.read_buffer(direction, max_rows=MAX_BUFFER_ROWS)

    resolved = output_path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)

    payload = result.model_dump(mode="json")
    resolved.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    logger.info("ptrace_buffer_written", path=str(resolved), rows=result.total_rows_read)
    return result


# ---------------------------------------------------------------------------
# Summary output
# ---------------------------------------------------------------------------


def print_capture_summary(
    status: PTraceStatus,
    result: PTraceBufferResult,
    output_path: Path,
) -> None:
    """Print a human-readable capture summary to stdout."""
    print()
    print("  PTrace Capture Summary")
    print("  " + "-" * 40)
    print(f"  Direction:        {result.direction.value}")
    print(f"  Port:             {result.port_number}")
    print(f"  Triggered:        {status.triggered}")
    print(f"  Buffer wrapped:   {status.tbuf_wrapped}")
    print(f"  Rows captured:    {result.total_rows_read}")
    print(f"  Trigger row:      {result.trigger_row_addr}")
    print(f"  Compress count:   {status.compress_cnt}")

    if status.trigger_ts > 0:
        elapsed = status.last_ts - status.trigger_ts
        print(f"  Trigger TS:       0x{status.trigger_ts:016X}")
        print(f"  Last TS:          0x{status.last_ts:016X}")
        print(f"  Elapsed (ticks):  {elapsed}")

    print(f"  Port error stat:  0x{status.port_err_status:08X}")
    print(f"  Output file:      {output_path.resolve()}")
    print()


# ---------------------------------------------------------------------------
# Device lifecycle
# ---------------------------------------------------------------------------


def run_capture(
    device_index: int,
    port_number: int,
    direction: PTraceDirection,
    trigger_mode: str,
    timeout_s: float,
    output_path: Path,
) -> int:
    """Open device, configure PTrace, capture, dump, and close.

    Returns:
        Exit code (0 = success, 1 = error).
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
        print(f"  Opened device {device_index} (chip {chip_label})")

        engine = PTraceEngine(device_obj, device_key, port_number)

        configure_and_arm(engine, direction, trigger_mode, port_number)

        print(f"  Waiting for capture (timeout {timeout_s}s)...")
        status = wait_for_capture(engine, direction, timeout_s)

        result = read_and_dump(engine, direction, output_path)

        # Clean up: disable the analyzer
        engine.disable(direction)

        print_capture_summary(status, result, output_path)
    finally:
        device.close()

    return 0


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Configure and capture Atlas3 PTrace (Protocol Trace) data. "
            "Arms the hardware analyzer on a specified port, waits for "
            "capture to complete, and dumps the trace buffer to JSON."
        ),
    )
    parser.add_argument(
        "device_index",
        type=int,
        help="Zero-based index of the Atlas3 device (matches 'calypso scan' order).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port number to trace (0-143). Default: 0.",
    )
    parser.add_argument(
        "--direction",
        choices=("ingress", "egress"),
        default="ingress",
        help="Capture direction. Default: ingress.",
    )
    parser.add_argument(
        "--trigger",
        choices=("immediate", "error", "manual"),
        default="immediate",
        help=(
            "Trigger mode. 'immediate' fills the buffer without a trigger. "
            "'error' triggers on any port error. "
            "'manual' arms then immediately force-triggers. Default: immediate."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Maximum seconds to wait for capture completion. Default: 10.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("ptrace_capture.json"),
        help="Output JSON file path. Default: ptrace_capture.json.",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse args, run capture, handle errors."""
    args = parse_args(argv)

    direction = PTraceDirection(args.direction)

    try:
        return run_capture(
            device_index=args.device_index,
            port_number=args.port,
            direction=direction,
            trigger_mode=args.trigger,
            timeout_s=args.timeout,
            output_path=args.output,
        )
    except CalypsoError as exc:
        logger.error("capture_failed", detail=str(exc))
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
