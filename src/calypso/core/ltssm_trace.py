"""LTSSM state polling, retrain observation, and Ptrace capture.

Provides domain-level access to:
- Live LTSSM state readback via Recovery Diagnostic register (0x3BC4)
- Recovery count and link-down diagnostics
- Retrain-and-watch: forces link retrain and records state transitions
- Ptrace ingress capture with configurable LTSSM triggers
"""

from __future__ import annotations

import threading
import time

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.hardware.atlas3 import port_register_base
from calypso.hardware.atlas3_phy import (
    PhyAdditionalStatusRegister,
    PortControlRegister,
    PtraceCaptureConfigRegister,
    PtraceCaptureControlRegister,
    PtraceCaptureStatusRegister,
    PtraceTriggerCondRegister,
    RecoveryDiagnosticRegister,
    VendorPhyRegs,
)
from calypso.models.ltssm import (
    LtssmState,
    LtssmTransition,
    PtraceCaptureEntry,
    PtraceCaptureResult,
    PtraceConfig,
    PtraceStatusResponse,
    PortLtssmSnapshot,
    RetrainWatchProgress,
    RetrainWatchResult,
    link_speed_name,
    ltssm_state_name,
)
from calypso.sdk.registers import read_mapped_register, write_mapped_register
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

# Module-level retrain tracking, keyed by "{device_id}:{port_number}"
_lock = threading.Lock()
_active_retrains: dict[str, RetrainWatchProgress] = {}
_retrain_results: dict[str, RetrainWatchResult] = {}

_RETRAIN_POLL_INTERVAL_S = 0.020  # 20ms

# Atlas3 has 16 ports per station; PHY registers are per-station with a
# port_select field that selects which port within the station to access.
_PORTS_PER_STATION = 16


