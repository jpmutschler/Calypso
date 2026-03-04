"""PAM4 3-eye lane margining sweep for PCIe Gen6 Flit mode.

Performs a full PCIe 6.0.1 Lane Margining at Receiver sweep across all
three PAM4 sub-eyes (upper, middle, lower) on a specified port and lane.
Reports per-eye voltage (mV) and timing (UI) margins, and renders an
ASCII eye diagram visualization.

This is a Gen6/Flit-specific tool -- it requires the target link to be
operating at 64 GT/s PAM4.

Usage:
    # Sweep port 4, lane 0 on device index 0
    python pam4_eye_sweep.py 0 4 0

    # Sweep port 8, lane 3 and save results to JSON
    python pam4_eye_sweep.py 0 8 3 --output results.json

    # Use a non-default device index
    python pam4_eye_sweep.py 2 0 0

Requirements:
    - Calypso must be installed (``pip install -e ".[dev]"``)
    - The PLX driver must be loaded (PlxSvc service on Windows,
      PlxSvc kernel module on Linux)
    - Target link must be active at Gen6 (64 GT/s) with PAM4 modulation
    - The downstream device must support Lane Margining at the Receiver
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from calypso.core.lane_margining import LaneMarginingEngine
from calypso.core.switch import SwitchDevice
from calypso.models.phy import PAM4_EYE_LABELS, steps_to_timing_ui, steps_to_voltage_mv
from calypso.models.phy_api import EyeSweepResult, PAM4SweepResult
from calypso.transport.pcie import PcieTransport
from calypso.utils.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data structures for display
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EyeMargins:
    """Margin measurements for a single PAM4 sub-eye."""

    label: str
    height_mv: float
    width_ui: float
    height_steps: int
    width_steps: int
    margin_up_mv: float
    margin_down_mv: float
    margin_left_ui: float
    margin_right_ui: float
    sweep_time_ms: int


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the PAM4 eye sweep CLI."""
    parser = argparse.ArgumentParser(
        description=(
            "PAM4 3-eye lane margining sweep for PCIe Gen6 Atlas3 switches. "
            "Sweeps voltage and timing margins on all three PAM4 sub-eyes "
            "(upper, middle, lower) and renders an ASCII eye diagram."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  %(prog)s 0 4 0                  # device 0, port 4, lane 0\n"
            "  %(prog)s 0 8 3 --output out.json # save results to JSON\n"
            "  %(prog)s 2 0 0                   # device index 2\n"
        ),
    )
    parser.add_argument(
        "device_index",
        type=int,
        help="Device index from discovery scan (0-based).",
    )
    parser.add_argument(
        "port",
        type=int,
        help="Target port number on the switch.",
    )
    parser.add_argument(
        "lane",
        type=int,
        help="Lane number within the port (typically 0-15).",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        metavar="FILE",
        help="Save results to a JSON file.",
    )
    return parser


# ---------------------------------------------------------------------------
# Eye margin extraction
# ---------------------------------------------------------------------------


def extract_eye_margins(eye: EyeSweepResult, label: str) -> EyeMargins:
    """Extract margin measurements from a single eye sweep result."""
    return EyeMargins(
        label=label,
        height_mv=eye.eye_height_mv,
        width_ui=eye.eye_width_ui,
        height_steps=eye.eye_height_steps,
        width_steps=eye.eye_width_steps,
        margin_up_mv=eye.margin_up_mv,
        margin_down_mv=eye.margin_down_mv,
        margin_left_ui=eye.margin_left_ui,
        margin_right_ui=eye.margin_right_ui,
        sweep_time_ms=eye.sweep_time_ms,
    )


def extract_all_margins(result: PAM4SweepResult) -> tuple[EyeMargins, ...]:
    """Extract margins for all three PAM4 sub-eyes."""
    eyes = (result.upper_eye, result.middle_eye, result.lower_eye)
    return tuple(extract_eye_margins(eye, label) for eye, label in zip(eyes, PAM4_EYE_LABELS))


