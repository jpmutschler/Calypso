"""PHY layer monitoring and diagnostics.

Provides domain-level access to physical layer features:
- Lane equalization control/status (16 GT/s and 32 GT/s extended capabilities)
- SerDes diagnostics (per-quad error counters)
- User Test Pattern (UTP) loading and result collection
- Lane margining capability detection

Uses PcieConfigReader for standard PCIe config space access and vendor-specific
register definitions from hardware.atlas3_phy for Atlas3 silicon.
"""

from __future__ import annotations

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.core.pcie_config import PcieConfigReader
from calypso.hardware.pcie_registers import ExtCapabilityID
from calypso.hardware.atlas3 import port_register_base
from calypso.hardware.atlas3_phy import (
    PhyCmdStatusRegister,
    PortControlRegister,
    SerDesDiagnosticRegister,
    TestPatternRate,
    UTPTestResult,
    UserTestPattern,
    VendorPhyRegs,
    get_quad_diag_offset,
)
from calypso.models.pcie_config import EqStatus16GT, EqStatus32GT, SupportedSpeedsVector
from calypso.models.phy import (
    LaneEqualizationControl,
    PhysLayer16GT,
    PhysLayer32GT,
)
from calypso.sdk.registers import read_pci_register_fast, write_pci_register_fast
from calypso.utils.logging import get_logger

logger = get_logger(__name__)


