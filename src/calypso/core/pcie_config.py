"""PCIe configuration space reader with capability walking, AER, and link control."""

from __future__ import annotations

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.hardware.pcie_registers import (
    AERCapability,
    CorrErrBits,
    DevCapBits,
    ExtCapabilityID,
    LinkCapBits,
    LinkCap2Bits,
    LinkCtl2Bits,
    LinkCtlBits,
    LinkStsBits,
    PCIeCapability,
    PCIeCapabilityID,
    PCIeLinkSpeed,
    SPEED_STRINGS,
    UncorrErrBits,
)
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


# Human-readable display names for standard capabilities.
# These preserve acronyms and conventional formatting from the PCI spec.
_STD_CAP_DISPLAY: dict[PCIeCapabilityID, str] = {
    PCIeCapabilityID.POWER_MANAGEMENT: "PCI Power Management",
    PCIeCapabilityID.AGP: "AGP",
    PCIeCapabilityID.VPD: "VPD",
    PCIeCapabilityID.SLOT_ID: "Slot Identification",
    PCIeCapabilityID.MSI: "MSI",
    PCIeCapabilityID.HOT_SWAP: "CompactPCI Hot Swap",
    PCIeCapabilityID.PCIX: "PCI-X",
    PCIeCapabilityID.HYPERTRANSPORT: "HyperTransport",
    PCIeCapabilityID.VENDOR_SPECIFIC: "Vendor Specific",
    PCIeCapabilityID.DEBUG_PORT: "Debug Port",
    PCIeCapabilityID.CPCI_CRC: "CompactPCI CRC",
    PCIeCapabilityID.HOT_PLUG: "PCI Hot Plug",
    PCIeCapabilityID.BRIDGE_SUBSYS_VENDOR: "PCI Bridge Subsystem VID",
    PCIeCapabilityID.AGP_8X: "AGP 8x",
    PCIeCapabilityID.SECURE_DEVICE: "Secure Device",
    PCIeCapabilityID.PCIE: "PCI Express",
    PCIeCapabilityID.MSIX: "MSI-X",
    PCIeCapabilityID.SATA: "SATA Config",
    PCIeCapabilityID.AF: "AF",
    PCIeCapabilityID.EA: "Enhanced Allocation",
    PCIeCapabilityID.FPB: "Flattening Portal Bridge",
}

