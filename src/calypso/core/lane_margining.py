"""Lane Margining sweep engine for eye diagram measurements.

Implements PCIe Base Spec 6.0.1 Section 7.7.8 Lane Margining at the Receiver.
Sweeps voltage and timing margins on a single lane to produce eye diagram data.
Supports NRZ (single eye, Gen1-5) and PAM4 (3-eye, Gen6) modulation.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from calypso.bindings.constants import PlxApiMode
from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT, PLX_MODE_PROP
from calypso.core.pcie_config import PcieConfigReader
from calypso.hardware.pcie_registers import ExtCapabilityID
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

_POLL_INTERVAL_S = 0.1
_POLL_TIMEOUT_S = 5.0


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
    )


def _compute_eye_dimensions(
    timing_points: list[MarginPoint],
    voltage_points: list[MarginPoint],
    num_timing: int,
    num_voltage: int,
) -> tuple[int, int, float, float]:
    """Compute eye width/height in steps and physical units.

    Returns (eye_width_steps, eye_height_steps, eye_width_ui, eye_height_mv).
    """
    max_right = max(
        (p.step for p in timing_points if p.direction == "right" and p.passed),
        default=0,
    )
    max_left = max(
        (p.step for p in timing_points if p.direction == "left" and p.passed),
        default=0,
    )
    max_up = max(
        (p.step for p in voltage_points if p.direction == "up" and p.passed),
        default=0,
    )
    max_down = max(
        (p.step for p in voltage_points if p.direction == "down" and p.passed),
        default=0,
    )

    eye_width_steps = max_left + max_right
    eye_height_steps = max_up + max_down
    eye_width_ui = steps_to_timing_ui(max_left, num_timing) + steps_to_timing_ui(
        max_right, num_timing
    )
    eye_height_mv = steps_to_voltage_mv(max_up, num_voltage) + steps_to_voltage_mv(
        max_down, num_voltage
    )
    return eye_width_steps, eye_height_steps, eye_width_ui, eye_height_mv


class LaneMarginingEngine:
    """Executes lane margining sweeps against a PCIe device port."""

    def __init__(
        self,
        device: PLX_DEVICE_OBJECT,
        device_key: PLX_DEVICE_KEY,
        port_number: int,
    ) -> None:
        self._port_number = port_number
        self._port_device: PLX_DEVICE_OBJECT | None = None  # Tracks separately-opened device

        # Check if the opened device IS the target port via its hardware PortNumber
        props = sdk_device.get_port_properties(device)
        if props.PortNumber == port_number:
            target_device, target_key = device, device_key
        else:
            # Find and open the device for the target port
            target_device, target_key = self._find_and_open_port(device_key, port_number)
            self._port_device = target_device  # Track for cleanup

        self._reader = PcieConfigReader(target_device, target_key)
        self._margining_offset = self._reader.find_extended_capability(
            ExtCapabilityID.RECEIVER_LANE_MARGINING,
        )
        if self._margining_offset is None:
            self.close()
            raise ValueError("Lane Margining capability not found on this device")

    @staticmethod
    def _find_and_open_port(
        reference_key: PLX_DEVICE_KEY, port_number: int
    ) -> tuple[PLX_DEVICE_OBJECT, PLX_DEVICE_KEY]:
        """Find and open the device for a specific switch port by hardware PortNumber."""
        api_mode = PlxApiMode(reference_key.ApiMode)
        mode_prop = PLX_MODE_PROP() if api_mode != PlxApiMode.PCI else None
        all_keys = sdk_device.find_devices(api_mode=api_mode, mode_prop=mode_prop)

        for k in all_keys:
            dev = sdk_device.open_device(k)
            try:
                props = sdk_device.get_port_properties(dev)
                if props.PortNumber == port_number:
                    return dev, k
                sdk_device.close_device(dev)
            except Exception:
                sdk_device.close_device(dev)
                raise

        raise ValueError(f"Port {port_number} not found in device enumeration")

    def close(self) -> None:
        """Close the separately-opened port device, if any."""
        if self._port_device is not None:
            try:
                sdk_device.close_device(self._port_device)
            except Exception:
                logger.warning("failed_to_close_port_device", port=self._port_number)
            self._port_device = None

    def __enter__(self) -> LaneMarginingEngine:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def is_margining_ready(self) -> bool:
        """Check whether the port's Margining Ready bit is set in Port Status."""
        dword = self._reader.read_config_register(
            self._margining_offset + LaneMarginingCap.PORT_CAP,
        )
        # Port Status is upper 16 bits (offset 0x06); bit 0 = Margining Ready
        port_status = (dword >> 16) & 0xFFFF
        return bool(port_status & 0x1)

    def _send_report_command(
        self,
        lane: int,
        receiver: MarginingReceiverNumber,
        report_payload: int,
    ) -> int:
        """Send an ACCESS_RECEIVER_MARGIN_CONTROL report command.

        Returns the 8-bit margin_payload from the Lane Status response register.
        Polls until the response margin_type echoes back as expected, which
        confirms the device has processed the command (not stale data).
        """
        control = MarginingLaneControl(
            receiver_number=receiver,
            margin_type=MarginingCmd.ACCESS_RECEIVER_MARGIN_CONTROL,
            usage_model=0,
            margin_payload=report_payload,
        )
        self._write_lane_control(lane, control)

        deadline = time.monotonic() + _POLL_TIMEOUT_S
        while time.monotonic() < deadline:
            time.sleep(_POLL_INTERVAL_S)
            status = self._read_lane_status(lane)
            if status.margin_type == MarginingCmd.ACCESS_RECEIVER_MARGIN_CONTROL:
                return status.margin_payload

        raise TimeoutError(f"Report command 0x{report_payload:02X} timed out waiting for response")

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
        if not self.is_margining_ready():
            raise ValueError("Port is not ready for margining (Margining Ready bit not set)")

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
        current = self._reader.read_config_register(offset)
        new_value = (current & 0xFFFF0000) | (control.to_register() & 0xFFFF)
        self._reader.write_config_register(offset, new_value)

    def _read_lane_status(self, lane: int) -> MarginingLaneStatus:
        """Read the lane status register (high 16 bits of the lane DWORD)."""
        offset = self._lane_control_offset(lane)
        dword = self._reader.read_config_register(offset)
        status_word = (dword >> 16) & 0xFFFF
        return MarginingLaneStatus.from_register(status_word)

    def _margin_single_point(
        self,
        lane: int,
        cmd: MarginingCmd,
        receiver: MarginingReceiverNumber,
        payload: int,
    ) -> MarginingLaneStatus:
        """Issue a single margining command and poll until complete or timeout."""
        control = MarginingLaneControl(
            receiver_number=receiver,
            margin_type=cmd,
            usage_model=0,
            margin_payload=payload,
        )
        self._write_lane_control(lane, control)

        deadline = time.monotonic() + _POLL_TIMEOUT_S
        while time.monotonic() < deadline:
            time.sleep(_POLL_INTERVAL_S)
            status = self._read_lane_status(lane)
            if not status.is_in_progress:
                return status

        # Timed out - return last status
        return self._read_lane_status(lane)

    def reset_lane(
        self, lane: int, receiver: MarginingReceiverNumber = MarginingReceiverNumber.BROADCAST
    ) -> None:
        """Send GO_TO_NORMAL_SETTINGS to restore normal operation."""
        control = MarginingLaneControl(
            receiver_number=receiver,
            margin_type=MarginingCmd.GO_TO_NORMAL_SETTINGS,
            usage_model=0,
            margin_payload=0,
        )
        self._write_lane_control(lane, control)

    def _execute_single_sweep(
        self,
        lane: int,
        receiver: MarginingReceiverNumber,
        progress_callback: Callable[[int, int], None] | None = None,
        caps: LaneMarginCapabilities | None = None,
    ) -> EyeSweepResult:
        """Core sweep for one receiver. No module-level state writes.

        Sweeps timing (right, left) and voltage (up, down) directions.
        Calls progress_callback(current_step, total_steps) after each point.
        If caps is provided, skips the hardware capabilities query.
        """
        start_ms = int(time.monotonic() * 1000)

        if caps is None:
            caps = self.get_capabilities(lane=lane, receiver=receiver)
        num_timing = caps.num_timing_steps
        num_voltage = caps.num_voltage_steps
        total_steps = (num_timing * 2) + (num_voltage * 2)

        if total_steps == 0:
            raise ValueError("Device reports 0 margining steps (margining not supported)")

        timing_points: list[MarginPoint] = []
        voltage_points: list[MarginPoint] = []
        step_count = 0

        directions: list[tuple[str, MarginingCmd, int, list[MarginPoint]]] = [
            ("right", MarginingCmd.MARGIN_TIMING, num_timing, timing_points),
            ("left", MarginingCmd.MARGIN_TIMING, num_timing, timing_points),
            ("up", MarginingCmd.MARGIN_VOLTAGE, num_voltage, voltage_points),
            ("down", MarginingCmd.MARGIN_VOLTAGE, num_voltage, voltage_points),
        ]

        for direction, cmd, num_steps, point_list in directions:
            for step in range(1, num_steps + 1):
                payload = step & 0x3F
                if direction in ("left", "down"):
                    payload |= 1 << 6

                status = self._margin_single_point(lane, cmd, receiver, payload)
                point_list.append(
                    MarginPoint(
                        direction=direction,
                        step=step,
                        margin_value=status.margin_value,
                        status_code=status.status_code,
                        passed=(status.is_complete and status.margin_value > 0),
                    )
                )
                step_count += 1
                if progress_callback is not None:
                    progress_callback(step_count, total_steps)

        eye_w_steps, eye_h_steps, eye_w_ui, eye_h_mv = _compute_eye_dimensions(
            timing_points,
            voltage_points,
            num_timing,
            num_voltage,
        )

        elapsed_ms = int(time.monotonic() * 1000) - start_ms

        return EyeSweepResult(
            lane=lane,
            receiver=int(receiver),
            timing_points=timing_points,
            voltage_points=voltage_points,
            capabilities=_build_caps_response(caps),
            eye_width_steps=eye_w_steps,
            eye_height_steps=eye_h_steps,
            eye_width_ui=round(eye_w_ui, 4),
            eye_height_mv=round(eye_h_mv, 2),
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

        # Pre-flight: get total steps for progress tracking
        caps = self.get_capabilities(lane=lane, receiver=receiver)
        total_steps = (caps.num_timing_steps * 2) + (caps.num_voltage_steps * 2)

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

        # Pre-flight: query capabilities for each receiver to compute total steps
        per_eye_caps: list[LaneMarginCapabilities] = []
        per_eye_steps: list[int] = []
        for rx in PAM4_RECEIVERS:
            caps = self.get_capabilities(lane=lane, receiver=rx)
            per_eye_caps.append(caps)
            steps = (caps.num_timing_steps * 2) + (caps.num_voltage_steps * 2)
            per_eye_steps.append(steps)

        overall_total = sum(per_eye_steps)
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
            for eye_idx, (rx, label, eye_caps) in enumerate(
                zip(PAM4_RECEIVERS, PAM4_EYE_LABELS, per_eye_caps)
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

                result = self._execute_single_sweep(lane, rx, _progress, caps=eye_caps)
                eye_results.append(result)
                completed_steps += per_eye_steps[eye_idx]

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
