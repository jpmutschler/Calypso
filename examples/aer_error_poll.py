"""AER Error Polling — continuously monitor Advanced Error Reporting on all ports.

Opens an Atlas3 switch by device index, enumerates all ports, and polls
AER (Advanced Error Reporting) status registers at a configurable interval.
Prints correctable and uncorrectable error counts with human-readable names.
Optionally clears AER status after each read for delta-based error counting.
Prints a summary of all observed errors on exit (Ctrl+C or --duration limit).

Usage:
    python aer_error_poll.py 0
    python aer_error_poll.py 0 --interval 2 --clear
    python aer_error_poll.py 0 --duration 60 --interval 1 --clear

Prerequisites:
    - Calypso installed: ``pip install -e ".[dev]"``
    - PLX driver loaded (PlxSvc service on Windows, PlxSvc module on Linux)
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from dataclasses import dataclass
from typing import Sequence

from calypso.bindings.constants import PlxApiMode
from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT, PLX_MODE_PROP
from calypso.core.pcie_config import PcieConfigReader
from calypso.core.switch import SwitchDevice
from calypso.sdk import device as sdk_device
from calypso.exceptions import CalypsoError
from calypso.models.pcie_config import AerCorrectableErrors, AerUncorrectableErrors
from calypso.transport.pcie import PcieTransport
from calypso.utils.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Human-readable field name mappings
# ---------------------------------------------------------------------------

UNCORRECTABLE_FIELD_NAMES: dict[str, str] = {
    "data_link_protocol": "Data Link Protocol Error",
    "surprise_down": "Surprise Down Error",
    "poisoned_tlp": "Poisoned TLP",
    "flow_control_protocol": "Flow Control Protocol Error",
    "completion_timeout": "Completion Timeout",
    "completer_abort": "Completer Abort",
    "unexpected_completion": "Unexpected Completion",
    "receiver_overflow": "Receiver Overflow",
    "malformed_tlp": "Malformed TLP",
    "ecrc_error": "ECRC Error",
    "unsupported_request": "Unsupported Request",
    "acs_violation": "ACS Violation",
}

CORRECTABLE_FIELD_NAMES: dict[str, str] = {
    "receiver_error": "Receiver Error",
    "bad_tlp": "Bad TLP",
    "bad_dllp": "Bad DLLP",
    "replay_num_rollover": "Replay Num Rollover",
    "replay_timer_timeout": "Replay Timer Timeout",
    "advisory_non_fatal": "Advisory Non-Fatal Error",
}


# ---------------------------------------------------------------------------
# Accumulator (immutable snapshots per port)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PortAerSnapshot:
    """Immutable snapshot of AER errors for a single port at a single poll."""

    port_number: int
    uncorrectable_flags: tuple[str, ...]
    correctable_flags: tuple[str, ...]
    uncorrectable_raw: int
    correctable_raw: int


@dataclass(frozen=True)
class PollSummary:
    """Immutable accumulator tracking all errors seen across the entire run."""

    total_polls: int = 0
    uncorrectable_counts: tuple[tuple[str, int], ...] = ()
    correctable_counts: tuple[tuple[str, int], ...] = ()
    ports_with_errors: tuple[int, ...] = ()


# ---------------------------------------------------------------------------
# AER field extraction
# ---------------------------------------------------------------------------


def _extract_active_flags(
    model: AerUncorrectableErrors | AerCorrectableErrors,
    field_names: dict[str, str],
) -> tuple[str, ...]:
    """Return human-readable names for all active (True) error fields."""
    return tuple(
        display_name for attr, display_name in field_names.items() if getattr(model, attr, False)
    )


def _read_port_aer(
    device: PLX_DEVICE_OBJECT,
    device_key: PLX_DEVICE_KEY,
    port_number: int,
    clear: bool,
) -> PortAerSnapshot | None:
    """Read AER status for a single port, optionally clearing after read.

    Returns None if AER capability is not present on this port.
    """
    reader = PcieConfigReader(device, device_key)
    aer = reader.get_aer_status()
    if aer is None:
        return None

    snapshot = PortAerSnapshot(
        port_number=port_number,
        uncorrectable_flags=_extract_active_flags(
            aer.uncorrectable,
            UNCORRECTABLE_FIELD_NAMES,
        ),
        correctable_flags=_extract_active_flags(
            aer.correctable,
            CORRECTABLE_FIELD_NAMES,
        ),
        uncorrectable_raw=aer.uncorrectable.raw_value,
        correctable_raw=aer.correctable.raw_value,
    )

    if clear and (snapshot.uncorrectable_raw or snapshot.correctable_raw):
        reader.clear_aer_errors()

    return snapshot


# ---------------------------------------------------------------------------
# Port enumeration
# ---------------------------------------------------------------------------


def _enumerate_port_keys(
    device: PLX_DEVICE_OBJECT,
    device_key: PLX_DEVICE_KEY,
) -> list[tuple[int, PLX_DEVICE_OBJECT, PLX_DEVICE_KEY]]:
    """Discover all ports and return open device handles for each.

    Returns a list of (port_number, device_object, device_key) tuples.
    The caller is responsible for closing each device_object.
    """
    api_mode = PlxApiMode(device_key.ApiMode)
    mode_prop = PLX_MODE_PROP() if api_mode != PlxApiMode.PCI else None
    all_keys = sdk_device.find_devices(api_mode=api_mode, mode_prop=mode_prop)

    ports: list[tuple[int, PLX_DEVICE_OBJECT, PLX_DEVICE_KEY]] = []
    for key in all_keys:
        try:
            dev = sdk_device.open_device(key)
            props = sdk_device.get_port_properties(dev)
            ports.append((props.PortNumber, dev, key))
        except Exception:
            logger.debug("port_open_failed", port=key.PlxPort)

    return sorted(ports, key=lambda p: p[0])


def _close_port_handles(
    ports: Sequence[tuple[int, PLX_DEVICE_OBJECT, PLX_DEVICE_KEY]],
) -> None:
    """Close all opened port device handles."""
    for _, dev, _ in ports:
        try:
            sdk_device.close_device(dev)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def _print_poll_header(poll_number: int, timestamp: float) -> None:
    """Print a timestamped separator for each poll cycle."""
    ts = time.strftime("%H:%M:%S", time.localtime(timestamp))
    print(f"\n--- Poll #{poll_number} at {ts} ---")


def _print_port_errors(snapshot: PortAerSnapshot) -> None:
    """Print error details for a single port if any errors are active."""
    if not snapshot.uncorrectable_flags and not snapshot.correctable_flags:
        return

    print(f"  Port {snapshot.port_number:>3}:")
    if snapshot.uncorrectable_flags:
        print(f"    Uncorrectable (0x{snapshot.uncorrectable_raw:08X}):")
        for name in snapshot.uncorrectable_flags:
            print(f"      - {name}")
    if snapshot.correctable_flags:
        print(f"    Correctable   (0x{snapshot.correctable_raw:08X}):")
        for name in snapshot.correctable_flags:
            print(f"      - {name}")


def _print_no_errors() -> None:
    """Print message when a poll cycle found no errors."""
    print("  No AER errors detected on any port.")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def _accumulate(summary: PollSummary, snapshots: tuple[PortAerSnapshot, ...]) -> PollSummary:
    """Return a new summary incorporating new snapshots (fully immutable)."""
    uncorr = dict(summary.uncorrectable_counts)
    corr = dict(summary.correctable_counts)
    ports = set(summary.ports_with_errors)

    for snap in snapshots:
        if snap.uncorrectable_flags or snap.correctable_flags:
            ports.add(snap.port_number)

        for name in snap.uncorrectable_flags:
            uncorr[name] = uncorr.get(name, 0) + 1
        for name in snap.correctable_flags:
            corr[name] = corr.get(name, 0) + 1

    return PollSummary(
        total_polls=summary.total_polls + 1,
        uncorrectable_counts=tuple(sorted(uncorr.items())),
        correctable_counts=tuple(sorted(corr.items())),
        ports_with_errors=tuple(sorted(ports)),
    )


def _print_summary(summary: PollSummary) -> None:
    """Print final summary of all errors observed during the run."""
    print("\n" + "=" * 60)
    print("AER Error Polling Summary")
    print("=" * 60)
    print(f"  Total poll cycles: {summary.total_polls}")
    print(f"  Ports with errors: {list(summary.ports_with_errors) or 'none'}")

    if summary.uncorrectable_counts:
        print("\n  Uncorrectable errors seen (poll cycles with error):")
        for name, count in summary.uncorrectable_counts:
            print(f"    {name:<35} {count:>5}x")
    else:
        print("\n  No uncorrectable errors observed.")

    if summary.correctable_counts:
        print("\n  Correctable errors seen (poll cycles with error):")
        for name, count in summary.correctable_counts:
            print(f"    {name:<35} {count:>5}x")
    else:
        print("\n  No correctable errors observed.")

    print("=" * 60)


# ---------------------------------------------------------------------------
# Poll loop
# ---------------------------------------------------------------------------


def _poll_all_ports(
    ports: Sequence[tuple[int, PLX_DEVICE_OBJECT, PLX_DEVICE_KEY]],
    clear: bool,
) -> tuple[PortAerSnapshot, ...]:
    """Read AER status from every port and return snapshots."""
    snapshots: list[PortAerSnapshot] = []
    for port_number, dev, key in ports:
        try:
            snap = _read_port_aer(dev, key, port_number, clear=clear)
            if snap is not None:
                snapshots.append(snap)
        except CalypsoError as exc:
            logger.debug("aer_read_failed", port=port_number, error=str(exc))
    return tuple(snapshots)


def run_poll_loop(
    device_index: int,
    interval: float,
    clear: bool,
    duration: float | None,
) -> int:
    """Main poll loop. Returns exit code."""
    transport = PcieTransport()
    device = SwitchDevice(transport)

    # Track whether we received SIGINT
    interrupted = False

    def _handle_sigint(signum: int, frame: object) -> None:
        nonlocal interrupted
        interrupted = True

    signal.signal(signal.SIGINT, _handle_sigint)

    try:
        device.open(device_index)
    except CalypsoError as exc:
        logger.error("device_open_failed", detail=str(exc))
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    device_obj = device._require_open()
    device_key = device.device_key
    if device_key is None:
        print("Error: Device key unavailable after open.", file=sys.stderr)
        device.close()
        return 1

    info = device.device_info
    chip_label = f"0x{info.chip_type:04X}" if info else "unknown"
    print(f"Opened device {device_index} (chip {chip_label})")

    # Enumerate all ports once
    ports = _enumerate_port_keys(device_obj, device_key)
    if not ports:
        print("No ports found on device.", file=sys.stderr)
        device.close()
        return 1

    port_numbers = [p[0] for p in ports]
    print(f"Monitoring {len(ports)} port(s): {port_numbers}")
    if clear:
        print("Mode: delta (clearing AER status after each read)")
    else:
        print("Mode: cumulative (AER status registers are not cleared)")
    if duration is not None:
        print(f"Duration limit: {duration}s")

    summary = PollSummary()
    poll_number = 0
    start_time = time.monotonic()

    try:
        while not interrupted:
            # Check duration limit
            if duration is not None:
                elapsed = time.monotonic() - start_time
                if elapsed >= duration:
                    print(f"\nDuration limit ({duration}s) reached.")
                    break

            poll_number += 1
            now = time.time()

            snapshots = _poll_all_ports(ports, clear=clear)
            has_errors = any(s.uncorrectable_flags or s.correctable_flags for s in snapshots)

            _print_poll_header(poll_number, now)
            if has_errors:
                for snap in snapshots:
                    _print_port_errors(snap)
            else:
                _print_no_errors()

            summary = _accumulate(summary, snapshots)

            # Sleep in short increments so we can respond to Ctrl+C promptly
            sleep_end = time.monotonic() + interval
            while time.monotonic() < sleep_end and not interrupted:
                time.sleep(min(0.25, sleep_end - time.monotonic()))

    finally:
        _close_port_handles(ports)
        device.close()

    _print_summary(summary)
    return 0


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Poll AER (Advanced Error Reporting) status registers on all ports "
            "of an Atlas3 PCIe switch."
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
        default=5.0,
        help="Poll interval in seconds (default: 5).",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        default=False,
        help=(
            "Clear AER status registers after each read (write-1-to-clear). "
            "Enables delta-based error counting between polls."
        ),
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help=("Maximum run duration in seconds. If not set, runs until Ctrl+C."),
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse args and run the AER poll loop."""
    args = parse_args(argv)

    if args.interval <= 0:
        print("Error: --interval must be positive.", file=sys.stderr)
        return 1

    if args.duration is not None and args.duration <= 0:
        print("Error: --duration must be positive.", file=sys.stderr)
        return 1

    return run_poll_loop(
        device_index=args.device_index,
        interval=args.interval,
        clear=args.clear,
        duration=args.duration,
    )


if __name__ == "__main__":
    raise SystemExit(main())