# Human-readable display names for extended capabilities.
_EXT_CAP_DISPLAY: dict[ExtCapabilityID, str] = {
    ExtCapabilityID.AER: "AER",
    ExtCapabilityID.VC: "VC",
    ExtCapabilityID.SERIAL_NUMBER: "Serial Number",
    ExtCapabilityID.POWER_BUDGETING: "Power Budgeting",
    ExtCapabilityID.ROOT_COMPLEX_LINK_DECL: "Root Complex Link Declaration",
    ExtCapabilityID.ROOT_COMPLEX_INTERNAL_LINK: "Root Complex Internal Link",
    ExtCapabilityID.ROOT_COMPLEX_EVENT_COLLECTOR: "Root Complex Event Collector",
    ExtCapabilityID.MFVC: "MFVC",
    ExtCapabilityID.VC_WITH_MFVC: "VC (MFVC)",
    ExtCapabilityID.RCRB: "RCRB Header",
    ExtCapabilityID.VENDOR_SPECIFIC: "Vendor Specific",
    ExtCapabilityID.CAC: "Config Access Correlation",
    ExtCapabilityID.ACS: "ACS",
    ExtCapabilityID.ARI: "ARI",
    ExtCapabilityID.ATS: "ATS",
    ExtCapabilityID.SR_IOV: "SR-IOV",
    ExtCapabilityID.MR_IOV: "MR-IOV",
    ExtCapabilityID.MULTICAST: "Multicast",
    ExtCapabilityID.PRI: "Page Request",
    ExtCapabilityID.REBAR: "Resizable BAR",
    ExtCapabilityID.DPA: "Dynamic Power Allocation",
    ExtCapabilityID.TPH: "TPH",
    ExtCapabilityID.LTR: "LTR",
    ExtCapabilityID.SECONDARY_PCIE: "Secondary PCIe",
    ExtCapabilityID.PMUX: "PMUX",
    ExtCapabilityID.PASID: "PASID",
    ExtCapabilityID.LNR: "LN Requester",
    ExtCapabilityID.DPC: "DPC",
    ExtCapabilityID.L1_PM_SUBSTATES: "L1 PM Substates",
    ExtCapabilityID.PTM: "Precision Time Measurement",
    ExtCapabilityID.MPCIE: "M-PCIe",
    ExtCapabilityID.FRS_QUEUEING: "FRS Queueing",
    ExtCapabilityID.RTR: "Readiness Time Reporting",
    ExtCapabilityID.DVSEC: "Designated Vendor Specific",
    ExtCapabilityID.VF_REBAR: "VF Resizable BAR",
    ExtCapabilityID.DATA_LINK_FEATURE: "Data Link Feature",
    ExtCapabilityID.PHYSICAL_LAYER_16GT: "Physical Layer 16.0 GT/s",
    ExtCapabilityID.RECEIVER_LANE_MARGINING: "Lane Margining at Receiver",
    ExtCapabilityID.HIERARCHY_ID: "Hierarchy ID",
    ExtCapabilityID.NATIVE_PCIE_ENCLOSURE: "NPEM",
    ExtCapabilityID.PHYSICAL_LAYER_32GT: "Physical Layer 32.0 GT/s",
    ExtCapabilityID.ALTERNATE_PROTOCOL: "Alternate Protocol",
    ExtCapabilityID.SFI: "SFI",
    ExtCapabilityID.SHADOW_FUNCTIONS: "Shadow Functions",
    ExtCapabilityID.DOE: "Data Object Exchange",
    ExtCapabilityID.DEVICE_3: "Device 3",
    ExtCapabilityID.IDE: "IDE",
    ExtCapabilityID.PHYSICAL_LAYER_64GT: "Physical Layer 64.0 GT/s",
    ExtCapabilityID.FLIT_LOGGING: "FLIT Logging",
    ExtCapabilityID.FLIT_PERF_MEASUREMENT: "FLIT Performance Measurement",
    ExtCapabilityID.FLIT_ERROR_INJECTION: "FLIT Error Injection",
}


def _std_cap_name(cap_id: int) -> str:
    """Look up a human-readable standard capability name."""
    try:
        member = PCIeCapabilityID(cap_id)
        return _STD_CAP_DISPLAY.get(member, member.name.replace("_", " ").title())
    except ValueError:
        return f"Unknown(0x{cap_id:02X})"


def _ext_cap_name(cap_id: int) -> str:
    """Look up a human-readable extended capability name."""
    try:
        member = ExtCapabilityID(cap_id)
        return _EXT_CAP_DISPLAY.get(member, member.name.replace("_", " ").title())
    except ValueError:
        return f"ExtUnknown(0x{cap_id:04X})"