def _station_base_port(port_number: int) -> int:
    """Return the first port number of the station owning *port_number*."""
    return (port_number // _PORTS_PER_STATION) * _PORTS_PER_STATION


def _port_select_for(port_number: int) -> int:
    """Return the intra-station port_select index for *port_number*."""
    return port_number % _PORTS_PER_STATION


def get_retrain_progress(device_id: str, port_number: int) -> RetrainWatchProgress:
    """Get the current retrain-watch progress."""
    key = f"{device_id}:{port_number}"
    with _lock:
        return _active_retrains.get(key, RetrainWatchProgress(
            status="idle", port_number=port_number,
            port_select=_port_select_for(port_number),
        ))


def get_retrain_result(device_id: str, port_number: int) -> RetrainWatchResult | None:
    """Get the completed retrain-watch result."""
    key = f"{device_id}:{port_number}"
    with _lock:
        return _retrain_results.get(key)


class LtssmTracer:
    """LTSSM state polling, retrain observation, and Ptrace capture for Atlas3 ports.

    Atlas3 vendor PHY registers (Recovery Diagnostic, PHY Additional Status,
    Port Control, etc.) are **station-level** registers that live at the
    station's base-port register offset.  An embedded ``port_select`` field
    (4 bits) selects which of the 16 ports within that station to access.

    This class accepts a global port number (0-143) and automatically computes
    the station base address and intra-station port_select so callers never
    need to worry about the two-level addressing scheme.
    """

    def __init__(
        self,
        device: PLX_DEVICE_OBJECT,
        device_key: PLX_DEVICE_KEY,
        port_number: int,
    ) -> None:
        if not 0 <= port_number <= 143:
            raise ValueError(f"Port number {port_number} out of range (0-143)")
        self._device = device
        self._key = device_key
        self._port_number = port_number
        # Station-level PHY registers live at the station's base port offset
        self._station_base = _station_base_port(port_number)
        self._port_select = _port_select_for(port_number)
        self._port_reg_base = port_register_base(self._station_base)
        logger.debug(
            "ltssm_tracer_init",
            port_number=port_number,
            station_base=self._station_base,
            port_select=self._port_select,
            reg_base=f"0x{self._port_reg_base:X}",
        )

    def _read_vendor_reg(self, offset: int) -> int:
        """Read a vendor-specific register relative to port register base."""
        abs_offset = self._port_reg_base + offset
        return read_mapped_register(self._device, abs_offset)

    def _write_vendor_reg(self, offset: int, value: int) -> None:
        """Write a vendor-specific register relative to port register base."""
        abs_offset = self._port_reg_base + offset
        write_mapped_register(self._device, abs_offset, value)

    # -----------------------------------------------------------------
    # Phase 1: LTSSM State Polling
    # -----------------------------------------------------------------

    def read_ltssm_state(self) -> int:
        """Read the current LTSSM state code for this port.

        Returns:
            LTSSM state code (see LtssmState enum).
        """
        reg = RecoveryDiagnosticRegister(
            port_select=self._port_select,
            ltssm_status_select=True,
        )
        write_val = reg.to_register()
        self._write_vendor_reg(VendorPhyRegs.RECOVERY_DIAGNOSTIC, write_val)
        raw = self._read_vendor_reg(VendorPhyRegs.RECOVERY_DIAGNOSTIC)
        result = RecoveryDiagnosticRegister.from_register(raw)
        # Log at debug only on first call per tracer instance (avoid noise
        # during 20ms retrain polling).  Subsequent reads log at trace level
        # which is normally suppressed.
        if not getattr(self, "_ltssm_read_logged", False):
            logger.debug(
                "read_ltssm_state",
                port=self._port_number,
                station_base=self._station_base,
                port_select=self._port_select,
                write_val=f"0x{write_val:08X}",
                raw_read=f"0x{raw:08X}",
                ltssm_code=f"0x{result.data_value & 0xFF:02X}",
            )
            self._ltssm_read_logged = True
        return result.data_value & 0xFF  # LTSSM state in low byte

    def read_recovery_count(self) -> tuple[int, int]:
        """Read recovery entry count and Rx evaluation count.

        Returns:
            Tuple of (recovery_count, rx_evaluation_count).
        """
        reg = RecoveryDiagnosticRegister(
            port_select=self._port_select,
            ltssm_status_select=False,
        )
        self._write_vendor_reg(VendorPhyRegs.RECOVERY_DIAGNOSTIC, reg.to_register())
        raw = self._read_vendor_reg(VendorPhyRegs.RECOVERY_DIAGNOSTIC)
        result = RecoveryDiagnosticRegister.from_register(raw)
        return (result.data_value, result.rx_evaluation_count)

    def read_phy_additional_status(self) -> PhyAdditionalStatusRegister:
        """Read PHY additional status (link speed, link down count, lane reversal).

        Returns:
            PhyAdditionalStatusRegister with decoded fields.
        """
        write_reg = PhyAdditionalStatusRegister(port_select=self._port_select)
        self._write_vendor_reg(VendorPhyRegs.PHY_ADDITIONAL_STATUS, write_reg.to_register())
        raw = self._read_vendor_reg(VendorPhyRegs.PHY_ADDITIONAL_STATUS)
        return PhyAdditionalStatusRegister.from_register(raw)

    def get_snapshot(self) -> PortLtssmSnapshot:
        """Read a complete LTSSM state snapshot for this port.

        Combines LTSSM state, recovery count, and PHY additional status.
        """
        ltssm_code = self.read_ltssm_state()
        recovery_count, rx_eval = self.read_recovery_count()
        phy_status = self.read_phy_additional_status()

        return PortLtssmSnapshot(
            port_number=self._port_number,
            port_select=self._port_select,
            ltssm_state=ltssm_code,
            ltssm_state_name=ltssm_state_name(ltssm_code),
            link_speed=phy_status.link_speed,
            link_speed_name=link_speed_name(phy_status.link_speed),
            recovery_count=recovery_count,
            link_down_count=phy_status.link_down_count,
            lane_reversal=phy_status.lane_reversal,
            rx_eval_count=rx_eval,
        )

    def clear_recovery_count(self) -> None:
        """Clear the recovery entry counter for this port."""
        reg = RecoveryDiagnosticRegister(
            port_select=self._port_select,
            ltssm_status_select=False,
        )
        self._write_vendor_reg(
            VendorPhyRegs.RECOVERY_DIAGNOSTIC,
            reg.to_register(clear_recovery_count=True),
        )

    def retrain_and_watch(
        self,
        device_id: str,
        timeout_s: float = 10.0,
    ) -> RetrainWatchResult:
        """Force a link retrain and record LTSSM state transitions.

        Disables the port briefly to trigger a retrain, then polls LTSSM state
        every 20ms, recording each transition with a timestamp.

        Args:
            device_id: Device identifier for progress tracking.
            timeout_s: Maximum time to watch for transitions.

        Returns:
            RetrainWatchResult with ordered transition log.
        """
        key = f"{device_id}:{self._port_number}"

        # Atomic check-and-set: reject if already running, else claim the slot
        with _lock:
            existing = _active_retrains.get(key)
            if existing and existing.status == "running":
                raise RuntimeError("Retrain already running on this port")
            _retrain_results.pop(key, None)  # clear stale result
            _active_retrains[key] = RetrainWatchProgress(
                status="running",
                port_number=self._port_number,
                port_select=self._port_select,
            )

        transitions: list[LtssmTransition] = []
        start_time = time.monotonic()

        try:
            # Read initial LTSSM state before retrain
            initial_state = self.read_ltssm_state()
            transitions.append(LtssmTransition(
                timestamp_ms=0.0,
                state=initial_state,
                state_name=ltssm_state_name(initial_state),
            ))

            # Disable port to force retrain
            ctrl = PortControlRegister(
                disable_port=True,
                port_select=self._port_select,
            )
            self._write_vendor_reg(
                VendorPhyRegs.PORT_CONTROL,
                ctrl.to_register(write_enable=True),
            )

            # Brief pause then re-enable
            time.sleep(0.050)  # 50ms disable pulse

            ctrl_enable = PortControlRegister(
                disable_port=False,
                port_select=self._port_select,
            )
            self._write_vendor_reg(
                VendorPhyRegs.PORT_CONTROL,
                ctrl_enable.to_register(write_enable=True),
            )

            # Poll LTSSM state transitions
            last_state = initial_state
            settled = False
            deadline = start_time + timeout_s

            while time.monotonic() < deadline:
                time.sleep(_RETRAIN_POLL_INTERVAL_S)

                current_state = self.read_ltssm_state()
                elapsed_ms = (time.monotonic() - start_time) * 1000

                if current_state != last_state:
                    transitions.append(LtssmTransition(
                        timestamp_ms=round(elapsed_ms, 2),
                        state=current_state,
                        state_name=ltssm_state_name(current_state),
                    ))
                    last_state = current_state

                    with _lock:
                        _active_retrains[key] = RetrainWatchProgress(
                            status="running",
                            port_number=self._port_number,
                            port_select=self._port_select,
                            elapsed_ms=round(elapsed_ms, 2),
                            transition_count=len(transitions),
                        )

                # Check if link reached L0
                if current_state == LtssmState.L0:
                    # Wait a bit to confirm it stays in L0
                    time.sleep(0.100)
                    confirm = self.read_ltssm_state()
                    if confirm == LtssmState.L0:
                        settled = True
                        break

            duration_ms = (time.monotonic() - start_time) * 1000

            # Read final state and speed
            final_state = self.read_ltssm_state()
            phy_status = self.read_phy_additional_status()

            result = RetrainWatchResult(
                port_number=self._port_number,
                port_select=self._port_select,
                transitions=transitions,
                final_state=final_state,
                final_state_name=ltssm_state_name(final_state),
                final_speed=phy_status.link_speed,
                final_speed_name=link_speed_name(phy_status.link_speed),
                duration_ms=round(duration_ms, 2),
                settled=settled,
            )

            with _lock:
                _retrain_results[key] = result
                _active_retrains[key] = RetrainWatchProgress(
                    status="complete",
                    port_number=self._port_number,
                    port_select=self._port_select,
                    elapsed_ms=round(duration_ms, 2),
                    transition_count=len(transitions),
                )

            return result

        except Exception as exc:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error("retrain_watch_failed", port=self._port_number, error=str(exc))
            with _lock:
                _active_retrains[key] = RetrainWatchProgress(
                    status="error",
                    port_number=self._port_number,
                    port_select=self._port_select,
                    elapsed_ms=round(duration_ms, 2),
                    transition_count=len(transitions),
                    error=str(exc),
                )
            raise

    # -----------------------------------------------------------------
    # Phase 2: Ptrace Capture
    # -----------------------------------------------------------------

    def configure_ptrace(self, config: PtraceConfig) -> None:
        """Configure Ptrace capture parameters.

        Args:
            config: Ptrace configuration with trace point, lane, and trigger settings.
                    port_select is auto-computed from the port number passed to __init__.
        """
        # Write capture config (use auto-computed port_select)
        cap_cfg = PtraceCaptureConfigRegister(
            cap_port_select=self._port_select,
            trace_point_select=config.trace_point,
            lane_select=config.lane_select,
        )
        self._write_vendor_reg(VendorPhyRegs.PTRACE_CAPTURE_CONFIG, cap_cfg.to_register())

        # Write trigger condition
        trigger = PtraceTriggerCondRegister(
            ltssm_enable=config.trigger_on_ltssm,
            ltssm_state_match=config.ltssm_trigger_state or 0,
        )
        self._write_vendor_reg(VendorPhyRegs.PTRACE_TRIGGER_COND_0, trigger.to_register())

    def start_ptrace(self) -> None:
        """Start Ptrace capture."""
        ctrl = PtraceCaptureControlRegister(start_capture=True)
        self._write_vendor_reg(VendorPhyRegs.PTRACE_CAPTURE_CONTROL, ctrl.to_register())

    def stop_ptrace(self) -> None:
        """Stop Ptrace capture."""
        ctrl = PtraceCaptureControlRegister(stop_capture=True)
        self._write_vendor_reg(VendorPhyRegs.PTRACE_CAPTURE_CONTROL, ctrl.to_register())

    def clear_ptrace(self) -> None:
        """Clear the Ptrace capture buffer."""
        ctrl = PtraceCaptureControlRegister(clear_buffer=True)
        self._write_vendor_reg(VendorPhyRegs.PTRACE_CAPTURE_CONTROL, ctrl.to_register())

    def read_ptrace_status(self) -> PtraceStatusResponse:
        """Read current Ptrace capture status."""
        raw = self._read_vendor_reg(VendorPhyRegs.PTRACE_CAPTURE_STATUS)
        status = PtraceCaptureStatusRegister.from_register(raw)
        return PtraceStatusResponse(
            capture_active=status.capture_active,
            trigger_hit=status.trigger_hit,
            entries_captured=status.entries_captured,
        )

    def read_ptrace_buffer(self, max_entries: int = 256) -> PtraceCaptureResult:
        """Read captured data from the Ptrace buffer.

        Args:
            max_entries: Maximum number of entries to read.

        Returns:
            PtraceCaptureResult with captured entries.
        """
        status = self.read_ptrace_status()
        count = min(status.entries_captured, max_entries)

        entries: list[PtraceCaptureEntry] = []
        for i in range(count):
            # Write RAM address to select entry, then read data register
            self._write_vendor_reg(VendorPhyRegs.PTRACE_RAM_ADDRESS, i)
            raw = self._read_vendor_reg(VendorPhyRegs.PTRACE_RAM_DATA)
            entries.append(PtraceCaptureEntry(
                index=i,
                raw_data=f"0x{raw:08X}",
            ))

        return PtraceCaptureResult(
            port_number=self._port_number,
            entries=entries,
            trigger_hit=status.trigger_hit,
            total_captured=status.entries_captured,
        )
