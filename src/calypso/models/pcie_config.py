"""PCIe configuration space, capability, AER, link, and device control models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ConfigRegister(BaseModel):
    """A single config space register read."""

    offset: int
    value: int
    size: int = 4


class PcieCapabilityInfo(BaseModel):
    """A discovered PCI/PCIe capability."""

    cap_id: int
    cap_name: str
    offset: int
    version: int = 0


class DeviceCapabilities(BaseModel):
    """Device Capabilities register fields (PCIe Cap + 0x04)."""

    max_payload_supported: int
    flr_capable: bool
    extended_tag_supported: bool
    role_based_error_reporting: bool


class DeviceControlStatus(BaseModel):
    """Device Control and Status register fields (PCIe Cap + 0x08)."""

    max_payload_size: int
    max_read_request_size: int
    relaxed_ordering: bool
    no_snoop: bool
    extended_tag_enabled: bool
    correctable_error_reporting: bool
    non_fatal_error_reporting: bool
    fatal_error_reporting: bool
    unsupported_request_reporting: bool


class LinkCapabilities(BaseModel):
    """Link Capabilities register fields (PCIe Cap + 0x0C)."""

    max_link_speed: str
    max_link_width: int
    aspm_support: str
    port_number: int
    dll_link_active_capable: bool
    surprise_down_capable: bool


class LinkControlStatus(BaseModel):
    """Link Control, Status, and Link Control 2 register fields."""

    current_speed: str
    current_width: int
    target_speed: str
    aspm_control: str
    link_training: bool
    dll_link_active: bool
    retrain_link: bool


class AerUncorrectableErrors(BaseModel):
    """Bit fields from AER Uncorrectable Error Status (+0x04)."""

    data_link_protocol: bool = False
    surprise_down: bool = False
    poisoned_tlp: bool = False
    flow_control_protocol: bool = False
    completion_timeout: bool = False
    completer_abort: bool = False
    unexpected_completion: bool = False
    receiver_overflow: bool = False
    malformed_tlp: bool = False
    ecrc_error: bool = False
    unsupported_request: bool = False
    acs_violation: bool = False
    raw_value: int = 0


class AerCorrectableErrors(BaseModel):
    """Bit fields from AER Correctable Error Status (+0x10)."""

    receiver_error: bool = False
    bad_tlp: bool = False
    bad_dllp: bool = False
    replay_num_rollover: bool = False
    replay_timer_timeout: bool = False
    advisory_non_fatal: bool = False
    raw_value: int = 0


class AerStatus(BaseModel):
    """Complete AER status from extended capability registers."""

    aer_offset: int
    uncorrectable: AerUncorrectableErrors
    correctable: AerCorrectableErrors
    first_error_pointer: int
    header_log: list[int] = Field(default_factory=list)


class SupportedSpeedsVector(BaseModel):
    """Supported Link Speeds Vector from Link Capabilities 2 (PCIe Cap + 0x2C)."""

    gen1: bool = False
    gen2: bool = False
    gen3: bool = False
    gen4: bool = False
    gen5: bool = False
    gen6: bool = False
    raw_value: int = 0

    @property
    def max_supported(self) -> str:
        """Return the highest supported speed string."""
        for gen, label in reversed(
            list(enumerate(["Gen1", "Gen2", "Gen3", "Gen4", "Gen5", "Gen6"], start=1))
        ):
            if getattr(self, f"gen{gen}", False):
                return label
        return "Unknown"

    @property
    def as_list(self) -> list[str]:
        """Return list of supported speed strings."""
        result: list[str] = []
        for gen in range(1, 7):
            if getattr(self, f"gen{gen}", False):
                result.append(f"Gen{gen}")
        return result


class EqStatus16GT(BaseModel):
    """Equalization status from Physical Layer 16 GT/s Extended Capability."""

    complete: bool = False
    phase1_success: bool = False
    phase2_success: bool = False
    phase3_success: bool = False
    link_eq_request: bool = False
    raw_value: int = 0


class EqStatus32GT(BaseModel):
    """Equalization status from Physical Layer 32 GT/s Extended Capability."""

    complete: bool = False
    phase1_success: bool = False
    phase2_success: bool = False
    phase3_success: bool = False
    link_eq_request: bool = False
    modified_ts_received: bool = False
    rx_lane_margin_capable: bool = False
    rx_lane_margin_status: bool = False
    eq_bypass_to_highest: bool = False
    no_eq_needed: bool = False
    raw_status: int = 0
    raw_capabilities: int = 0


class EqStatus64GT(BaseModel):
    """Equalization status from Physical Layer 64 GT/s Extended Capability."""

    complete: bool = False
    phase1_success: bool = False
    phase2_success: bool = False
    phase3_success: bool = False
    link_eq_request: bool = False
    flit_mode_supported: bool = False
    no_eq_needed: bool = False
    raw_status: int = 0
    raw_capabilities: int = 0


class ConfigSpaceDump(BaseModel):
    """Raw config space dump with discovered capabilities."""

    port_number: int
    registers: list[ConfigRegister] = Field(default_factory=list)
    capabilities: list[PcieCapabilityInfo] = Field(default_factory=list)


# =============================================================================
# Flit Logging (Extended Capability 0x0032)
# =============================================================================


class FlitErrorLogEntry(BaseModel):
    """A single decoded Flit Error Log FIFO entry."""

    valid: bool = False
    link_width: int = 0
    flit_offset: int = 0
    consecutive_errors: int = 0
    more_entries: bool = False
    unrecognized_flit: bool = False
    fec_uncorrectable: bool = False
    syndrome_0: int = 0
    syndrome_1: int = 0
    syndrome_2: int = 0
    syndrome_3: int = 0
    raw_log1: int = 0
    raw_log2: int = 0


class FlitErrorCounter(BaseModel):
    """Flit Error Counter control + status."""

    enable: bool = False
    interrupt_enable: bool = False
    events_to_count: int = 0
    trigger_event_count: int = 0
    link_width: int = 0
    interrupt_generated: bool = False
    counter: int = 0
    raw_value: int = 0


class FberStatus(BaseModel):
    """FBER (Flit Bit Error Rate) measurement status."""

    enabled: bool = False
    granularity: int = 0
    flit_counter: int = 0
    lane_counters: list[int] = Field(default_factory=list)
    raw_control: int = 0


class FlitLoggingStatus(BaseModel):
    """Composite Flit Logging capability status."""

    cap_offset: int
    error_log_entries: list[FlitErrorLogEntry] = Field(default_factory=list)
    error_counter: FlitErrorCounter = Field(default_factory=FlitErrorCounter)
    fber: FberStatus = Field(default_factory=FberStatus)


# =============================================================================
# Flit Performance Measurement (Extended Capability 0x0033)
# =============================================================================


class FlitPerfConfig(BaseModel):
    """Configuration for Flit Performance Measurement."""

    response_type: int = Field(default=0, ge=0, le=0x7)
    flit_type: int = Field(default=0, ge=0, le=0x3)
    num_instances: int = Field(default=1, ge=0, le=0x1F)
    interrupt_threshold: int = Field(default=0, ge=0, le=0x7)
    ltssm_tracker: int = Field(default=0, ge=0, le=0x1F)
    ltssm_num_instances: int = Field(default=0, ge=0, le=0x1F)


class FlitPerfLtssmStatus(BaseModel):
    """Per-LTSSM-register status from Flit Perf Measurement."""

    tracking_status: int = 0
    tracking_count: int = 0
    interrupt: bool = False
    counter: int = 0
    raw_value: int = 0


class FlitPerfStatus(BaseModel):
    """Composite Flit Performance Measurement status."""

    cap_offset: int
    interrupt_vector: int = 0
    ltssm_tracking_count: int = 0
    tracking_status: int = 0
    flits_tracked: int = 0
    interrupt_generated: bool = False
    ltssm_counter: int = 0
    ltssm_statuses: list[FlitPerfLtssmStatus] = Field(default_factory=list)
    raw_capability: int = 0
    raw_control: int = 0
    raw_status: int = 0


# =============================================================================
# Flit Error Injection (Extended Capability 0x0034)
# =============================================================================


class FlitErrorInjectionConfig(BaseModel):
    """Configuration for Flit error injection."""

    inject_tx: bool = True
    inject_rx: bool = False
    data_rate: int = Field(default=0, ge=0, le=0x1FFF)
    num_errors: int = Field(default=1, ge=0, le=0x1F)
    spacing: int = Field(default=0, ge=0, le=0xFF)
    flit_type: int = Field(default=0, ge=0, le=0x7)
    consecutive: int = Field(default=0, ge=0, le=0x7)
    error_type: int = Field(default=0, ge=0, le=0x3)
    error_offset: int = Field(default=0, ge=0, le=0x7F)
    error_magnitude: int = Field(default=0, ge=0, le=0xFF)


class OsErrorInjectionConfig(BaseModel):
    """Configuration for Ordered Set error injection."""

    inject_tx: bool = True
    inject_rx: bool = False
    num_errors: int = Field(default=1, ge=0, le=0x1F)
    spacing: int = Field(default=0, ge=0, le=0xFF)
    os_type_skp: bool = False
    os_type_eieos: bool = False
    os_type_ts1: bool = False
    os_type_ts2: bool = False
    os_type_eios: bool = False
    os_type_sds: bool = False
    os_type_eideos: bool = False
    ltssm_detect: bool = False
    ltssm_polling: bool = False
    ltssm_config: bool = False
    ltssm_l0: bool = False
    ltssm_recovery: bool = False
    ltssm_loopback: bool = False
    ltssm_hot_reset: bool = False
    error_bytes: int = Field(default=0, ge=0, le=0xFFFF)
    lane_mask: int = Field(default=0xFFFF, ge=0, le=0xFFFF)


class FlitErrorInjectionStatus(BaseModel):
    """Composite Flit Error Injection capability status."""

    cap_offset: int
    flit_tx_status: int = 0
    flit_rx_status: int = 0
    os_tx_status: int = 0
    os_rx_status: int = 0
    raw_flit_ctl1: int = 0
    raw_flit_ctl2: int = 0
    raw_flit_status: int = 0
    raw_os_ctl1: int = 0
    raw_os_ctl2: int = 0
    raw_os_tx_status: int = 0
    raw_os_rx_status: int = 0
