"""Lane Margining sweep engine for eye diagram measurements.

Implements PCIe Base Spec 6.0.1 Section 7.7.8 Lane Margining at the Receiver.
Sweeps voltage and timing margins on a single lane to produce eye diagram data.
"""

from __future__ import annotations

import threading
import time

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.core.pcie_config import PcieConfigReader
from calypso.hardware.pcie_registers import ExtCapabilityID
from calypso.models.phy import (
    LaneMarginCapabilities,
    LaneMarginingCap,
    MarginingCmd,
    MarginingLaneControl,
    MarginingLaneStatus,
    MarginingReceiverNumber,
    MarginingReportPayload,
    steps_to_timing_ui,
    steps_to_voltage_mv,
)
from calypso.models.phy_api import (
    EyeSweepResult,
    LaneMarginCapabilitiesResponse,
    MarginPoint,
    SweepProgress,
)
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

# Module-level sweep tracking, keyed by "{device_id}:{lane}"
_lock = threading.Lock()
_active_sweeps: dict[str, SweepProgress] = {}
_sweep_results: dict[str, EyeSweepResult] = {}

_POLL_INTERVAL_S = 0.1
_POLL_TIMEOUT_S = 5.0


def get_sweep_progress(device_id: str, lane: int) -> SweepProgress:
    """Get the current sweep progress for a device+lane."""
    key = f"{device_id}:{lane}"
    with _lock:
        return _active_sweeps.get(key, SweepProgress(
            status="idle", lane=lane, current_step=0, total_steps=0, percent=0.0,
        ))


def get_sweep_result(device_id: str, lane: int) -> EyeSweepResult | None:
    """Get the completed sweep result for a device+lane."""
    with _lock:
        return _sweep_results.get(f"{device_id}:{lane}")