# ---------------------------------------------------------------------------
# ASCII eye diagram rendering
# ---------------------------------------------------------------------------

# Diagram dimensions
_DIAGRAM_WIDTH = 60
_DIAGRAM_HEIGHT = 9  # per eye vertical rows (odd for center row)
_BORDER_CHAR = "."
_FILL_CHAR = " "
_CENTER_CHAR = "-"
_EYE_CHAR = "#"


def _scale_to_cols(ui_value: float, max_ui: float, half_width: int) -> int:
    """Scale a UI margin value to column count (clamped to half_width)."""
    if max_ui <= 0:
        return 0
    return min(int((ui_value / max_ui) * half_width), half_width)


def _scale_to_rows(mv_value: float, max_mv: float, half_height: int) -> int:
    """Scale a mV margin value to row count (clamped to half_height)."""
    if max_mv <= 0:
        return 0
    return min(int((mv_value / max_mv) * half_height), half_height)


def render_single_eye(
    margins: EyeMargins,
    max_ui: float,
    max_mv: float,
) -> list[str]:
    """Render one PAM4 sub-eye as ASCII art lines.

    The eye is drawn as a diamond shape whose width corresponds to the
    timing margin (UI) and height corresponds to the voltage margin (mV),
    scaled relative to the capability maximums.
    """
    half_w = _DIAGRAM_WIDTH // 2
    half_h = _DIAGRAM_HEIGHT // 2

    # Scale margins to character grid
    right_cols = _scale_to_cols(margins.margin_right_ui, max_ui, half_w)
    left_cols = _scale_to_cols(margins.margin_left_ui, max_ui, half_w)
    up_rows = _scale_to_rows(margins.margin_up_mv, max_mv, half_h)
    down_rows = _scale_to_rows(margins.margin_down_mv, max_mv, half_h)

    lines: list[str] = []
    center_col = half_w

    for row in range(_DIAGRAM_HEIGHT):
        row_offset = abs(row - half_h)
        chars = list(_BORDER_CHAR * _DIAGRAM_WIDTH)

        if row == half_h:
            # Center row -- draw the full eye opening width
            eye_left = center_col - left_cols
            eye_right = center_col + right_cols
            for col in range(max(0, eye_left), min(_DIAGRAM_WIDTH, eye_right + 1)):
                chars[col] = _CENTER_CHAR
        elif row < half_h and row_offset <= up_rows:
            # Upper half -- diamond narrows toward top
            frac = 1.0 - (row_offset / max(up_rows, 1))
            span_left = int(left_cols * frac)
            span_right = int(right_cols * frac)
            eye_left = center_col - span_left
            eye_right = center_col + span_right
            for col in range(max(0, eye_left), min(_DIAGRAM_WIDTH, eye_right + 1)):
                chars[col] = _FILL_CHAR
            # Draw boundary
            if 0 <= eye_left < _DIAGRAM_WIDTH:
                chars[eye_left] = _EYE_CHAR
            if 0 <= eye_right < _DIAGRAM_WIDTH:
                chars[eye_right] = _EYE_CHAR
        elif row > half_h and row_offset <= down_rows:
            # Lower half -- diamond narrows toward bottom
            frac = 1.0 - (row_offset / max(down_rows, 1))
            span_left = int(left_cols * frac)
            span_right = int(right_cols * frac)
            eye_left = center_col - span_left
            eye_right = center_col + span_right
            for col in range(max(0, eye_left), min(_DIAGRAM_WIDTH, eye_right + 1)):
                chars[col] = _FILL_CHAR
            if 0 <= eye_left < _DIAGRAM_WIDTH:
                chars[eye_left] = _EYE_CHAR
            if 0 <= eye_right < _DIAGRAM_WIDTH:
                chars[eye_right] = _EYE_CHAR

        lines.append("".join(chars))

    return lines


