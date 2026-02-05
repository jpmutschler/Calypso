"""PCIe configuration space reader with capability walking, AER, and link control."""

from __future__ import annotations

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.models.pcie_config import (
    AerCorrectableErrors,
    AerStatus,
    AerUncorrectableErrors,
    ConfigRegister,
    ConfigSpaceDump,
    DeviceCapabilities,
    DeviceControlStatus,
    EqStatus16GT,
    EqStatus32GT,
    LinkCapabilities,
    LinkControlStatus,
    PcieCapabilityInfo,
    SupportedSpeedsVector,
)
from calypso.sdk.registers import read_pci_register_fast, write_pci_register_fast
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

# Standard capability IDs
_CAP_ID_PCIE = 0x10

# Extended capability IDs
_EXT_CAP_AER = 0x0001
_EXT_CAP_PHY_16GT = 0x0026
_EXT_CAP_LANE_MARGIN = 0x0027
_EXT_CAP_PHY_32GT = 0x002A

# Standard capability name table
_STD_CAP_NAMES: dict[int, str] = {
    0x01: "PCI Power Management",
    0x02: "AGP",
    0x03: "VPD",
    0x04: "Slot Identification",
    0x05: "MSI",
    0x06: "CompactPCI Hot Swap",
    0x07: "PCI-X",
    0x08: "HyperTransport",
    0x09: "Vendor Specific",
    0x0A: "Debug Port",
    0x0B: "CompactPCI CRC",
    0x0C: "PCI Hot Plug",
    0x0D: "PCI Bridge Subsystem VID",
    0x0E: "AGP 8x",
    0x0F: "Secure Device",
    0x10: "PCI Express",
    0x11: "MSI-X",
    0x12: "SATA Config",
    0x13: "AF",
    0x14: "Enhanced Allocation",
    0x15: "Flattening Portal Bridge",
}

# Extended capability name table
_EXT_CAP_NAMES: dict[int, str] = {
    0x0001: "AER",
    0x0002: "VC",
    0x0003: "Serial Number",
    0x0004: "Power Budgeting",
    0x0005: "Root Complex Link Declaration",
    0x0006: "Root Complex Internal Link",
    0x0007: "Root Complex Event Collector",
    0x0008: "MFVC",
    0x0009: "VC (MFVC)",
    0x000A: "RCRB Header",
    0x000B: "Vendor Specific",
    0x000C: "Config Access Correlation",
    0x000D: "ACS",
    0x000E: "ARI",
    0x000F: "ATS",
    0x0010: "SR-IOV",
    0x0011: "MR-IOV",
    0x0012: "Multicast",
    0x0013: "Page Request",
    0x0015: "Resizable BAR",
    0x0016: "Dynamic Power Allocation",
    0x0017: "TPH",
    0x0018: "LTR",
    0x0019: "Secondary PCIe",
    0x001A: "PMUX",
    0x001B: "PASID",
    0x001C: "LN Requester",
    0x001D: "DPC",
    0x001E: "L1 PM Substates",
    0x001F: "Precision Time Measurement",
    0x0020: "M-PCIe",
    0x0021: "FRS Queueing",
    0x0022: "Readiness Time Reporting",
    0x0023: "Designated Vendor Specific",
    0x0024: "VF Resizable BAR",
    0x0025: "Data Link Feature",
    0x0026: "Physical Layer 16.0 GT/s",
    0x0027: "Lane Margining at Receiver",
    0x0028: "Hierarchy ID",
    0x0029: "NPEM",
    0x002A: "Physical Layer 32.0 GT/s",
    0x002B: "Alternate Protocol",
    0x002C: "SFI",
}

# Link speed code to human-readable string
_SPEED_MAP: dict[int, str] = {
    1: "Gen1",
    2: "Gen2",
    3: "Gen3",
    4: "Gen4",
    5: "Gen5",
    6: "Gen6",
}

# ASPM decode
_ASPM_MAP: dict[int, str] = {
    0: "none",
    1: "L0s",
    2: "L1",
    3: "L0s+L1",
}