class LaneMarginingEngine:
    """Executes lane margining sweeps against a PCIe device port."""

    def __init__(
        self,
        device: PLX_DEVICE_OBJECT,
        device_key: PLX_DEVICE_KEY,
        port_number: int,
    ) -> None:
        self._reader = PcieConfigReader(device, device_key)
        self._port_number = port_number
        self._margining_offset = self._reader.find_extended_capability(
            ExtCapabilityID.RECEIVER_LANE_MARGINING,
        )
        if self._margining_offset is None:
            raise ValueError("Lane Margining capability not found on this device")

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

        raise TimeoutError(
            f"Report command 0x{report_payload:02X} timed out waiting for response"
        )

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

    def reset_lane(self, lane: int, receiver: MarginingReceiverNumber = MarginingReceiverNumber.BROADCAST) -> None:
        """Send GO_TO_NORMAL_SETTINGS to restore normal operation."""
        control = MarginingLaneControl(
            receiver_number=receiver,
            margin_type=MarginingCmd.GO_TO_NORMAL_SETTINGS,
            usage_model=0,
            margin_payload=0,
        )
        self._write_lane_control(lane, control)

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
        start_ms = int(time.monotonic() * 1000)

        caps = self.get_capabilities(lane=lane, receiver=receiver)
        num_timing = caps.num_timing_steps
        num_voltage = caps.num_voltage_steps

        # Total points: timing (left + right) + voltage (up + down)
        total_steps = (num_timing * 2) + (num_voltage * 2)

        if total_steps == 0:
            error_msg = "Device reports 0 margining steps (margining not supported)"
            with _lock:
                _active_sweeps[key] = SweepProgress(
                    status="error", lane=lane, current_step=0,
                    total_steps=0, percent=0.0, error=error_msg,
                )
            raise ValueError(error_msg)

        with _lock:
            _active_sweeps[key] = SweepProgress(
                status="running", lane=lane, current_step=0,
                total_steps=total_steps, percent=0.0,
            )

        timing_points: list[MarginPoint] = []
        voltage_points: list[MarginPoint] = []
        step_count = 0

        try:
            # Sweep timing - right direction (payload bit 6 = 0)
            for step in range(1, num_timing + 1):
                payload = step & 0x3F
                status = self._margin_single_point(lane, MarginingCmd.MARGIN_TIMING, receiver, payload)
                timing_points.append(MarginPoint(
                    direction="right",
                    step=step,
                    margin_value=status.margin_value,
                    status_code=status.status_code,
                    passed=(status.is_complete and status.margin_value > 0),
                ))
                step_count += 1
                with _lock:
                    _active_sweeps[key] = SweepProgress(
                        status="running", lane=lane, current_step=step_count,
                        total_steps=total_steps, percent=(step_count / total_steps) * 100,
                    )

            # Sweep timing - left direction (payload bit 6 = 1)
            for step in range(1, num_timing + 1):
                payload = (step & 0x3F) | (1 << 6)
                status = self._margin_single_point(lane, MarginingCmd.MARGIN_TIMING, receiver, payload)
                timing_points.append(MarginPoint(
                    direction="left",
                    step=step,
                    margin_value=status.margin_value,
                    status_code=status.status_code,
                    passed=(status.is_complete and status.margin_value > 0),
                ))
                step_count += 1
                with _lock:
                    _active_sweeps[key] = SweepProgress(
                        status="running", lane=lane, current_step=step_count,
                        total_steps=total_steps, percent=(step_count / total_steps) * 100,
                    )

            # Sweep voltage - up direction (payload bit 6 = 0)
            for step in range(1, num_voltage + 1):
                payload = step & 0x3F
                status = self._margin_single_point(lane, MarginingCmd.MARGIN_VOLTAGE, receiver, payload)
                voltage_points.append(MarginPoint(
                    direction="up",
                    step=step,
                    margin_value=status.margin_value,
                    status_code=status.status_code,
                    passed=(status.is_complete and status.margin_value > 0),
                ))
                step_count += 1
                with _lock:
                    _active_sweeps[key] = SweepProgress(
                        status="running", lane=lane, current_step=step_count,
                        total_steps=total_steps, percent=(step_count / total_steps) * 100,
                    )

            # Sweep voltage - down direction (payload bit 6 = 1)
            for step in range(1, num_voltage + 1):
                payload = (step & 0x3F) | (1 << 6)
                status = self._margin_single_point(lane, MarginingCmd.MARGIN_VOLTAGE, receiver, payload)
                voltage_points.append(MarginPoint(
                    direction="down",
                    step=step,
                    margin_value=status.margin_value,
                    status_code=status.status_code,
                    passed=(status.is_complete and status.margin_value > 0),
                ))
                step_count += 1
                with _lock:
                    _active_sweeps[key] = SweepProgress(
                        status="running", lane=lane, current_step=step_count,
                        total_steps=total_steps, percent=(step_count / total_steps) * 100,
                    )

            # Restore normal operation
            self.reset_lane(lane, receiver)

        except Exception as exc:
            logger.error("sweep_failed", lane=lane, error=str(exc))
            self.reset_lane(lane, receiver)
            with _lock:
                _active_sweeps[key] = SweepProgress(
                    status="error", lane=lane, current_step=step_count,
                    total_steps=total_steps, percent=(step_count / total_steps) * 100,
                    error=str(exc),
                )
            raise

        # Calculate eye dimensions
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
        eye_width_ui = (
            steps_to_timing_ui(max_left, num_timing)
            + steps_to_timing_ui(max_right, num_timing)
        )
        eye_height_mv = (
            steps_to_voltage_mv(max_up, num_voltage)
            + steps_to_voltage_mv(max_down, num_voltage)
        )

        elapsed_ms = int(time.monotonic() * 1000) - start_ms

        caps_response = LaneMarginCapabilitiesResponse(
            max_timing_offset=caps.max_timing_offset,
            max_voltage_offset=caps.max_voltage_offset,
            num_timing_steps=caps.num_timing_steps,
            num_voltage_steps=caps.num_voltage_steps,
            ind_up_down_voltage=caps.ind_up_down_voltage,
            ind_left_right_timing=caps.ind_left_right_timing,
        )

        result = EyeSweepResult(
            lane=lane,
            receiver=int(receiver),
            timing_points=timing_points,
            voltage_points=voltage_points,
            capabilities=caps_response,
            eye_width_steps=eye_width_steps,
            eye_height_steps=eye_height_steps,
            eye_width_ui=round(eye_width_ui, 4),
            eye_height_mv=round(eye_height_mv, 2),
            sweep_time_ms=elapsed_ms,
        )

        with _lock:
            _sweep_results[key] = result
            _active_sweeps[key] = SweepProgress(
                status="complete", lane=lane, current_step=total_steps,
                total_steps=total_steps, percent=100.0,
            )

        return result