def _speed_name(code: int) -> str:
    """Convert a speed code to a human-readable generation string."""
    try:
        return SPEED_STRINGS[PCIeLinkSpeed(code)].split(" ")[0]  # "Gen4 (16.0 GT/s)" -> "Gen4"
    except (ValueError, KeyError):
        return f"Unknown({code})"

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

            cap_name = _std_cap_name(cap_id)
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

            cap_name = _ext_cap_name(cap_id)
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
        offset = self.find_capability(PCIeCapabilityID.PCIE)
        if offset is None:
            raise ValueError("PCIe capability not found in config space")
        return offset

    def get_device_capabilities(self) -> DeviceCapabilities:
        """Read Device Capabilities register."""
        pcie_cap = self._require_pcie_cap()
        dev_cap = self.read_config_register(pcie_cap + PCIeCapability.DEV_CAP)

        mps_supported_code = dev_cap & int(DevCapBits.MAX_PAYLOAD_MASK)
        return DeviceCapabilities(
            max_payload_supported=_decode_payload(mps_supported_code),
            flr_capable=bool(dev_cap & DevCapBits.FLR_CAPABLE),
            extended_tag_supported=bool(dev_cap & DevCapBits.EXT_TAG_SUPPORTED),
            role_based_error_reporting=bool(dev_cap & DevCapBits.ROLE_BASED_ERR_RPT),
        )

    def get_device_control(self) -> DeviceControlStatus:
        """Read Device Control + Status registers."""
        pcie_cap = self._require_pcie_cap()
        dev_ctrl = self.read_config_register(pcie_cap + PCIeCapability.DEV_CTL)

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
        reg_offset = pcie_cap + PCIeCapability.DEV_CTL
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
        """Read Link Capabilities register."""
        pcie_cap = self._require_pcie_cap()
        link_cap = self.read_config_register(pcie_cap + PCIeCapability.LINK_CAP)

        max_speed_code = link_cap & int(LinkCapBits.MAX_LINK_SPEED_MASK)
        max_width = (link_cap & int(LinkCapBits.MAX_LINK_WIDTH_MASK)) >> 4
        aspm_code = (link_cap >> 10) & 0x3
        port_number = (link_cap & int(LinkCapBits.PORT_NUMBER_MASK)) >> 24

        return LinkCapabilities(
            max_link_speed=_speed_name(max_speed_code),
            max_link_width=max_width,
            aspm_support=_ASPM_MAP.get(aspm_code, "unknown"),
            port_number=port_number,
            dll_link_active_capable=bool(link_cap & LinkCapBits.DL_ACTIVE_REPORTING),
            surprise_down_capable=bool(link_cap & LinkCapBits.SURPRISE_DOWN_ERR),
        )

    def get_link_status(self) -> LinkControlStatus:
        """Read Link Control + Status + Link Control 2 registers."""
        pcie_cap = self._require_pcie_cap()

        link_ctrl_status = self.read_config_register(pcie_cap + PCIeCapability.LINK_CTL)
        ctrl_word = link_ctrl_status & 0xFFFF
        status_word = (link_ctrl_status >> 16) & 0xFFFF

        current_speed_code = status_word & int(LinkStsBits.CURRENT_LINK_SPEED_MASK)
        current_width = (status_word & int(LinkStsBits.NEGOTIATED_WIDTH_MASK)) >> 4

        link_ctrl2 = self.read_config_register(pcie_cap + PCIeCapability.LINK_CTL2)
        target_speed_code = link_ctrl2 & int(LinkCtl2Bits.TARGET_LINK_SPEED_MASK)

        aspm_code = ctrl_word & int(LinkCtlBits.ASPM_MASK)

        return LinkControlStatus(
            current_speed=_speed_name(current_speed_code),
            current_width=current_width,
            target_speed=_speed_name(target_speed_code),
            aspm_control=_ASPM_MAP.get(aspm_code, "unknown"),
            link_training=bool(status_word & LinkStsBits.LINK_TRAINING),
            dll_link_active=bool(status_word & LinkStsBits.DL_LINK_ACTIVE),
            retrain_link=bool(ctrl_word & LinkCtlBits.RETRAIN_LINK),
        )

    def retrain_link(self) -> None:
        """Set the Retrain Link bit in Link Control to initiate retraining."""
        pcie_cap = self._require_pcie_cap()
        reg_offset = pcie_cap + PCIeCapability.LINK_CTL
        current = self.read_config_register(reg_offset)

        ctrl_word = current & 0xFFFF
        ctrl_word |= int(LinkCtlBits.RETRAIN_LINK)
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
        reg_offset = pcie_cap + PCIeCapability.LINK_CTL2
        current = self.read_config_register(reg_offset)

        mask = int(LinkCtl2Bits.TARGET_LINK_SPEED_MASK)
        new_value = (current & ~mask) | speed
        self.write_config_register(reg_offset, new_value)

    def get_aer_status(self) -> AerStatus | None:
        """Read AER extended capability registers.

        Returns:
            AerStatus with all error fields, or None if AER not present.
        """
        aer_offset = self.find_extended_capability(ExtCapabilityID.AER)
        if aer_offset is None:
            return None

        uncorr_raw = self.read_config_register(aer_offset + AERCapability.UNCORR_ERR_STATUS)
        corr_raw = self.read_config_register(aer_offset + AERCapability.CORR_ERR_STATUS)
        cap_ctrl = self.read_config_register(aer_offset + AERCapability.ADV_ERR_CAP_CTL)
        first_error_pointer = cap_ctrl & 0x1F

        header_log = [
            self.read_config_register(aer_offset + AERCapability.HEADER_LOG_0),
            self.read_config_register(aer_offset + AERCapability.HEADER_LOG_1),
            self.read_config_register(aer_offset + AERCapability.HEADER_LOG_2),
            self.read_config_register(aer_offset + AERCapability.HEADER_LOG_3),
        ]

        uncorrectable = AerUncorrectableErrors(
            data_link_protocol=bool(uncorr_raw & UncorrErrBits.DL_PROTOCOL_ERR),
            surprise_down=bool(uncorr_raw & UncorrErrBits.SURPRISE_DOWN),
            poisoned_tlp=bool(uncorr_raw & UncorrErrBits.POISONED_TLP),
            flow_control_protocol=bool(uncorr_raw & UncorrErrBits.FC_PROTOCOL_ERR),
            completion_timeout=bool(uncorr_raw & UncorrErrBits.COMPLETION_TIMEOUT),
            completer_abort=bool(uncorr_raw & UncorrErrBits.COMPLETER_ABORT),
            unexpected_completion=bool(uncorr_raw & UncorrErrBits.UNEXPECTED_COMPLETION),
            receiver_overflow=bool(uncorr_raw & UncorrErrBits.RECEIVER_OVERFLOW),
            malformed_tlp=bool(uncorr_raw & UncorrErrBits.MALFORMED_TLP),
            ecrc_error=bool(uncorr_raw & UncorrErrBits.ECRC_ERR),
            unsupported_request=bool(uncorr_raw & UncorrErrBits.UNSUPPORTED_REQ),
            acs_violation=bool(uncorr_raw & UncorrErrBits.ACS_VIOLATION),
            raw_value=uncorr_raw,
        )

        correctable = AerCorrectableErrors(
            receiver_error=bool(corr_raw & CorrErrBits.RECEIVER_ERR),
            bad_tlp=bool(corr_raw & CorrErrBits.BAD_TLP),
            bad_dllp=bool(corr_raw & CorrErrBits.BAD_DLLP),
            replay_num_rollover=bool(corr_raw & CorrErrBits.REPLAY_NUM_ROLLOVER),
            replay_timer_timeout=bool(corr_raw & CorrErrBits.REPLAY_TIMER_TIMEOUT),
            advisory_non_fatal=bool(corr_raw & CorrErrBits.ADVISORY_NONFATAL),
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
        aer_offset = self.find_extended_capability(ExtCapabilityID.AER)
        if aer_offset is None:
            return

        self.write_config_register(aer_offset + AERCapability.UNCORR_ERR_STATUS, 0xFFFFFFFF)
        self.write_config_register(aer_offset + AERCapability.CORR_ERR_STATUS, 0xFFFFFFFF)

    def get_supported_speeds(self) -> SupportedSpeedsVector:
        """Read Supported Link Speeds Vector from Link Capabilities 2."""
        pcie_cap = self._require_pcie_cap()
        link_cap2 = self.read_config_register(pcie_cap + PCIeCapability.LINK_CAP2)
        vector = (link_cap2 >> 1) & 0x7F

        return SupportedSpeedsVector(
            gen1=bool(link_cap2 & LinkCap2Bits.SPEED_2_5GT),
            gen2=bool(link_cap2 & LinkCap2Bits.SPEED_5GT),
            gen3=bool(link_cap2 & LinkCap2Bits.SPEED_8GT),
            gen4=bool(link_cap2 & LinkCap2Bits.SPEED_16GT),
            gen5=bool(link_cap2 & LinkCap2Bits.SPEED_32GT),
            gen6=bool(link_cap2 & LinkCap2Bits.SPEED_64GT),
            raw_value=vector,
        )

    def get_eq_status_16gt(self) -> EqStatus16GT | None:
        """Read equalization status from Physical Layer 16 GT/s Extended Capability.

        Returns:
            EqStatus16GT with EQ phase status, or None if capability not present.
        """
        offset = self.find_extended_capability(ExtCapabilityID.PHYSICAL_LAYER_16GT)
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
        offset = self.find_extended_capability(ExtCapabilityID.PHYSICAL_LAYER_32GT)
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
        return self.find_extended_capability(ExtCapabilityID.RECEIVER_LANE_MARGINING)