def render_pam4_eye_diagram(
    all_margins: tuple[EyeMargins, ...],
    caps_max_timing_ui: float,
    caps_max_voltage_mv: float,
) -> str:
    """Render a stacked 3-eye ASCII diagram for PAM4.

    Eyes are stacked vertically: upper eye at top, lower eye at bottom,
    matching the physical PAM4 voltage level arrangement.
    """
    sections: list[str] = []
    header = (
        f"  PAM4 3-Eye Diagram  "
        f"(max timing: {caps_max_timing_ui:.3f} UI, "
        f"max voltage: {caps_max_voltage_mv:.1f} mV)"
    )
    sections.append(header)
    sections.append("=" * max(len(header), _DIAGRAM_WIDTH + 20))

    for margins in all_margins:
        label_line = (
            f"  [{margins.label.upper()} EYE]  "
            f"H={margins.height_mv:.1f} mV  W={margins.width_ui:.4f} UI  "
            f"({margins.sweep_time_ms}ms)"
        )
        sections.append("")
        sections.append(label_line)
        eye_lines = render_single_eye(margins, caps_max_timing_ui, caps_max_voltage_mv)
        for line in eye_lines:
            sections.append(f"  |{line}|")

    sections.append("")
    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Results table
# ---------------------------------------------------------------------------


def print_margin_table(all_margins: tuple[EyeMargins, ...]) -> None:
    """Print a formatted table of per-eye margin values."""
    print("\n  Per-Eye Margin Results")
    print("  " + "=" * 74)
    print(
        f"  {'Eye':<10s} {'Height(mV)':>10s} {'Width(UI)':>10s} "
        f"{'Up(mV)':>8s} {'Down(mV)':>9s} "
        f"{'Left(UI)':>9s} {'Right(UI)':>10s} {'Time(ms)':>9s}"
    )
    print("  " + "-" * 74)

    for m in all_margins:
        print(
            f"  {m.label:<10s} {m.height_mv:>10.1f} {m.width_ui:>10.4f} "
            f"{m.margin_up_mv:>8.1f} {m.margin_down_mv:>9.1f} "
            f"{m.margin_left_ui:>9.4f} {m.margin_right_ui:>10.4f} {m.sweep_time_ms:>9d}"
        )

    print("  " + "-" * 74)


def print_summary(result: PAM4SweepResult) -> None:
    """Print the overall sweep summary."""
    balance_str = "BALANCED" if result.is_balanced else "UNBALANCED"
    print("\n  Summary")
    print("  " + "=" * 50)
    print(f"    Worst eye width:  {result.worst_eye_width_ui:.4f} UI")
    print(f"    Worst eye height: {result.worst_eye_height_mv:.1f} mV")
    print(f"    Eye balance:      {balance_str}")
    print(f"    Total sweep time: {result.total_sweep_time_ms} ms")
    print("  " + "=" * 50)


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------


def build_json_output(
    result: PAM4SweepResult,
    all_margins: tuple[EyeMargins, ...],
    port: int,
    lane: int,
    device_index: int,
) -> dict:
    """Build a JSON-serializable dictionary from sweep results."""
    return {
        "device_index": device_index,
        "port": port,
        "lane": lane,
        "modulation": result.modulation,
        "total_sweep_time_ms": result.total_sweep_time_ms,
        "worst_eye_width_ui": result.worst_eye_width_ui,
        "worst_eye_height_mv": result.worst_eye_height_mv,
        "is_balanced": result.is_balanced,
        "eyes": [asdict(m) for m in all_margins],
        "capabilities": {
            "max_timing_offset": result.upper_eye.capabilities.max_timing_offset,
            "max_voltage_offset": result.upper_eye.capabilities.max_voltage_offset,
            "num_timing_steps": result.upper_eye.capabilities.num_timing_steps,
            "num_voltage_steps": result.upper_eye.capabilities.num_voltage_steps,
            "ind_up_down_voltage": result.upper_eye.capabilities.ind_up_down_voltage,
            "ind_left_right_timing": result.upper_eye.capabilities.ind_left_right_timing,
        },
    }


