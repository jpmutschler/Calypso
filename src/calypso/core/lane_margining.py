"""Lane Margining sweep engine for eye diagram measurements.

Implements PCIe Base Spec 6.0.1 Section 7.7.8 Lane Margining at the Receiver.
Sweeps voltage and timing margins on a single lane to produce eye diagram data.
Supports NRZ (single eye, Gen1-5) and PAM4 (3-eye, Gen6) modulation.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.core.pcie_config import PcieConfigReader
from calypso.hardware.pcie_registers import (
    ExtCapabilityID,
    LinkStsBits,
    PCIeCapability,
    PCIeCapabilityID,
    PCIeLinkSpeed,
    SPEED_STRINGS,
)
from calypso.sdk import device as sdk_device
from calypso.models.phy import (
    LaneMarginCapabilities,
    LaneMarginingCap,
    MarginingCmd,
    MarginingLaneControl,
    MarginingLaneStatus,
    MarginingReceiverNumber,
    MarginingReportPayload,
    PAM4_EYE_LABELS,
    PAM4_RECEIVERS,
    get_modulation_for_speed,
    Modulation,
    steps_to_timing_ui,
    steps_to_voltage_mv,
)
from calypso.models.phy_api import (
    EyeSweepResult,
    LaneMarginCapabilitiesResponse,
    MarginPoint,
    PAM4SweepProgress,
    PAM4SweepResult,
    SweepProgress,
)
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

# Module-level sweep tracking, keyed by "{device_id}:{lane}"
_lock = threading.Lock()
_active_sweeps: dict[str, SweepProgress] = {}
_sweep_results: dict[str, EyeSweepResult] = {}

# PAM4 sweep tracking (separate from NRZ)
_pam4_active_sweeps: dict[str, PAM4SweepProgress] = {}
_pam4_sweep_results: dict[str, PAM4SweepResult] = {}

_POLL_INTERVAL_S = 0.02  # 20ms between status register reads
_POLL_TIMEOUT_S = 2.0  # 2s max per margin point
_CLEAR_SETTLE_S = 0.03  # 30ms for NO_COMMAND PHY ordered set round-trip
_MIN_DWELL_S = 0.2  # 200ms dwell — gives receiver time to measure before polling


def get_sweep_progress(device_id: str, lane: int) -> SweepProgress:
    """Get the current sweep progress for a device+lane."""
    key = f"{device_id}:{lane}"
    with _lock:
        return _active_sweeps.get(
            key,
            SweepProgress(
                status="idle",
                lane=lane,
                current_step=0,
                total_steps=0,
                percent=0.0,
            ),
        )


def get_sweep_result(device_id: str, lane: int) -> EyeSweepResult | None:
    """Get the completed sweep result for a device+lane."""
    with _lock:
        return _sweep_results.get(f"{device_id}:{lane}")


def get_pam4_sweep_progress(device_id: str, lane: int) -> PAM4SweepProgress:
    """Get the current PAM4 3-eye sweep progress for a device+lane."""
    key = f"{device_id}:{lane}"
    with _lock:
        return _pam4_active_sweeps.get(
            key,
            PAM4SweepProgress(
                status="idle",
                lane=lane,
                current_eye="",
                current_eye_index=0,
                overall_step=0,
                overall_total_steps=0,
                percent=0.0,
            ),
        )


def get_pam4_sweep_result(device_id: str, lane: int) -> PAM4SweepResult | None:
    """Get the completed PAM4 3-eye sweep result for a device+lane."""
    with _lock:
        return _pam4_sweep_results.get(f"{device_id}:{lane}")


def _check_balance(upper_mv: float, middle_mv: float, lower_mv: float) -> bool:
    """True if 3 eye heights are within 20% of their average."""
    avg = (upper_mv + middle_mv + lower_mv) / 3
    if avg == 0:
        return True
    return all(abs(eye - avg) / avg <= 0.2 for eye in (upper_mv, middle_mv, lower_mv))


def _build_caps_response(caps: LaneMarginCapabilities) -> LaneMarginCapabilitiesResponse:
    """Convert internal capabilities to API response model."""
    return LaneMarginCapabilitiesResponse(
        max_timing_offset=caps.max_timing_offset,
        max_voltage_offset=caps.max_voltage_offset,
        num_timing_steps=caps.num_timing_steps,
        num_voltage_steps=caps.num_voltage_steps,
        ind_up_down_voltage=caps.ind_up_down_voltage,
        ind_left_right_timing=caps.ind_left_right_timing,
        sample_count=caps.sample_count,
    )


def _count_sweep_steps(caps: LaneMarginCapabilities) -> int:
    """Count the number of margining steps for a single-receiver sweep.

    Respects ind_left_right_timing and ind_up_down_voltage capability flags:
    when a flag is False, only one direction is swept (right or up) and the
    result is mirrored, halving the step count for that axis.
    """
    timing_dirs = 2 if caps.ind_left_right_timing else 1
    voltage_dirs = 2 if caps.ind_up_down_voltage else 1
    return (caps.num_timing_steps * timing_dirs) + (caps.num_voltage_steps * voltage_dirs)


# Maximum consecutive timeouts before bailing out of a direction.
# When a receiver is non-responsive, every step takes the full poll timeout.
# Bailing early saves minutes of wasted time.
_MAX_CONSECUTIVE_TIMEOUTS = 5

# Target BER for eye boundary determination.
# Points with BER below this threshold are considered "inside the eye".
# 1% BER is a practical default — at low sample counts (128 symbols)
# it translates to just 1 error, while at high sample counts it scales up.
_EYE_BOUNDARY_BER = 0.01

# Normalized error threshold for the visual eye boundary.
# Uses the same 0–1 normalization as the heatmap; 0.5 = halfway to max error.
_EYE_NORM_THRESHOLD = 0.5


def _error_threshold_from_sample_count(sample_count: int) -> int:
    """Derive the error-count threshold from the PCIe sample count capability.

    PCIe 6.0.1 Section 7.7.8: total_samples = 128 * 2^sample_count.
    Returns the maximum error_count considered "inside the eye" at the
    target BER (_EYE_BOUNDARY_BER).
    """
    total_samples = 128 * (1 << min(sample_count, 20))
    threshold = int(total_samples * _EYE_BOUNDARY_BER)
    return max(1, min(63, threshold))  # At least 1, capped at max reportable


def _contiguous_passing_steps(
    points: list[MarginPoint],
    direction: str,
    error_threshold: int,
) -> int:
    """Find the last contiguous step from center where error <= threshold.

    Walks outward from step 1 in order; stops at the first step that
    exceeds the threshold or receives a NAK (status_code == 3).
    Returns the step number of the last passing step, or 0 if step 1 fails.
    """
    dir_points = sorted(
        (p for p in points if p.direction == direction),
        key=lambda p: p.step,
    )
    max_step = 0
    for p in dir_points:
        if p.status_code == 3:  # NAK — beyond receiver range
            break
        if p.margin_value > error_threshold:
            break
        max_step = p.step
    return max_step


class _EyeDimensions:
    """Per-direction eye margin results."""

    __slots__ = (
        "width_steps", "height_steps", "width_ui", "height_mv",
        "right_ui", "left_ui", "up_mv", "down_mv",
    )

    def __init__(
        self,
        width_steps: int, height_steps: int,
        width_ui: float, height_mv: float,
        right_ui: float, left_ui: float,
        up_mv: float, down_mv: float,
    ) -> None:
        self.width_steps = width_steps
        self.height_steps = height_steps
        self.width_ui = width_ui
        self.height_mv = height_mv
        self.right_ui = right_ui
        self.left_ui = left_ui
        self.up_mv = up_mv
        self.down_mv = down_mv


def _compute_eye_dimensions(
    timing_points: list[MarginPoint],
    voltage_points: list[MarginPoint],
    num_timing: int,
    num_voltage: int,
    sample_count: int = 0,  # kept for API compat; unused by normalized approach
) -> _EyeDimensions:
    """Compute eye width/height using normalized-error boundary.

    Uses the **same normalization** as the 2D heatmap so the eye boundary
    overlay aligns with the visual.  Per-direction errors are normalized
    to 0–1 (by max error when a gradient exists, by step-distance when
    errors are constant).  The eye boundary is the last contiguous step
    in each direction where normalized error ≤ _EYE_NORM_THRESHOLD.

    Returns an _EyeDimensions with total and per-direction values.
    """
    # --- Group usable points (exclude NAK and timed-out) by direction ---
    dir_pts: dict[str, list[MarginPoint]] = {
        "right": [], "left": [], "up": [], "down": [],
    }
    for p in timing_points:
        if p.status_code != 3 and not p.timed_out:
            dir_pts[p.direction].append(p)
    for p in voltage_points:
        if p.status_code != 3 and not p.timed_out:
            dir_pts[p.direction].append(p)

    # --- Detect gradient per axis ---
    t_errors = [
        p.margin_value for d in ("right", "left")
        for p in dir_pts[d] if p.margin_value > 0
    ]
    v_errors = [
        p.margin_value for d in ("up", "down")
        for p in dir_pts[d] if p.margin_value > 0
    ]
    t_has_gradient = len(set(t_errors)) > 1
    v_has_gradient = len(set(v_errors)) > 1
    max_t_err = max(t_errors) if t_errors else 1
    max_v_err = max(v_errors) if v_errors else 1

    # --- Max usable step per direction (for no-gradient fallback) ---
    max_usable: dict[str, int] = {}
    for d in ("right", "left", "up", "down"):
        steps = [p.step for p in dir_pts[d]]
        max_usable[d] = max(steps) if steps else 0

    # --- Find boundary step per direction ---
    def _boundary_step(direction: str, is_timing: bool) -> int:
        pts = sorted(dir_pts[direction], key=lambda p: p.step)
        has_grad = t_has_gradient if is_timing else v_has_gradient
        m_err = max_t_err if is_timing else max_v_err
        mx = max_usable[direction]
        boundary = 0
        for p in pts:
            if has_grad:
                norm = p.margin_value / m_err if m_err > 0 else 1.0
            else:
                norm = p.step / mx if mx > 0 else 1.0
            if norm > _EYE_NORM_THRESHOLD:
                break
            boundary = p.step
        return boundary

    max_right = _boundary_step("right", is_timing=True)
    max_left = _boundary_step("left", is_timing=True)
    max_up = _boundary_step("up", is_timing=False)
    max_down = _boundary_step("down", is_timing=False)

    right_ui = steps_to_timing_ui(max_right, num_timing)
    left_ui = steps_to_timing_ui(max_left, num_timing)
    up_mv = steps_to_voltage_mv(max_up, num_voltage)
    down_mv = steps_to_voltage_mv(max_down, num_voltage)

    return _EyeDimensions(
        width_steps=max_left + max_right,
        height_steps=max_up + max_down,
        width_ui=left_ui + right_ui,
        height_mv=up_mv + down_mv,
        right_ui=right_ui,
        left_ui=left_ui,
        up_mv=up_mv,
        down_mv=down_mv,
    )


class LaneMarginingEngine:
    """Executes lane margining sweeps on a target port's config space.

    Opens a separate device handle when targeting a non-management port,
    following the proven topology/port-manager pattern for per-port access.
    """

    def __init__(
        self,
        device: PLX_DEVICE_OBJECT,
        device_key: PLX_DEVICE_KEY,
        port_number: int = 0,
    ) -> None:
        self._port_device: PLX_DEVICE_OBJECT | None = None

        props = sdk_device.get_port_properties(device)
        if props.PortNumber == port_number:
            # Management port IS the target — use existing handle
            reader_device = device
        else:
            # Find and open the target port
            target_key = self._find_port_key(device_key, port_number)
            if target_key is None:
                raise ValueError(
                    f"Port {port_number} not found. "
                    f"Ensure it is configured and the link is active."
                )
            self._port_device = sdk_device.open_device(target_key)
            reader_device = self._port_device

        # PcieConfigReader for all register access (handle-based OS config path).
        # Both capability walk and margining commands must use the same path
        # to ensure register offsets map correctly.
        self._config = PcieConfigReader(reader_device, device_key)

        try:
            self._margining_offset = self._config.find_extended_capability(
                ExtCapabilityID.RECEIVER_LANE_MARGINING,
            )
        except Exception:
            self.close()
            raise

        if self._margining_offset is None:
            self.close()
            raise ValueError(
                f"Lane Margining capability not found on port {port_number}"
            )

    def close(self) -> None:
        """Release the opened port device handle, if any."""
        if self._port_device is not None:
            try:
                sdk_device.close_device(self._port_device)
            except Exception:
                logger.debug("close_device_failed", exc_info=True)
            self._port_device = None

    @staticmethod
    def _find_port_key(
        mgmt_key: PLX_DEVICE_KEY, port_number: int
    ) -> PLX_DEVICE_KEY | None:
        """Find a device key whose hardware PortNumber matches.

        PlxPort (SDK index) does not always equal the hardware PortNumber,
        so we open each candidate and check get_port_properties().PortNumber.
        This mirrors the pattern used by PortManager.get_all_port_statuses().
        """
        from calypso.bindings.constants import PlxApiMode

        all_keys = sdk_device.find_devices(api_mode=PlxApiMode(mgmt_key.ApiMode))
        for key in all_keys:
            try:
                dev = sdk_device.open_device(key)
                try:
                    props = sdk_device.get_port_properties(dev)
                    found = props.PortNumber == port_number
                finally:
                    sdk_device.close_device(dev)
                if found:
                    return key
            except Exception:
                continue
        return None

    def _cfg_read(self, offset: int) -> int:
        """Read a config register via the port's device handle."""
        return self._config.read_config_register(offset)

    def _cfg_write(self, offset: int, value: int) -> None:
        """Write a config register via the port's device handle."""
        self._config.write_config_register(offset, value)

    def _get_link_state(self) -> tuple[int, bool, bool]:
        """Read link speed code, DLL Link Active, and Link Training from Link Status.

        Returns (speed_code, dll_link_active, link_training).
        speed_code: 1=Gen1 .. 6=Gen6, 0 on failure.
        """
        try:
            pcie_cap = self._config.find_capability(PCIeCapabilityID.PCIE)
            if pcie_cap is None:
                return (0, False, False)
            link_ctl_sts = self._cfg_read(pcie_cap + PCIeCapability.LINK_CTL)
            status_word = (link_ctl_sts >> 16) & 0xFFFF
            speed = status_word & int(LinkStsBits.CURRENT_LINK_SPEED_MASK)
            dll_active = bool(status_word & LinkStsBits.DL_LINK_ACTIVE)
            training = bool(status_word & LinkStsBits.LINK_TRAINING)
            return (speed, dll_active, training)
        except Exception:
            return (0, False, False)

    def _format_link_speed(self, code: int) -> str:
        """Format a speed code as a human-readable string."""
        try:
            return SPEED_STRINGS[PCIeLinkSpeed(code)]
        except (ValueError, KeyError):
            return f"Unknown(0x{code:X})"

    def _read_diag(self) -> dict[str, str]:
        """Collect diagnostic register reads for troubleshooting."""
        diag: dict[str, str] = {}
        try:
            speed_code, dll_active, training = self._get_link_state()
            diag["link_speed"] = self._format_link_speed(speed_code)
            diag["dll_link_active"] = str(dll_active)
            diag["link_training"] = str(training)

            cap_header = self._cfg_read(self._margining_offset)
            cap_id = cap_header & 0xFFFF
            diag["cap_header"] = f"0x{cap_header:08X} (cap_id=0x{cap_id:04X})"

            port_dword = self._cfg_read(
                self._margining_offset + LaneMarginingCap.PORT_CAP
            )
            port_cap = port_dword & 0xFFFF
            port_status = (port_dword >> 16) & 0xFFFF
            diag["port_cap"] = f"0x{port_cap:04X}"
            diag["port_status"] = f"0x{port_status:04X}"
            diag["margining_ready"] = str(bool(port_status & 0x1))

            lane0_dword = self._cfg_read(
                self._margining_offset + LaneMarginingCap.LANE_CONTROL_BASE
            )
            lane0_ctrl = lane0_dword & 0xFFFF
            lane0_status = (lane0_dword >> 16) & 0xFFFF
            diag["lane0_ctrl"] = f"0x{lane0_ctrl:04X}"
            diag["lane0_status"] = f"0x{lane0_status:04X}"
        except Exception as exc:
            diag["diag_error"] = str(exc)
        return diag

    def is_margining_ready(self) -> bool:
        """Check whether the port's Margining Ready bit is set in Port Status."""
        dword = self._cfg_read(self._margining_offset + LaneMarginingCap.PORT_CAP)
        # Port Status is upper 16 bits (offset 0x06); bit 0 = Margining Ready
        port_status = (dword >> 16) & 0xFFFF
        return bool(port_status & 0x1)

    def _clear_lane_command(self, lane: int, receiver: MarginingReceiverNumber) -> None:
        """Write NO_COMMAND to the lane control register and wait for the PHY.

        Per PCIe 6.0.1 Section 7.7.8.4, software must write No Command to the
        Margin Type field before writing a new margin command. The receiver only
        processes commands when it sees a transition FROM No Command.

        Uses a fixed 100ms settle delay. The status register is NOT polled because
        NO_COMMAND does not generate its own response — the status retains the
        last non-NO_COMMAND response indefinitely.
        """
        clear = MarginingLaneControl(
            receiver_number=receiver,
            margin_type=MarginingCmd.NO_COMMAND,
            usage_model=0,
            margin_payload=0,
        )
        self._write_lane_control(lane, clear)
        time.sleep(_CLEAR_SETTLE_S)

    def _try_report_command(
        self,
        lane: int,
        receiver: MarginingReceiverNumber,
        report_payload: int,
        settle_s: float = _CLEAR_SETTLE_S,
    ) -> tuple[int | None, MarginingLaneStatus | None]:
        """Single attempt at sending a report command.

        Returns (payload, None) on success or (None, last_status) on timeout.
        """
        # Log status register state before we begin
        pre_status = self._read_lane_status(lane)
        logger.debug(
            "report_pre_status",
            payload=f"0x{report_payload:02X}",
            status_type=pre_status.margin_type.name,
            status_receiver=pre_status.receiver_number,
            status_payload=f"0x{pre_status.margin_payload:02X}",
        )

        # Clear to NO_COMMAND (mandatory per spec Section 7.7.8.4)
        clear = MarginingLaneControl(
            receiver_number=receiver,
            margin_type=MarginingCmd.NO_COMMAND,
            usage_model=0,
            margin_payload=0,
        )
        self._write_lane_control(lane, clear)
        time.sleep(settle_s)

        # Write the actual report command
        control = MarginingLaneControl(
            receiver_number=receiver,
            margin_type=MarginingCmd.ACCESS_RECEIVER_MARGIN_CONTROL,
            usage_model=0,
            margin_payload=report_payload,
        )
        self._write_lane_control(lane, control)

        # Readback to verify write took effect
        offset = self._lane_control_offset(lane)
        readback = self._cfg_read(offset)
        ctrl_word = readback & 0xFFFF
        expected = control.to_register()
        if ctrl_word != expected:
            logger.warning(
                "report_ctrl_mismatch",
                expected=f"0x{expected:04X}",
                readback=f"0x{ctrl_word:04X}",
            )

        # Poll until status margin_type echoes the command
        deadline = time.monotonic() + _POLL_TIMEOUT_S
        last_status: MarginingLaneStatus | None = None
        while time.monotonic() < deadline:
            time.sleep(_POLL_INTERVAL_S)
            last_status = self._read_lane_status(lane)
            if last_status.margin_type == MarginingCmd.ACCESS_RECEIVER_MARGIN_CONTROL:
                return last_status.margin_payload, None

        return None, last_status

    def _send_report_command(
        self,
        lane: int,
        receiver: MarginingReceiverNumber,
        report_payload: int,
    ) -> int:
        """Send an ACCESS_RECEIVER_MARGIN_CONTROL report command.

        Returns the 8-bit margin_payload from the Lane Status response register.
        Per PCIe 6.0.1, clears to NO_COMMAND first so the receiver sees a valid
        transition, then polls until the response margin_type echoes back.

        If the first attempt times out (e.g. stale GO_TO_NORMAL_SETTINGS after a
        previous sweep), retries once with a longer settle time.
        """
        # First attempt with normal settle time
        result, last_status = self._try_report_command(lane, receiver, report_payload)
        if result is not None:
            return result

        # First attempt failed — retry with longer settle (500ms)
        logger.warning(
            "report_command_retry",
            payload=f"0x{report_payload:02X}",
            last_status_type=last_status.margin_type.name if last_status else "none",
        )
        result, last_status = self._try_report_command(
            lane, receiver, report_payload, settle_s=0.5,
        )
        if result is not None:
            return result

        # Both attempts failed — build diagnostic message
        diag = self._read_diag()
        diag["margining_offset"] = f"0x{self._margining_offset:X}"
        # Read raw lane DWORD for complete picture
        offset = self._lane_control_offset(lane)
        raw_dword = self._cfg_read(offset)
        diag["raw_lane_dword"] = f"0x{raw_dword:08X}"
        control = MarginingLaneControl(
            receiver_number=receiver,
            margin_type=MarginingCmd.ACCESS_RECEIVER_MARGIN_CONTROL,
            usage_model=0,
            margin_payload=report_payload,
        )
        diag["control_written"] = f"0x{control.to_register():04X}"
        if last_status is not None:
            diag["last_status_type"] = last_status.margin_type.name
            diag["last_status_payload"] = f"0x{last_status.margin_payload:02X}"
        diag_str = ", ".join(f"{k}={v}" for k, v in diag.items())

        raise TimeoutError(
            f"Report command 0x{report_payload:02X} timed out. Diag: {diag_str}"
        )

    _MIN_MARGINING_SPEED = PCIeLinkSpeed.GEN4  # 16 GT/s — first gen with margining

    def get_link_info(self) -> tuple[str, str]:
        """Get the target port's link speed and modulation.

        Returns (link_speed_str, modulation) where modulation is "NRZ" or "PAM4".
        """
        speed_code, _, _ = self._get_link_state()
        speed_str = self._format_link_speed(speed_code)
        mod = "PAM4" if get_modulation_for_speed(speed_code) == Modulation.PAM4 else "NRZ"
        return speed_str, mod

    def _resolve_receiver(
        self,
        receiver: MarginingReceiverNumber,
        speed_code: int,
    ) -> MarginingReceiverNumber:
        """Auto-select a valid receiver number based on link speed.

        Per PCIe 6.0.1 Table 7-51, receiver number 000b is RESERVED at
        64 GT/s (Gen6 PAM4). Hardware SHALL NOT respond to commands with
        receiver 000b at that speed. At Gen6:
          - Use RECEIVER_A (001b) for per-receiver queries/sweeps
          - Use PAM4_BROADCAST (111b) for reset/broadcast operations

        At NRZ speeds (Gen4/5), receiver 000b is the single valid default.
        """
        if (
            receiver == MarginingReceiverNumber.BROADCAST
            and get_modulation_for_speed(speed_code) == Modulation.PAM4
        ):
            return MarginingReceiverNumber.RECEIVER_A
        return receiver

    def get_capabilities(
        self,
        lane: int = 0,
        receiver: MarginingReceiverNumber = MarginingReceiverNumber.BROADCAST,
    ) -> LaneMarginCapabilities:
        """Query lane margining capabilities using the command protocol.

        Per PCIe 6.0.1 Section 7.7.8, capabilities are obtained by sending
        ACCESS_RECEIVER_MARGIN_CONTROL report commands on a per-lane basis
        and reading the response from the Lane Status register.
        """
        speed_code, dll_active, training = self._get_link_state()

        if not dll_active:
            current = self._format_link_speed(speed_code)
            raise ValueError(
                f"Link is not active (DLL Link Active=0). "
                f"LTSSM must reach L0 before margining can operate. "
                f"Reported speed: {current}, training={training}."
            )

        if speed_code < self._MIN_MARGINING_SPEED:
            current = self._format_link_speed(speed_code)
            raise ValueError(
                f"Lane Margining requires Gen4 (16 GT/s) or higher. "
                f"Current link speed: {current}."
            )

        if not self.is_margining_ready():
            raise ValueError("Port is not ready for margining (Margining Ready bit not set)")

        # At Gen6 (64 GT/s), receiver 000b is reserved — auto-resolve to a valid value
        receiver = self._resolve_receiver(receiver, speed_code)

        # Cancel any in-progress margining from a previous sweep.
        # At Gen6 PAM4, use PAM4_BROADCAST to reset ALL 3 receivers at once.
        reset_rx = (
            MarginingReceiverNumber.PAM4_BROADCAST
            if get_modulation_for_speed(speed_code) == Modulation.PAM4
            else receiver
        )
        self._clear_lane_command(lane, reset_rx)
        go_normal = MarginingLaneControl(
            receiver_number=reset_rx,
            margin_type=MarginingCmd.GO_TO_NORMAL_SETTINGS,
            usage_model=0,
            margin_payload=0,
        )
        self._write_lane_control(lane, go_normal)

        # Poll until the status register confirms GO_TO_NORMAL was processed
        go_deadline = time.monotonic() + 2.0
        while time.monotonic() < go_deadline:
            time.sleep(_POLL_INTERVAL_S)
            status = self._read_lane_status(lane)
            if status.margin_type == MarginingCmd.GO_TO_NORMAL_SETTINGS:
                break

        # Extra settle after GO_TO_NORMAL before sending report commands
        self._clear_lane_command(lane, receiver)
        time.sleep(0.1)

        def _report(payload: int) -> int:
            return self._send_report_command(lane, receiver, payload)

        # Report Margin Control Capabilities (response bits: Table 7-52)
        caps_byte = _report(MarginingReportPayload.CAPABILITIES)

        return LaneMarginCapabilities(
            max_voltage_offset=_report(MarginingReportPayload.MAX_VOLTAGE_OFFSET) & 0x3F,
            num_voltage_steps=_report(MarginingReportPayload.NUM_VOLTAGE_STEPS) & 0x3F,
            max_timing_offset=_report(MarginingReportPayload.MAX_TIMING_OFFSET) & 0x3F,
            num_timing_steps=_report(MarginingReportPayload.NUM_TIMING_STEPS) & 0x3F,
            sample_count=_report(MarginingReportPayload.SAMPLE_COUNT) & 0x3F,
            sample_rate_voltage=bool(
                _report(MarginingReportPayload.SAMPLING_RATE_VOLTAGE) & 0x01,
            ),
            sample_rate_timing=bool(
                _report(MarginingReportPayload.SAMPLING_RATE_TIMING) & 0x01,
            ),
            ind_up_down_voltage=bool(caps_byte & 0x02),
            ind_left_right_timing=bool(caps_byte & 0x04),
        )

    def _lane_control_offset(self, lane: int) -> int:
        """Calculate the register offset for a lane's control/status DWORD."""
        return self._margining_offset + LaneMarginingCap.LANE_CONTROL_BASE + (lane * 4)

    def _write_lane_control(self, lane: int, control: MarginingLaneControl) -> None:
        """Write the lane control register (low 16 bits of the lane DWORD)."""
        offset = self._lane_control_offset(lane)
        current = self._cfg_read(offset)
        new_value = (current & 0xFFFF0000) | (control.to_register() & 0xFFFF)
        self._cfg_write(offset, new_value)

    def _read_lane_status(self, lane: int) -> MarginingLaneStatus:
        """Read the lane status register (high 16 bits of the lane DWORD)."""
        offset = self._lane_control_offset(lane)
        dword = self._cfg_read(offset)
        status_word = (dword >> 16) & 0xFFFF
        return MarginingLaneStatus.from_register(status_word)

    def _margin_single_point(
        self,
        lane: int,
        cmd: MarginingCmd,
        receiver: MarginingReceiverNumber,
        payload: int,
    ) -> MarginingLaneStatus:
        """Issue a single margining command and poll until complete or timeout.

        Clears to NO_COMMAND first (mandatory per spec Section 7.7.8.4),
        writes the margin command, waits a minimum dwell time, then polls
        for a response where margin_type matches the command.

        The dwell time prevents stale data from the previous step (consecutive
        commands with the same margin_type). Between receivers, the
        GO_TO_NORMAL reset changes margin_type in the status register,
        making stale cross-receiver data distinguishable.

        receiver_number is NOT checked in the poll because some hardware
        echoes receiver_number=0 (BROADCAST) regardless of the addressed
        receiver, causing legitimate responses to be rejected.
        """
        # Clear to NO_COMMAND first (mandatory per spec Section 7.7.8.4)
        self._clear_lane_command(lane, receiver)

        control = MarginingLaneControl(
            receiver_number=receiver,
            margin_type=cmd,
            usage_model=0,
            margin_payload=payload,
        )
        self._write_lane_control(lane, control)

        # Minimum dwell before accepting — prevents stale same-type data
        time.sleep(_MIN_DWELL_S)

        deadline = time.monotonic() + _POLL_TIMEOUT_S
        while time.monotonic() < deadline:
            status = self._read_lane_status(lane)

            # Accept when margin_type matches and not in setup phase.
            # receiver_number is intentionally not checked — some hardware
            # echoes a different receiver_number than addressed.
            if status.margin_type == cmd and not status.is_setup:
                return status

            time.sleep(_POLL_INTERVAL_S)

        # Timed out — return last status for diagnostics
        return self._read_lane_status(lane)

    def _go_to_normal_and_confirm(
        self, lane: int, receiver: MarginingReceiverNumber
    ) -> None:
        """Send GO_TO_NORMAL_SETTINGS and poll until the status register confirms.

        This ensures the status register's margin_type changes to
        GO_TO_NORMAL_SETTINGS, flushing any stale response from a previous
        command. Critical between directions that share the same margin_type
        (right→left timing, up→down voltage) to prevent the next direction's
        poll from matching stale data.
        """
        self._clear_lane_command(lane, receiver)
        control = MarginingLaneControl(
            receiver_number=receiver,
            margin_type=MarginingCmd.GO_TO_NORMAL_SETTINGS,
            usage_model=0,
            margin_payload=0,
        )
        self._write_lane_control(lane, control)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            time.sleep(_POLL_INTERVAL_S)
            status = self._read_lane_status(lane)
            if status.margin_type == MarginingCmd.GO_TO_NORMAL_SETTINGS:
                return
        logger.warning(
            "go_to_normal_confirm_timeout", lane=lane, receiver=int(receiver)
        )

    def reset_lane(
        self, lane: int, receiver: MarginingReceiverNumber = MarginingReceiverNumber.BROADCAST
    ) -> None:
        """Send GO_TO_NORMAL_SETTINGS to restore normal operation.

        At Gen6 PAM4, uses PAM4_BROADCAST (111b) instead of BROADCAST (000b)
        to reset all three receivers simultaneously. Polls until the status
        register confirms the reset took effect.
        """
        # At Gen6, receiver 000b is reserved — use PAM4_BROADCAST for resets
        speed_code, _, _ = self._get_link_state()
        if (
            receiver == MarginingReceiverNumber.BROADCAST
            and get_modulation_for_speed(speed_code) == Modulation.PAM4
        ):
            receiver = MarginingReceiverNumber.PAM4_BROADCAST

        self._go_to_normal_and_confirm(lane, receiver)

    def _execute_single_sweep(
        self,
        lane: int,
        receiver: MarginingReceiverNumber,
        progress_callback: Callable[[int, int], None] | None = None,
        caps: LaneMarginCapabilities | None = None,
    ) -> EyeSweepResult:
        """Core sweep for one receiver. No module-level state writes.

        Sweeps timing and voltage directions, respecting the ind_left_right_timing
        and ind_up_down_voltage capability flags.  When an independent flag is
        False, only one direction is swept and the result is mirrored for the
        opposite direction.

        Calls progress_callback(current_step, total_steps) after each point.
        If caps is provided, skips the hardware capabilities query.
        """
        start_ms = int(time.monotonic() * 1000)

        if caps is None:
            caps = self.get_capabilities(lane=lane, receiver=receiver)
        num_timing = caps.num_timing_steps
        num_voltage = caps.num_voltage_steps
        total_steps = _count_sweep_steps(caps)

        if total_steps == 0:
            raise ValueError("Device reports 0 margining steps (margining not supported)")

        logger.info(
            "sweep_capabilities",
            receiver=int(receiver),
            num_timing=num_timing,
            num_voltage=num_voltage,
            ind_left_right=caps.ind_left_right_timing,
            ind_up_down=caps.ind_up_down_voltage,
            total_steps=total_steps,
        )

        timing_points: list[MarginPoint] = []
        voltage_points: list[MarginPoint] = []
        step_count = 0

        # Build direction list based on capability flags.  Per PCIe 6.0.1
        # Section 7.7.8, when ind_left_right_timing is False the timing
        # margins are symmetric — sweep only one direction and mirror.
        # Same for ind_up_down_voltage.
        directions: list[tuple[str, MarginingCmd, int, list[MarginPoint]]] = [
            ("right", MarginingCmd.MARGIN_TIMING, num_timing, timing_points),
        ]
        if caps.ind_left_right_timing:
            directions.append(
                ("left", MarginingCmd.MARGIN_TIMING, num_timing, timing_points),
            )
        directions.append(
            ("up", MarginingCmd.MARGIN_VOLTAGE, num_voltage, voltage_points),
        )
        if caps.ind_up_down_voltage:
            directions.append(
                ("down", MarginingCmd.MARGIN_VOLTAGE, num_voltage, voltage_points),
            )

        prev_cmd: MarginingCmd | None = None
        for direction, cmd, num_steps, point_list in directions:
            # Between directions sharing the same margin_type (right→left
            # timing, up→down voltage), send GO_TO_NORMAL to flush stale
            # data from the status register.
            if prev_cmd is not None and prev_cmd == cmd:
                logger.debug(
                    "direction_transition_reset",
                    direction=direction,
                    margin_type=cmd.name,
                )
                self._go_to_normal_and_confirm(lane, receiver)
            prev_cmd = cmd

            dir_status_codes: dict[int, int] = {}  # status_code -> count
            dir_error_counts: dict[int, int] = {}  # margin_value -> count
            dir_passed = 0
            dir_timed_out = 0
            consecutive_timeouts = 0

            for step in range(1, num_steps + 1):
                # Early bailout: if receiver is non-responsive (many consecutive
                # timeouts), skip remaining steps for this direction.  Each
                # timeout costs the full poll timeout (~2s), so bailing early
                # saves minutes on non-responsive receivers (e.g., Rx B/C).
                if consecutive_timeouts >= _MAX_CONSECUTIVE_TIMEOUTS:
                    remaining = num_steps - step + 1
                    logger.warning(
                        "direction_bailout",
                        direction=direction,
                        receiver=int(receiver),
                        after_step=step - 1,
                        consecutive_timeouts=consecutive_timeouts,
                        remaining_skipped=remaining,
                    )
                    # Fill remaining steps as timed-out failures
                    for skip_step in range(step, num_steps + 1):
                        point_list.append(
                            MarginPoint(
                                direction=direction,
                                step=skip_step,
                                margin_value=0,
                                status_code=0,
                                passed=False,
                                timed_out=True,
                            )
                        )
                        dir_timed_out += 1
                        step_count += 1
                        if progress_callback is not None:
                            progress_callback(step_count, total_steps)
                    break

                payload = step & 0x3F
                # Per PCIe 6.0.1 Table 7-51:
                #   Timing: direction in bit 7 (0=right/decrease, 1=left/increase)
                #   Voltage: direction in bit 6 (0=up/increase, 1=down/decrease)
                if direction == "left":
                    payload |= 1 << 7
                elif direction == "down":
                    payload |= 1 << 6

                status = self._margin_single_point(lane, cmd, receiver, payload)

                # Check if poll timed out (margin_type mismatch means no response)
                timed_out = status.margin_type != cmd
                if timed_out:
                    dir_timed_out += 1
                    consecutive_timeouts += 1
                else:
                    consecutive_timeouts = 0

                # A point "passes" when the receiver reports clean margin:
                #   - status_code 2 (10b): spec "margining passed" (no errors)
                #   - error_count == 0: zero errors detected (industry standard
                #     criterion; some receivers report status_code=0 even with
                #     0 errors due to firmware quirks)
                # NAK (status_code 3) means "cannot execute" — never passed,
                # even though margin_value may read 0.
                # If timed out, the response is stale — treat as failed
                # regardless of the status_code in the stale payload.
                passed = (
                    (status.is_passed or status.error_count == 0)
                    and not timed_out
                    and status.status_code != 3
                )
                if passed:
                    dir_passed += 1
                dir_status_codes[status.status_code] = (
                    dir_status_codes.get(status.status_code, 0) + 1
                )

                # Log first 3 and last 3 points per direction for diagnostics
                if step <= 3 or step > num_steps - 3:
                    logger.info(
                        "margin_point_detail",
                        direction=direction,
                        step=step,
                        receiver=int(receiver),
                        status_receiver=int(status.receiver_number),
                        margin_type=status.margin_type.name,
                        margin_type_match=status.margin_type == cmd,
                        receiver_match=status.receiver_number == receiver,
                        status_code=status.status_code,
                        margin_value=status.margin_value,
                        margin_payload=f"0x{status.margin_payload:02X}",
                        passed=passed,
                        timed_out=timed_out,
                    )

                dir_error_counts[status.margin_value] = (
                    dir_error_counts.get(status.margin_value, 0) + 1
                )
                point_list.append(
                    MarginPoint(
                        direction=direction,
                        step=step,
                        margin_value=status.margin_value,
                        status_code=status.status_code,
                        passed=passed,
                        timed_out=timed_out,
                    )
                )
                step_count += 1
                if progress_callback is not None:
                    progress_callback(step_count, total_steps)

            # Summary per direction — includes error count distribution
            # to distinguish real data (varying counts) from stale data (all same)
            logger.info(
                "margin_direction_summary",
                direction=direction,
                receiver=int(receiver),
                total_points=num_steps,
                passed=dir_passed,
                timed_out=dir_timed_out,
                status_code_dist=dir_status_codes,
                error_count_dist=dir_error_counts,
            )

        # Mirror single-direction data when independent capability is False.
        # Per PCIe 6.0.1 Section 7.7.8, symmetric margins mean we only need
        # to measure one direction; the opposite is identical.
        if not caps.ind_left_right_timing:
            for p in list(timing_points):
                if p.direction == "right":
                    timing_points.append(
                        MarginPoint(
                            direction="left",
                            step=p.step,
                            margin_value=p.margin_value,
                            status_code=p.status_code,
                            passed=p.passed,
                            timed_out=p.timed_out,
                        )
                    )
        if not caps.ind_up_down_voltage:
            for p in list(voltage_points):
                if p.direction == "up":
                    voltage_points.append(
                        MarginPoint(
                            direction="down",
                            step=p.step,
                            margin_value=p.margin_value,
                            status_code=p.status_code,
                            passed=p.passed,
                            timed_out=p.timed_out,
                        )
                    )

        eye = _compute_eye_dimensions(
            timing_points,
            voltage_points,
            num_timing,
            num_voltage,
            sample_count=caps.sample_count,
        )

        elapsed_ms = int(time.monotonic() * 1000) - start_ms

        return EyeSweepResult(
            lane=lane,
            receiver=int(receiver),
            timing_points=timing_points,
            voltage_points=voltage_points,
            capabilities=_build_caps_response(caps),
            eye_width_steps=eye.width_steps,
            eye_height_steps=eye.height_steps,
            eye_width_ui=round(eye.width_ui, 4),
            eye_height_mv=round(eye.height_mv, 2),
            margin_right_ui=round(eye.right_ui, 4),
            margin_left_ui=round(eye.left_ui, 4),
            margin_up_mv=round(eye.up_mv, 2),
            margin_down_mv=round(eye.down_mv, 2),
            sweep_time_ms=elapsed_ms,
        )

    def sweep_lane(
        self,
        lane: int,
        device_id: str,
        receiver: MarginingReceiverNumber = MarginingReceiverNumber.BROADCAST,
    ) -> EyeSweepResult:
        """Execute a full timing + voltage sweep on one lane.

        Updates _active_sweeps progress in-place as each point completes.
        Stores the final result in _sweep_results.
        """
        key = f"{device_id}:{lane}"

        # Signal "running" immediately so the UI sees feedback before pre-flight
        with _lock:
            _active_sweeps[key] = SweepProgress(
                status="running",
                lane=lane,
                current_step=0,
                total_steps=0,
                percent=0.0,
            )

        # At Gen6, receiver 000b is reserved — auto-resolve before use
        speed_code, _, _ = self._get_link_state()
        receiver = self._resolve_receiver(receiver, speed_code)

        # Pre-flight: get total steps for progress tracking
        caps = self.get_capabilities(lane=lane, receiver=receiver)
        total_steps = _count_sweep_steps(caps)

        if total_steps == 0:
            error_msg = "Device reports 0 margining steps (margining not supported)"
            with _lock:
                _active_sweeps[key] = SweepProgress(
                    status="error",
                    lane=lane,
                    current_step=0,
                    total_steps=0,
                    percent=0.0,
                    error=error_msg,
                )
            raise ValueError(error_msg)

        # Update with actual total now that pre-flight is complete
        with _lock:
            _active_sweeps[key] = SweepProgress(
                status="running",
                lane=lane,
                current_step=0,
                total_steps=total_steps,
                percent=0.0,
            )

        def _progress(current_step: int, total: int) -> None:
            with _lock:
                _active_sweeps[key] = SweepProgress(
                    status="running",
                    lane=lane,
                    current_step=current_step,
                    total_steps=total,
                    percent=(current_step / total) * 100,
                )

        try:
            result = self._execute_single_sweep(lane, receiver, _progress, caps=caps)
            self.reset_lane(lane, receiver)
        except Exception as exc:
            logger.error("sweep_failed", lane=lane, error=str(exc))
            self.reset_lane(lane, receiver)
            with _lock:
                _active_sweeps[key] = SweepProgress(
                    status="error",
                    lane=lane,
                    current_step=0,
                    total_steps=total_steps,
                    percent=0.0,
                    error=str(exc),
                )
            raise

        with _lock:
            _sweep_results[key] = result
            _active_sweeps[key] = SweepProgress(
                status="complete",
                lane=lane,
                current_step=total_steps,
                total_steps=total_steps,
                percent=100.0,
            )

        return result

    def sweep_lane_pam4(self, lane: int, device_id: str) -> PAM4SweepResult:
        """Execute a PAM4 3-eye sweep (Receivers A/B/C) on one lane.

        Sweeps each of the 3 PAM4 eyes independently using per-receiver
        margining commands, then aggregates the results.
        """
        key = f"{device_id}:{lane}"
        start_ms = int(time.monotonic() * 1000)

        # Signal "running" immediately so the UI sees feedback before pre-flight
        with _lock:
            _pam4_active_sweeps[key] = PAM4SweepProgress(
                status="running",
                lane=lane,
                current_eye="pre-flight",
                current_eye_index=0,
                overall_step=0,
                overall_total_steps=0,
                percent=0.0,
            )

        # Pre-flight: query capabilities once with RECEIVER_A.
        # Capabilities (num_timing_steps, num_voltage_steps, etc.) are port-level
        # properties per PCIe 6.0.1 Table 7-52, identical across all receivers.
        # Some hardware only responds to report commands on RECEIVER_A.
        caps = self.get_capabilities(lane=lane, receiver=MarginingReceiverNumber.RECEIVER_A)
        steps_per_eye = _count_sweep_steps(caps)

        # Reset lane after pre-flight so each eye sweep starts from a clean state
        self.reset_lane(lane)

        overall_total = steps_per_eye * len(PAM4_RECEIVERS)
        if overall_total == 0:
            error_msg = "Device reports 0 margining steps for all PAM4 receivers"
            with _lock:
                _pam4_active_sweeps[key] = PAM4SweepProgress(
                    status="error",
                    lane=lane,
                    current_eye="",
                    current_eye_index=0,
                    overall_step=0,
                    overall_total_steps=0,
                    percent=0.0,
                    error=error_msg,
                )
            raise ValueError(error_msg)

        # Update with actual total now that pre-flight is complete
        with _lock:
            _pam4_active_sweeps[key] = PAM4SweepProgress(
                status="running",
                lane=lane,
                current_eye=PAM4_EYE_LABELS[0],
                current_eye_index=0,
                overall_step=0,
                overall_total_steps=overall_total,
                percent=0.0,
            )

        eye_results: list[EyeSweepResult] = []
        completed_steps = 0

        try:
            for eye_idx, (rx, label) in enumerate(
                zip(PAM4_RECEIVERS, PAM4_EYE_LABELS)
            ):
                with _lock:
                    _pam4_active_sweeps[key] = PAM4SweepProgress(
                        status="running",
                        lane=lane,
                        current_eye=label,
                        current_eye_index=eye_idx,
                        overall_step=completed_steps,
                        overall_total_steps=overall_total,
                        percent=(completed_steps / overall_total) * 100,
                    )

                base_steps = completed_steps

                def _progress(
                    current_step: int,
                    total: int,
                    _base=base_steps,
                    _label=label,
                    _eye_idx=eye_idx,
                ) -> None:
                    overall_current = _base + current_step
                    with _lock:
                        _pam4_active_sweeps[key] = PAM4SweepProgress(
                            status="running",
                            lane=lane,
                            current_eye=_label,
                            current_eye_index=_eye_idx,
                            overall_step=overall_current,
                            overall_total_steps=overall_total,
                            percent=(overall_current / overall_total) * 100,
                        )

                # Reset before each eye to ensure clean state, then sweep.
                # Use pre-fetched caps (from Rx A) — some hardware only responds
                # to report commands on RECEIVER_A.
                self.reset_lane(lane, rx)
                result = self._execute_single_sweep(lane, rx, _progress, caps=caps)
                eye_results.append(result)
                completed_steps += steps_per_eye

                # Reset after each eye sweep
                self.reset_lane(lane, rx)

        except Exception as exc:
            logger.error("pam4_sweep_failed", lane=lane, error=str(exc))
            # Reset all receivers on error
            for rx in PAM4_RECEIVERS:
                try:
                    self.reset_lane(lane, rx)
                except Exception:
                    pass
            with _lock:
                _pam4_active_sweeps[key] = PAM4SweepProgress(
                    status="error",
                    lane=lane,
                    current_eye="",
                    current_eye_index=0,
                    overall_step=completed_steps,
                    overall_total_steps=overall_total,
                    percent=(completed_steps / overall_total) * 100 if overall_total else 0,
                    error=str(exc),
                )
            raise

        upper_eye, middle_eye, lower_eye = eye_results
        total_time_ms = int(time.monotonic() * 1000) - start_ms

        pam4_result = PAM4SweepResult(
            lane=lane,
            upper_eye=upper_eye,
            middle_eye=middle_eye,
            lower_eye=lower_eye,
            worst_eye_width_ui=min(
                upper_eye.eye_width_ui,
                middle_eye.eye_width_ui,
                lower_eye.eye_width_ui,
            ),
            worst_eye_height_mv=min(
                upper_eye.eye_height_mv,
                middle_eye.eye_height_mv,
                lower_eye.eye_height_mv,
            ),
            is_balanced=_check_balance(
                upper_eye.eye_height_mv,
                middle_eye.eye_height_mv,
                lower_eye.eye_height_mv,
            ),
            total_sweep_time_ms=total_time_ms,
        )

        with _lock:
            _pam4_sweep_results[key] = pam4_result
            _pam4_active_sweeps[key] = PAM4SweepProgress(
                status="complete",
                lane=lane,
                current_eye="",
                current_eye_index=2,
                overall_step=overall_total,
                overall_total_steps=overall_total,
                percent=100.0,
            )

        return pam4_result