# MPS/MRRS encoding: value = 128 << code
_PAYLOAD_SIZES = [128, 256, 512, 1024, 2048, 4096]


def _decode_payload(code: int) -> int:
    """Decode 3-bit MPS/MRRS field to byte count."""
    if 0 <= code < len(_PAYLOAD_SIZES):
        return _PAYLOAD_SIZES[code]
    return 128


def _encode_payload(size: int) -> int:
    """Encode byte count to 3-bit MPS/MRRS field."""
    try:
        return _PAYLOAD_SIZES.index(size)
    except ValueError:
        raise ValueError(f"Invalid payload size {size}, must be one of {_PAYLOAD_SIZES}")


class PcieConfigReader:
    """Reads and parses PCIe configuration space registers."""

    def __init__(self, device: PLX_DEVICE_OBJECT, device_key: PLX_DEVICE_KEY) -> None:
        self._device = device
        self._key = device_key

    def read_config_register(self, offset: int) -> int:
        """Read a single 32-bit config register."""
        return read_pci_register_fast(self._device, offset)

    def write_config_register(self, offset: int, value: int) -> None:
        """Write a single 32-bit config register."""
        write_pci_register_fast(self._device, offset, value)

    def dump_config_space(self, offset: int = 0, count: int = 64) -> list[ConfigRegister]:
        """Read a range of config space registers.

        Args:
            offset: Starting DWORD-aligned offset.
            count: Number of DWORDs to read.

        Returns:
            List of ConfigRegister entries.
        """
        registers: list[ConfigRegister] = []
        for i in range(count):
            reg_offset = offset + (i * 4)
            try:
                value = self.read_config_register(reg_offset)
                registers.append(ConfigRegister(offset=reg_offset, value=value))
            except Exception:
                logger.warning("config_read_failed", offset=f"0x{reg_offset:X}")
                registers.append(ConfigRegister(offset=reg_offset, value=0xFFFFFFFF))
        return registers

    def walk_capabilities(self) -> list[PcieCapabilityInfo]:
        """Walk the PCI capability linked list starting at offset 0x34.

        Returns:
            List of discovered standard capabilities.
        """
        caps: list[PcieCapabilityInfo] = []
        pointer_reg = self.read_config_register(0x34)
        pointer = pointer_reg & 0xFF

        visited: set[int] = set()
        while pointer and pointer != 0xFF:
            if pointer in visited:
                break
            visited.add(pointer)

            cap_reg = self.read_config_register(pointer)
            cap_id = cap_reg & 0xFF
            next_ptr = (cap_reg >> 8) & 0xFF

            cap_name = _STD_CAP_NAMES.get(cap_id, f"Unknown(0x{cap_id:02X})")
            caps.append(PcieCapabilityInfo(
                cap_id=cap_id,
                cap_name=cap_name,
                offset=pointer,
            ))

            pointer = next_ptr

        return caps

    def walk_extended_capabilities(self) -> list[PcieCapabilityInfo]:
        """Walk extended capabilities starting at offset 0x100.

        Returns:
            List of discovered extended capabilities.
        """
        caps: list[PcieCapabilityInfo] = []
        offset = 0x100

        visited: set[int] = set()
        while offset and offset >= 0x100:
            if offset in visited:
                break
            visited.add(offset)

            try:
                header = self.read_config_register(offset)
            except Exception:
                break

            if header == 0 or header == 0xFFFFFFFF:
                break

            cap_id = header & 0xFFFF
            version = (header >> 16) & 0xF
            next_offset = (header >> 20) & 0xFFC

            cap_name = _EXT_CAP_NAMES.get(cap_id, f"ExtUnknown(0x{cap_id:04X})")
            caps.append(PcieCapabilityInfo(
                cap_id=cap_id,
                cap_name=cap_name,
                offset=offset,
                version=version,
            ))

            offset = next_offset

        return caps

    def find_capability(self, cap_id: int) -> int | None:
        """Find a standard capability by ID.

        Returns:
            Offset of the capability header, or None if not found.
        """
        for cap in self.walk_capabilities():
            if cap.cap_id == cap_id:
                return cap.offset
        return None

    def find_extended_capability(self, ext_cap_id: int) -> int | None:
        """Find an extended capability by ID.

        Returns:
            Offset of the extended capability header, or None if not found.
        """
        for cap in self.walk_extended_capabilities():
            if cap.cap_id == ext_cap_id:
                return cap.offset
        return None

    def _require_pcie_cap(self) -> int:
        """Find the PCIe capability offset, raising if not found."""
        offset = self.find_capability(_CAP_ID_PCIE)
        if offset is None:
            raise ValueError("PCIe capability not found in config space")
        return offset

    def get_device_capabilities(self) -> DeviceCapabilities:
        """Read Device Capabilities register (PCIe Cap + 0x04)."""
        pcie_cap = self._require_pcie_cap()
        dev_cap = self.read_config_register(pcie_cap + 0x04)

        mps_supported_code = dev_cap & 0x7
        return DeviceCapabilities(
            max_payload_supported=_decode_payload(mps_supported_code),
            flr_capable=bool(dev_cap & (1 << 28)),
            extended_tag_supported=bool(dev_cap & (1 << 5)),
            role_based_error_reporting=bool(dev_cap & (1 << 15)),
        )

    def get_device_control(self) -> DeviceControlStatus:
        """Read Device Control + Status registers (PCIe Cap + 0x08)."""
        pcie_cap = self._require_pcie_cap()
        dev_ctrl = self.read_config_register(pcie_cap + 0x08)

        ctrl_word = dev_ctrl & 0xFFFF
        return DeviceControlStatus(
            max_payload_size=_decode_payload((ctrl_word >> 5) & 0x7),
            max_read_request_size=_decode_payload((ctrl_word >> 12) & 0x7),
            relaxed_ordering=bool(ctrl_word & (1 << 4)),
            no_snoop=bool(ctrl_word & (1 << 11)),
            extended_tag_enabled=bool(ctrl_word & (1 << 8)),
            correctable_error_reporting=bool(ctrl_word & (1 << 0)),
            non_fatal_error_reporting=bool(ctrl_word & (1 << 1)),
            fatal_error_reporting=bool(ctrl_word & (1 << 2)),
            unsupported_request_reporting=bool(ctrl_word & (1 << 3)),
        )

    def set_device_control(
        self, mps: int | None = None, mrrs: int | None = None
    ) -> DeviceControlStatus:
        """Modify Device Control register (read-modify-write).

        Args:
            mps: New Max Payload Size in bytes (128-4096), or None to leave unchanged.
            mrrs: New Max Read Request Size in bytes (128-4096), or None to leave unchanged.

        Returns:
            Updated DeviceControlStatus after write.
        """
        pcie_cap = self._require_pcie_cap()
        reg_offset = pcie_cap + 0x08
        current = self.read_config_register(reg_offset)

        ctrl_word = current & 0xFFFF

        if mps is not None:
            mps_code = _encode_payload(mps)
            ctrl_word = (ctrl_word & ~(0x7 << 5)) | (mps_code << 5)

        if mrrs is not None:
            mrrs_code = _encode_payload(mrrs)
            ctrl_word = (ctrl_word & ~(0x7 << 12)) | (mrrs_code << 12)

        new_value = (current & 0xFFFF0000) | ctrl_word
        self.write_config_register(reg_offset, new_value)

        return self.get_device_control()

    def get_link_capabilities(self) -> LinkCapabilities:
        """Read Link Capabilities register (PCIe Cap + 0x0C)."""
        pcie_cap = self._require_pcie_cap()
        link_cap = self.read_config_register(pcie_cap + 0x0C)

        max_speed_code = link_cap & 0xF
        max_width = (link_cap >> 4) & 0x3F
        aspm_code = (link_cap >> 10) & 0x3
        port_number = (link_cap >> 24) & 0xFF

        return LinkCapabilities(
            max_link_speed=_SPEED_MAP.get(max_speed_code, f"Unknown({max_speed_code})"),
            max_link_width=max_width,
            aspm_support=_ASPM_MAP.get(aspm_code, "unknown"),
            port_number=port_number,
            dll_link_active_capable=bool(link_cap & (1 << 20)),
            surprise_down_capable=bool(link_cap & (1 << 19)),
        )

    def get_link_status(self) -> LinkControlStatus:
        """Read Link Control + Status + Link Control 2 registers."""
        pcie_cap = self._require_pcie_cap()

        link_ctrl_status = self.read_config_register(pcie_cap + 0x10)
        ctrl_word = link_ctrl_status & 0xFFFF
        status_word = (link_ctrl_status >> 16) & 0xFFFF

        current_speed_code = status_word & 0xF
        current_width = (status_word >> 4) & 0x3F

        link_ctrl2 = self.read_config_register(pcie_cap + 0x30)
        target_speed_code = link_ctrl2 & 0xF

        aspm_code = ctrl_word & 0x3

        return LinkControlStatus(
            current_speed=_SPEED_MAP.get(current_speed_code, f"Unknown({current_speed_code})"),
            current_width=current_width,
            target_speed=_SPEED_MAP.get(target_speed_code, f"Unknown({target_speed_code})"),
            aspm_control=_ASPM_MAP.get(aspm_code, "unknown"),
            link_training=bool(status_word & (1 << 11)),
            dll_link_active=bool(status_word & (1 << 13)),
            retrain_link=bool(ctrl_word & (1 << 5)),
        )

    def retrain_link(self) -> None:
        """Write bit 5 of Link Control to initiate link retraining."""
        pcie_cap = self._require_pcie_cap()
        reg_offset = pcie_cap + 0x10
        current = self.read_config_register(reg_offset)

        ctrl_word = current & 0xFFFF
        ctrl_word |= (1 << 5)
        new_value = (current & 0xFFFF0000) | ctrl_word
        self.write_config_register(reg_offset, new_value)

    def set_target_link_speed(self, speed: int) -> None:
        """Set target link speed in Link Control 2 bits [3:0].

        Args:
            speed: Speed code 1-6 (Gen1 through Gen6).
        """
        if speed < 1 or speed > 6:
            raise ValueError(f"Invalid speed code {speed}, must be 1-6")

        pcie_cap = self._require_pcie_cap()
        reg_offset = pcie_cap + 0x30
        current = self.read_config_register(reg_offset)

        new_value = (current & ~0xF) | speed
        self.write_config_register(reg_offset, new_value)

    def get_aer_status(self) -> AerStatus | None:
        """Read AER extended capability registers.

        Returns:
            AerStatus with all error fields, or None if AER not present.
        """
        aer_offset = self.find_extended_capability(_EXT_CAP_AER)
        if aer_offset is None:
            return None

        uncorr_raw = self.read_config_register(aer_offset + 0x04)
        corr_raw = self.read_config_register(aer_offset + 0x10)
        cap_ctrl = self.read_config_register(aer_offset + 0x18)
        first_error_pointer = cap_ctrl & 0x1F

        header_log = [
            self.read_config_register(aer_offset + 0x1C),
            self.read_config_register(aer_offset + 0x20),
            self.read_config_register(aer_offset + 0x24),
            self.read_config_register(aer_offset + 0x28),
        ]

        uncorrectable = AerUncorrectableErrors(
            data_link_protocol=bool(uncorr_raw & (1 << 4)),
            surprise_down=bool(uncorr_raw & (1 << 5)),
            poisoned_tlp=bool(uncorr_raw & (1 << 12)),
            flow_control_protocol=bool(uncorr_raw & (1 << 13)),
            completion_timeout=bool(uncorr_raw & (1 << 14)),
            completer_abort=bool(uncorr_raw & (1 << 15)),
            unexpected_completion=bool(uncorr_raw & (1 << 16)),
            receiver_overflow=bool(uncorr_raw & (1 << 17)),
            malformed_tlp=bool(uncorr_raw & (1 << 18)),
            ecrc_error=bool(uncorr_raw & (1 << 19)),
            unsupported_request=bool(uncorr_raw & (1 << 20)),
            acs_violation=bool(uncorr_raw & (1 << 21)),
            raw_value=uncorr_raw,
        )

        correctable = AerCorrectableErrors(
            receiver_error=bool(corr_raw & (1 << 0)),
            bad_tlp=bool(corr_raw & (1 << 6)),
            bad_dllp=bool(corr_raw & (1 << 7)),
            replay_num_rollover=bool(corr_raw & (1 << 8)),
            replay_timer_timeout=bool(corr_raw & (1 << 12)),
            advisory_non_fatal=bool(corr_raw & (1 << 13)),
            raw_value=corr_raw,
        )

        return AerStatus(
            aer_offset=aer_offset,
            uncorrectable=uncorrectable,
            correctable=correctable,
            first_error_pointer=first_error_pointer,
            header_log=header_log,
        )

    def clear_aer_errors(self) -> None:
        """Clear AER error status registers (write-1-to-clear)."""
        aer_offset = self.find_extended_capability(_EXT_CAP_AER)
        if aer_offset is None:
            return

        self.write_config_register(aer_offset + 0x04, 0xFFFFFFFF)
        self.write_config_register(aer_offset + 0x10, 0xFFFFFFFF)

    def get_supported_speeds(self) -> SupportedSpeedsVector:
        """Read Supported Link Speeds Vector from Link Capabilities 2.

        Link Capabilities 2 is at PCIe Cap + 0x2C.
        Bits [7:1] contain the supported link speeds vector.
        """
        pcie_cap = self._require_pcie_cap()
        link_cap2 = self.read_config_register(pcie_cap + 0x2C)
        vector = (link_cap2 >> 1) & 0x7F

        return SupportedSpeedsVector(
            gen1=bool(vector & (1 << 0)),
            gen2=bool(vector & (1 << 1)),
            gen3=bool(vector & (1 << 2)),
            gen4=bool(vector & (1 << 3)),
            gen5=bool(vector & (1 << 4)),
            gen6=bool(vector & (1 << 5)),
            raw_value=vector,
        )

    def get_eq_status_16gt(self) -> EqStatus16GT | None:
        """Read equalization status from Physical Layer 16 GT/s Extended Capability.

        Returns:
            EqStatus16GT with EQ phase status, or None if capability not present.
        """
        offset = self.find_extended_capability(_EXT_CAP_PHY_16GT)
        if offset is None:
            return None

        status_reg = self.read_config_register(offset + 0x0C)
        return EqStatus16GT(
            complete=bool(status_reg & (1 << 0)),
            phase1_success=bool(status_reg & (1 << 1)),
            phase2_success=bool(status_reg & (1 << 2)),
            phase3_success=bool(status_reg & (1 << 3)),
            link_eq_request=bool(status_reg & (1 << 4)),
            raw_value=status_reg,
        )

    def get_eq_status_32gt(self) -> EqStatus32GT | None:
        """Read equalization status from Physical Layer 32 GT/s Extended Capability.

        Returns:
            EqStatus32GT with EQ phase status and capabilities, or None if not present.
        """
        offset = self.find_extended_capability(_EXT_CAP_PHY_32GT)
        if offset is None:
            return None

        cap_reg = self.read_config_register(offset + 0x04)
        status_reg = self.read_config_register(offset + 0x0C)

        return EqStatus32GT(
            complete=bool(status_reg & (1 << 0)),
            phase1_success=bool(status_reg & (1 << 1)),
            phase2_success=bool(status_reg & (1 << 2)),
            phase3_success=bool(status_reg & (1 << 3)),
            link_eq_request=bool(status_reg & (1 << 4)),
            modified_ts_received=bool(status_reg & (1 << 5)),
            rx_lane_margin_capable=bool(status_reg & (1 << 6)),
            rx_lane_margin_status=bool(status_reg & (1 << 7)),
            eq_bypass_to_highest=bool(cap_reg & (1 << 0)),
            no_eq_needed=bool(cap_reg & (1 << 1)),
            raw_status=status_reg,
            raw_capabilities=cap_reg,
        )

    def get_lane_margining_offset(self) -> int | None:
        """Find Lane Margining at Receiver Extended Capability offset.

        Returns:
            Offset of the capability, or None if not present.
        """
        return self.find_extended_capability(_EXT_CAP_LANE_MARGIN)