def save_json(data: dict, output_path: str) -> None:
    """Write results to a JSON file."""
    resolved = Path(output_path).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"\n  Results saved to: {resolved}")


# ---------------------------------------------------------------------------
# Sweep execution
# ---------------------------------------------------------------------------


def run_sweep(device_index: int, port: int, lane: int) -> PAM4SweepResult:
    """Open a device, execute the PAM4 3-eye sweep, and return results.

    Opens the switch via PCIe transport, creates a LaneMarginingEngine
    targeting the specified port, and runs the full PAM4 sweep across
    all three receivers (upper/middle/lower eyes).
    """
    transport = PcieTransport()
    device = SwitchDevice(transport)

    try:
        device.open(device_index)
    except Exception as exc:
        logger.exception("device_open_failed")
        print(f"Error: failed to open device {device_index}: {exc}")
        sys.exit(1)

    dev_obj = device._require_open()
    dev_key = device.device_key
    if dev_obj is None or dev_key is None:
        print("Error: device opened but internal objects are None.")
        device.close()
        sys.exit(1)

    engine: LaneMarginingEngine | None = None
    try:
        print(f"\n  Initializing margining engine for port {port}, lane {lane}...")
        engine = LaneMarginingEngine(dev_obj, dev_key, port_number=port)

        # Verify link is Gen6 PAM4
        link_speed, modulation = engine.get_link_info()
        print(f"  Link speed:  {link_speed}")
        print(f"  Modulation:  {modulation}")

        if modulation != "PAM4":
            print(
                f"\n  Error: PAM4 3-eye sweep requires Gen6 (64 GT/s) PAM4 link."
                f"\n  Current link is {link_speed} ({modulation})."
                f"\n  Use a standard NRZ sweep for Gen4/Gen5 links."
            )
            sys.exit(1)

        print(f"\n  Starting PAM4 3-eye sweep on lane {lane}...")
        print("  This sweeps voltage and timing margins for each sub-eye.")
        print("  Typical duration: 30-120 seconds depending on step counts.\n")

        # Use a stable device_id for the module-level progress tracking
        device_id = f"dev{device_index}_port{port}"
        result = engine.sweep_lane_pam4(lane=lane, device_id=device_id)
        return result

    except TimeoutError as exc:
        logger.exception("margining_timeout")
        print(f"\n  Timeout: {exc}")
        sys.exit(1)
    except ValueError as exc:
        logger.exception("margining_value_error")
        print(f"\n  Error: {exc}")
        sys.exit(1)
    except Exception as exc:
        logger.exception("sweep_failed")
        print(f"\n  Error: sweep failed: {exc}")
        sys.exit(1)
    finally:
        if engine is not None:
            engine.close()
        device.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point for the PAM4 eye sweep CLI."""
    parser = build_parser()
    args = parser.parse_args()

    print("\n  PAM4 3-Eye Lane Margining Sweep")
    print("  PCIe 6.0.1 Lane Margining at Receiver")
    print(f"  Device: {args.device_index}  Port: {args.port}  Lane: {args.lane}")
    print("  " + "-" * 50)

    # Execute the hardware sweep
    result = run_sweep(args.device_index, args.port, args.lane)

    # Extract per-eye margins
    all_margins = extract_all_margins(result)

    # Print margin table
    print_margin_table(all_margins)

    # Print summary
    print_summary(result)

    # Compute capability maximums for diagram scaling
    caps = result.upper_eye.capabilities
    max_timing_ui = steps_to_timing_ui(caps.num_timing_steps, caps.num_timing_steps)
    max_voltage_mv = steps_to_voltage_mv(caps.num_voltage_steps, caps.num_voltage_steps)

    # Render ASCII eye diagram
    diagram = render_pam4_eye_diagram(all_margins, max_timing_ui, max_voltage_mv)
    print(f"\n{diagram}")

    # Optionally save to JSON
    if args.output is not None:
        data = build_json_output(result, all_margins, args.port, args.lane, args.device_index)
        save_json(data, args.output)

    print("")


if __name__ == "__main__":
    main()