class PhyMonitor:
    """Physical layer monitoring and diagnostics for Atlas3 switch ports.

    Combines standard PCIe PHY layer extended capability reads with
    vendor-specific SerDes diagnostic register access.

    Args:
        device: Open PLX device object.
        device_key: Device key for the target port.
        port_number: Physical port number for vendor register base calculation.
    """

    def __init__(
        self,
        device: PLX_DEVICE_OBJECT,
        device_key: PLX_DEVICE_KEY,
        port_number: int,
    ) -> None:
        self._device = device
        self._key = device_key
        self._port_number = port_number
        self._config = PcieConfigReader(device, device_key)
        self._port_reg_base = port_register_base(port_number)

    def _read_vendor_reg(self, offset: int) -> int:
        """Read a vendor-specific register relative to port register base."""
        abs_offset = self._port_reg_base + offset
        return read_pci_register_fast(self._device, abs_offset)

    def _write_vendor_reg(self, offset: int, value: int) -> None:
        """Write a vendor-specific register relative to port register base."""
        abs_offset = self._port_reg_base + offset
        write_pci_register_fast(self._device, abs_offset, value)

    # -----------------------------------------------------------------
    # Standard PCIe capability reads (delegated to PcieConfigReader)
    # -----------------------------------------------------------------

    def get_supported_speeds(self) -> SupportedSpeedsVector:
        """Read the supported link speeds vector from Link Capabilities 2."""
        return self._config.get_supported_speeds()

    def get_eq_status_16gt(self) -> EqStatus16GT | None:
        """Read 16 GT/s equalization status."""
        return self._config.get_eq_status_16gt()

    def get_eq_status_32gt(self) -> EqStatus32GT | None:
        """Read 32 GT/s equalization status and capabilities."""
        return self._config.get_eq_status_32gt()

    def has_lane_margining(self) -> bool:
        """Check if Lane Margining at Receiver capability is present."""
        return self._config.get_lane_margining_offset() is not None

    def get_lane_eq_settings_16gt(self, num_lanes: int = 16) -> list[LaneEqualizationControl]:
        """Read per-lane equalization control from 16 GT/s PHY capability.

        Args:
            num_lanes: Number of lanes to read (default 16, max per station).

        Returns:
            List of LaneEqualizationControl for each lane.
        """
        offset = self._config.find_extended_capability(ExtCapabilityID.PHYSICAL_LAYER_16GT)
        if offset is None:
            return []

        eq_base = offset + PhysLayer16GT.LANE_EQ_CTL_BASE
        settings: list[LaneEqualizationControl] = []

        for lane in range(num_lanes):
            # Two lanes per DWORD: even lane in low 16 bits, odd in high 16
            reg_offset = eq_base + (lane // 2) * 4
            try:
                reg_value = self._config.read_config_register(reg_offset)
            except Exception:
                logger.warning("lane_eq_read_failed", lane=lane, offset=f"0x{reg_offset:X}")
                continue

            if lane % 2 == 0:
                lane_value = reg_value & 0xFFFF
            else:
                lane_value = (reg_value >> 16) & 0xFFFF

            settings.append(LaneEqualizationControl.from_register(lane, lane_value))

        return settings

    # -----------------------------------------------------------------
    # Vendor-specific register reads
    # -----------------------------------------------------------------

    def get_port_control(self) -> PortControlRegister:
        """Read the Port Control Register (0x3208)."""
        raw = self._read_vendor_reg(VendorPhyRegs.PORT_CONTROL)
        return PortControlRegister.from_register(raw)

    def set_port_control(self, port_ctrl: PortControlRegister) -> None:
        """Write the Port Control Register (0x3208) with write-enable set."""
        self._write_vendor_reg(
            VendorPhyRegs.PORT_CONTROL,
            port_ctrl.to_register(write_enable=True),
        )

    def get_phy_cmd_status(self) -> PhyCmdStatusRegister:
        """Read the PHY Command/Status Register (0x321C)."""
        raw = self._read_vendor_reg(VendorPhyRegs.PHY_CMD_STATUS)
        return PhyCmdStatusRegister.from_register(raw)

    def get_serdes_diag(self, lane: int) -> SerDesDiagnosticRegister:
        """Read SerDes diagnostic data for a specific lane.

        Args:
            lane: Lane number (0-15).

        Returns:
            SerDesDiagnosticRegister with error count and sync status.
        """
        reg_offset, lane_in_quad = get_quad_diag_offset(lane)

        # Write lane_select first
        select_value = (lane_in_quad & 0x3) << 24
        self._write_vendor_reg(reg_offset, select_value)

        # Read back diagnostic data
        raw = self._read_vendor_reg(reg_offset)
        return SerDesDiagnosticRegister.from_register(raw)

    def get_all_serdes_diag(self, num_lanes: int = 16) -> list[SerDesDiagnosticRegister]:
        """Read SerDes diagnostic data for all lanes in a station.

        Args:
            num_lanes: Number of lanes to query (default 16).

        Returns:
            List of SerDesDiagnosticRegister, one per lane.
        """
        results: list[SerDesDiagnosticRegister] = []
        for lane in range(num_lanes):
            try:
                diag = self.get_serdes_diag(lane)
                results.append(diag)
            except Exception:
                logger.warning("serdes_diag_read_failed", lane=lane)
                results.append(SerDesDiagnosticRegister(lane_select=lane % 4))
        return results

    def clear_serdes_errors(self, lane: int) -> None:
        """Clear the SerDes error counter for a specific lane.

        Args:
            lane: Lane number (0-15).
        """
        reg_offset, lane_in_quad = get_quad_diag_offset(lane)
        diag = SerDesDiagnosticRegister(lane_select=lane_in_quad)
        self._write_vendor_reg(reg_offset, diag.to_register(clear_error_count=True))

    # -----------------------------------------------------------------
    # User Test Pattern operations
    # -----------------------------------------------------------------

    def load_utp(self, pattern: UserTestPattern) -> None:
        """Load a 16-byte User Test Pattern into the UTP registers.

        Args:
            pattern: UserTestPattern with exactly 16 bytes.
        """
        regs = pattern.to_registers()
        offsets = [
            VendorPhyRegs.UTP_PATTERN_0,
            VendorPhyRegs.UTP_PATTERN_4,
            VendorPhyRegs.UTP_PATTERN_8,
            VendorPhyRegs.UTP_PATTERN_12,
        ]
        for offset, value in zip(offsets, regs):
            self._write_vendor_reg(offset, value)

    def read_utp(self) -> UserTestPattern:
        """Read the current UTP registers back."""
        offsets = [
            VendorPhyRegs.UTP_PATTERN_0,
            VendorPhyRegs.UTP_PATTERN_4,
            VendorPhyRegs.UTP_PATTERN_8,
            VendorPhyRegs.UTP_PATTERN_12,
        ]
        regs = [self._read_vendor_reg(off) for off in offsets]
        return UserTestPattern.from_registers(*regs)

    def collect_utp_results(self, num_lanes: int = 16) -> list[UTPTestResult]:
        """Collect UTP test results from all lanes via SerDes diagnostic registers.

        Args:
            num_lanes: Number of lanes to check (default 16).

        Returns:
            List of UTPTestResult for each lane.
        """
        results: list[UTPTestResult] = []
        for lane in range(num_lanes):
            try:
                diag = self.get_serdes_diag(lane)
                results.append(UTPTestResult(
                    lane=lane,
                    synced=diag.utp_sync,
                    error_count=diag.utp_error_count,
                    expected_on_error=diag.utp_expected_data if diag.utp_error_count > 0 else None,
                    actual_on_error=diag.utp_actual_data if diag.utp_error_count > 0 else None,
                ))
            except Exception:
                logger.warning("utp_result_read_failed", lane=lane)
                results.append(UTPTestResult(
                    lane=lane, synced=False, error_count=0,
                    expected_on_error=None, actual_on_error=None,
                ))
        return results

    def prepare_utp_test(
        self,
        pattern: UserTestPattern,
        rate: TestPatternRate = TestPatternRate.RATE_8_0GT,
        port_select: int = 0,
    ) -> None:
        """Prepare a port for UTP testing.

        Steps:
        1. Set Port Control to disable port and hold quiet
        2. Set the test pattern rate
        3. Load the UTP pattern
        4. Clear disable (keeping quiet cleared by caller when ready)

        Args:
            pattern: The 16-byte test pattern to load.
            rate: Test pattern generation speed.
            port_select: Port within the station (0-15).
        """
        # Step 1+2: Disable port and set rate
        ctrl = PortControlRegister(
            disable_port=True,
            port_quiet=True,
            test_pattern_rate=rate,
            port_select=port_select,
        )
        self.set_port_control(ctrl)

        # Step 3: Load pattern
        self.load_utp(pattern)

        # Step 4: Clear disable, keep quiet until caller is ready
        ctrl_ready = PortControlRegister(
            disable_port=False,
            port_quiet=True,
            test_pattern_rate=rate,
            port_select=port_select,
        )
        self.set_port_control(ctrl_ready)
