"""Atlas3 vendor-specific physical layer register definitions.

These registers are implementation-specific to the Atlas3 switch silicon.
Users should interact through the PhyMonitor domain class, not directly
with these register definitions.

Register offsets are relative to the per-port register base:
    base = 0x60800000 + (port_number * 0x8000)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, IntFlag


# ---------------------------------------------------------------------------
# Register Offsets
# ---------------------------------------------------------------------------

class VendorPhyRegs(IntEnum):
    """Vendor-specific physical layer register offsets (per-station)."""

    PORT_CONTROL = 0x3208       # LTSSM and test pattern control
    UTP_PATTERN_0 = 0x320C      # User Test Pattern bytes 0-3
    UTP_PATTERN_4 = 0x3210      # User Test Pattern bytes 4-7
    UTP_PATTERN_8 = 0x3214      # User Test Pattern bytes 8-11
    UTP_PATTERN_12 = 0x3218     # User Test Pattern bytes 12-15
    PHY_CMD_STATUS = 0x321C     # Physical Layer Command/Status
    PHY_ADDITIONAL_STATUS = 0x3254  # Link speed, link down count, lane reversal
    SERDES_DIAG_QUAD0 = 0x3238  # SerDes Diagnostic Data, Quad 0
    SERDES_DIAG_QUAD1 = 0x323C  # SerDes Diagnostic Data, Quad 1
    SERDES_DIAG_QUAD2 = 0x3240  # SerDes Diagnostic Data, Quad 2
    SERDES_DIAG_QUAD3 = 0x3244  # SerDes Diagnostic Data, Quad 3
    RECOVERY_DIAGNOSTIC = 0x3BC4    # Recovery count / LTSSM state readback
    LTSSM_STATE_MACHINE = 0x3DAC   # Detailed sub-state readback + override
    # Ptrace Ingress Capture registers
    PTRACE_CAPTURE_CONTROL = 0x4000
    PTRACE_CAPTURE_STATUS = 0x4004
    PTRACE_CAPTURE_CONFIG = 0x4008
    PTRACE_POST_TRIGGER = 0x400C
    PTRACE_TRIGGER_CONFIG = 0x4020
    PTRACE_RAM_ADDRESS = 0x4028
    PTRACE_RAM_DATA = 0x402C
    PTRACE_TRIGGER_COND_0 = 0x4038


# ---------------------------------------------------------------------------
# Test Pattern Rate
# ---------------------------------------------------------------------------

class TestPatternRate(IntEnum):
    """Test pattern transmission rate selection (Port Control bits [4:3])."""

    RATE_2_5GT = 0   # Gen1
    RATE_5_0GT = 1   # Gen2
    RATE_8_0GT = 2   # Gen3
    RATE_16_0GT = 3  # Gen4
    RATE_32_0GT = 4  # Gen5
    RATE_64_0GT = 5  # Gen6


# ---------------------------------------------------------------------------
# Port Control Register (0x3208)
# ---------------------------------------------------------------------------

class _PortControlBits(IntFlag):
    """Port Control Register bit definitions."""

    DISABLE_PORT = 1 << 0          # Forces LTSSM to Detect.Quiet
    PORT_QUIET = 1 << 1            # Holds port in Detect.Quiet state
    LOCK_DOWN_FE_PRESET = 1 << 2   # Lock down far-end preset
    # Bits 4:3 = Test Pattern Rate (use TestPatternRate)
    # Bits 23:8 = Bypass UTP Alignment Pattern (1 bit per lane)
    # Bits 27:24 = Port Select
    WRITE_ENABLE = 1 << 31         # Must be set to write control bits


@dataclass
class PortControlRegister:
    """Port Control Register (0x3208) field access.

    Controls LTSSM within a specified port for test pattern transmission.
    Recommended usage:
    1. Set Disable Port and Port Quiet bits
    2. Set Test Pattern Rate for desired speed
    3. Clear Disable Port if device attached
    4. Load UTP registers and enable UTP, or enable PRBS
    """

    disable_port: bool = False
    port_quiet: bool = False
    lock_down_fe_preset: bool = False
    test_pattern_rate: TestPatternRate = TestPatternRate.RATE_2_5GT
    bypass_utp_alignment: int = 0  # 16-bit mask, 1 bit per lane
    port_select: int = 0           # 0-15

    def to_register(self, write_enable: bool = True) -> int:
        value = 0
        if self.disable_port:
            value |= _PortControlBits.DISABLE_PORT
        if self.port_quiet:
            value |= _PortControlBits.PORT_QUIET
        if self.lock_down_fe_preset:
            value |= _PortControlBits.LOCK_DOWN_FE_PRESET
        value |= (self.test_pattern_rate & 0x7) << 3
        value |= (self.bypass_utp_alignment & 0xFFFF) << 8
        value |= (self.port_select & 0xF) << 24
        if write_enable:
            value |= _PortControlBits.WRITE_ENABLE
        return value

    @classmethod
    def from_register(cls, value: int) -> PortControlRegister:
        return cls(
            disable_port=bool(value & _PortControlBits.DISABLE_PORT),
            port_quiet=bool(value & _PortControlBits.PORT_QUIET),
            lock_down_fe_preset=bool(value & _PortControlBits.LOCK_DOWN_FE_PRESET),
            test_pattern_rate=TestPatternRate((value >> 3) & 0x7),
            bypass_utp_alignment=(value >> 8) & 0xFFFF,
            port_select=(value >> 24) & 0xF,
        )


# ---------------------------------------------------------------------------
# PHY Command/Status Register (0x321C)
# ---------------------------------------------------------------------------

class PhyCmdStatusBits(IntFlag):
    """Physical Layer Command/Status Register bit definitions."""

    UPSTREAM_CROSSLINK_EN = 1 << 5
    DOWNSTREAM_CROSSLINK_EN = 1 << 6
    LANE_REVERSAL_DISABLE = 1 << 7
    LTSSM_WDT_DISABLE = 1 << 8
    LTSSM_WDT_DISABLE_WE = 1 << 9


@dataclass
class PhyCmdStatusRegister:
    """Physical Layer Command/Status Register (0x321C) field access.

    Contains station-wide physical layer configuration.
    """

    num_ports: int = 0                       # Read-only, bits [4:0]
    upstream_crosslink_enable: bool = True
    downstream_crosslink_enable: bool = True
    lane_reversal_disable: bool = False
    ltssm_wdt_disable: bool = False
    ltssm_wdt_port_select: int = 0           # bits [15:12]
    utp_kcode_flags: int = 0                 # bits [31:16], 1 bit per UTP byte

    def to_register(self, wdt_write_enable: bool = False) -> int:
        value = self.num_ports & 0x1F
        if self.upstream_crosslink_enable:
            value |= PhyCmdStatusBits.UPSTREAM_CROSSLINK_EN
        if self.downstream_crosslink_enable:
            value |= PhyCmdStatusBits.DOWNSTREAM_CROSSLINK_EN
        if self.lane_reversal_disable:
            value |= PhyCmdStatusBits.LANE_REVERSAL_DISABLE
        if self.ltssm_wdt_disable:
            value |= PhyCmdStatusBits.LTSSM_WDT_DISABLE
        if wdt_write_enable:
            value |= PhyCmdStatusBits.LTSSM_WDT_DISABLE_WE
        value |= (self.ltssm_wdt_port_select & 0xF) << 12
        value |= (self.utp_kcode_flags & 0xFFFF) << 16
        return value

    @classmethod
    def from_register(cls, value: int) -> PhyCmdStatusRegister:
        return cls(
            num_ports=value & 0x1F,
            upstream_crosslink_enable=bool(value & PhyCmdStatusBits.UPSTREAM_CROSSLINK_EN),
            downstream_crosslink_enable=bool(value & PhyCmdStatusBits.DOWNSTREAM_CROSSLINK_EN),
            lane_reversal_disable=bool(value & PhyCmdStatusBits.LANE_REVERSAL_DISABLE),
            ltssm_wdt_disable=bool(value & PhyCmdStatusBits.LTSSM_WDT_DISABLE),
            ltssm_wdt_port_select=(value >> 12) & 0xF,
            utp_kcode_flags=(value >> 16) & 0xFFFF,
        )


# ---------------------------------------------------------------------------
# SerDes Diagnostic Data Registers (per quad)
# ---------------------------------------------------------------------------

_QUAD_DIAG_OFFSETS = [
    VendorPhyRegs.SERDES_DIAG_QUAD0,
    VendorPhyRegs.SERDES_DIAG_QUAD1,
    VendorPhyRegs.SERDES_DIAG_QUAD2,
    VendorPhyRegs.SERDES_DIAG_QUAD3,
]


@dataclass
class SerDesDiagnosticRegister:
    """SerDes Diagnostic Data Register (per quad) field access.

    Each quad contains 4 lanes; use lane_select to choose which lane's data.
    """

    utp_expected_data: int = 0   # bits [7:0], RO
    utp_actual_data: int = 0     # bits [15:8], RO
    utp_error_count: int = 0     # bits [23:16], RO (saturates at 255)
    lane_select: int = 0         # bits [25:24], RW
    utp_sync: bool = False       # bit 31, RO

    @classmethod
    def from_register(cls, value: int) -> SerDesDiagnosticRegister:
        return cls(
            utp_expected_data=value & 0xFF,
            utp_actual_data=(value >> 8) & 0xFF,
            utp_error_count=(value >> 16) & 0xFF,
            lane_select=(value >> 24) & 0x3,
            utp_sync=bool(value & (1 << 31)),
        )

    def to_register(self, clear_error_count: bool = False) -> int:
        """Encode to register value. Only lane_select is writable."""
        value = (self.lane_select & 0x3) << 24
        if clear_error_count:
            value |= 1 << 26
        return value


# ---------------------------------------------------------------------------
# User Test Pattern (0x320C - 0x3218)
# ---------------------------------------------------------------------------

@dataclass
class UserTestPattern:
    """16-byte User Test Pattern for UTP transmission.

    Written to registers 0x320C-0x3218 (4 bytes each).
    For Gen1/Gen2, each byte can be marked as K-code.
    For Gen3+, data is sent as Data block with Sync Header 10b.
    """

    pattern: bytes

    def __post_init__(self) -> None:
        if len(self.pattern) != 16:
            raise ValueError("UTP pattern must be exactly 16 bytes")

    def to_registers(self) -> tuple[int, int, int, int]:
        """Convert to four 32-bit register values."""
        return (
            int.from_bytes(self.pattern[0:4], "little"),
            int.from_bytes(self.pattern[4:8], "little"),
            int.from_bytes(self.pattern[8:12], "little"),
            int.from_bytes(self.pattern[12:16], "little"),
        )

    @classmethod
    def from_registers(cls, reg0: int, reg1: int, reg2: int, reg3: int) -> UserTestPattern:
        pattern = (
            reg0.to_bytes(4, "little")
            + reg1.to_bytes(4, "little")
            + reg2.to_bytes(4, "little")
            + reg3.to_bytes(4, "little")
        )
        return cls(pattern=pattern)

    @classmethod
    def prbs7(cls) -> UserTestPattern:
        """PRBS-7 approximation pattern (x^7 + x^6 + 1, 127-bit period)."""
        return cls(pattern=bytes([
            0x7F, 0xBF, 0xDF, 0xEF, 0xF7, 0xFB, 0xFD, 0x7E,
            0xBF, 0x5F, 0xAF, 0xD7, 0xEB, 0xF5, 0xFA, 0x7D,
        ]))

    @classmethod
    def prbs15(cls) -> UserTestPattern:
        """PRBS-15 approximation pattern (x^15 + x^14 + 1)."""
        return cls(pattern=bytes([
            0x00, 0x00, 0x7F, 0xFF, 0x80, 0x00, 0x3F, 0xFF,
            0xC0, 0x00, 0x1F, 0xFF, 0xE0, 0x00, 0x0F, 0xFF,
        ]))

    @classmethod
    def prbs31(cls) -> UserTestPattern:
        """PRBS-31 approximation pattern (x^31 + x^28 + 1)."""
        return cls(pattern=bytes([
            0x7F, 0xFF, 0xFF, 0xFF, 0x80, 0x00, 0x00, 0x07,
            0xFF, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0x3F, 0xFF,
        ]))

    @classmethod
    def alternating(cls) -> UserTestPattern:
        """Alternating 0xAA/0x55 pattern (clock-like)."""
        return cls(pattern=bytes([0xAA, 0x55] * 8))

    @classmethod
    def walking_ones(cls) -> UserTestPattern:
        """Walking ones pattern."""
        return cls(pattern=bytes([
            0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80,
            0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80,
        ]))

    @classmethod
    def all_zeros(cls) -> UserTestPattern:
        return cls(pattern=bytes(16))

    @classmethod
    def all_ones(cls) -> UserTestPattern:
        return cls(pattern=bytes([0xFF] * 16))


# ---------------------------------------------------------------------------
# UTP Test Result
# ---------------------------------------------------------------------------

@dataclass
class UTPTestResult:
    """Results from a User Test Pattern test run."""

    lane: int
    synced: bool
    error_count: int
    expected_on_error: int | None
    actual_on_error: int | None

    @property
    def passed(self) -> bool:
        return self.synced and self.error_count == 0

    @property
    def error_rate(self) -> str:
        if not self.synced:
            return "NO SYNC"
        if self.error_count == 0:
            return "PASS"
        if self.error_count == 255:
            return "FAIL (255+ errors)"
        return f"FAIL ({self.error_count} errors)"


# ---------------------------------------------------------------------------
# UTP Preset Registry
# ---------------------------------------------------------------------------

UTP_PRESETS: dict[str, type[UserTestPattern]] = {}
"""Registry of named UTP presets, populated after class definition."""


def _build_utp_presets() -> dict[str, UserTestPattern]:
    """Build the preset lookup table mapping names to factory-produced patterns."""
    return {
        "prbs7": UserTestPattern.prbs7(),
        "prbs15": UserTestPattern.prbs15(),
        "prbs31": UserTestPattern.prbs31(),
        "alternating": UserTestPattern.alternating(),
        "walking_ones": UserTestPattern.walking_ones(),
        "zeros": UserTestPattern.all_zeros(),
        "ones": UserTestPattern.all_ones(),
    }


def get_utp_preset(name: str) -> UserTestPattern:
    """Look up a UTP preset by name.

    Args:
        name: Preset name (prbs7, prbs15, prbs31, alternating, walking_ones, zeros, ones).

    Returns:
        A fresh UserTestPattern instance.

    Raises:
        ValueError: If the preset name is unknown.
    """
    _factories = {
        "prbs7": UserTestPattern.prbs7,
        "prbs15": UserTestPattern.prbs15,
        "prbs31": UserTestPattern.prbs31,
        "alternating": UserTestPattern.alternating,
        "walking_ones": UserTestPattern.walking_ones,
        "zeros": UserTestPattern.all_zeros,
        "ones": UserTestPattern.all_ones,
    }
    factory = _factories.get(name)
    if factory is None:
        raise ValueError(f"Unknown UTP preset '{name}'. Options: {', '.join(_factories)}")
    return factory()


UTP_PRESET_NAMES: list[str] = ["prbs7", "prbs15", "prbs31", "alternating", "walking_ones", "zeros", "ones"]


# ---------------------------------------------------------------------------
# Quad Diagnostic Helpers
# ---------------------------------------------------------------------------

def get_quad_diag_offset(lane: int) -> tuple[int, int]:
    """Get the quad diagnostic register offset and lane select for a lane.

    Args:
        lane: Lane number (0-15).

    Returns:
        Tuple of (register_offset, lane_select_value).
    """
    if not 0 <= lane < 16:
        raise ValueError(f"Lane must be 0-15, got {lane}")
    quad = lane // 4
    lane_in_quad = lane % 4
    return (_QUAD_DIAG_OFFSETS[quad], lane_in_quad)


# ---------------------------------------------------------------------------
# Recovery Diagnostic Register (0x3BC4)
# ---------------------------------------------------------------------------

class _RecoveryDiagBits(IntFlag):
    """Recovery Diagnostic Register bit definitions."""

    LTSSM_STATUS_SELECT = 1 << 30   # 0=recovery count, 1=LTSSM state
    CLEAR_RECOVERY_COUNT = 1 << 31  # W1C


@dataclass
class RecoveryDiagnosticRegister:
    """Recovery Diagnostic Register (0x3BC4) field access.

    When ltssm_status_select=0, bits [15:0] = recovery entry count.
    When ltssm_status_select=1, bits [15:0] = current LTSSM state code.
    """

    data_value: int = 0              # bits [15:0], RO
    rx_evaluation_count: int = 0     # bits [21:16], RO
    port_select: int = 0             # bits [27:24], RW
    speed_select: int = 0            # bits [29:28], RW (0=Gen1..5=Gen6)
    ltssm_status_select: bool = False  # bit 30, RW

    def to_register(self, clear_recovery_count: bool = False) -> int:
        value = self.data_value & 0xFFFF
        value |= (self.rx_evaluation_count & 0x3F) << 16
        value |= (self.port_select & 0xF) << 24
        value |= (self.speed_select & 0x3) << 28
        if self.ltssm_status_select:
            value |= _RecoveryDiagBits.LTSSM_STATUS_SELECT
        if clear_recovery_count:
            value |= _RecoveryDiagBits.CLEAR_RECOVERY_COUNT
        return value

    @classmethod
    def from_register(cls, value: int) -> RecoveryDiagnosticRegister:
        return cls(
            data_value=value & 0xFFFF,
            rx_evaluation_count=(value >> 16) & 0x3F,
            port_select=(value >> 24) & 0xF,
            speed_select=(value >> 28) & 0x3,
            ltssm_status_select=bool(value & _RecoveryDiagBits.LTSSM_STATUS_SELECT),
        )


# ---------------------------------------------------------------------------
# PHY Additional Status Register (0x3254)
# ---------------------------------------------------------------------------

@dataclass
class PhyAdditionalStatusRegister:
    """PHY Additional Status Register (0x3254) field access.

    Provides link speed, link down count, and lane reversal status.
    """

    lane_reversal: bool = False      # bit 1, RO
    link_down_count: int = 0         # bits [7:3], RO
    link_speed: int = 0              # bits [10:8], RO (0=Gen1..5=Gen6)
    port_select: int = 0             # bits [15:12], RW

    def to_register(self) -> int:
        value = 0
        if self.lane_reversal:
            value |= 1 << 1
        value |= (self.link_down_count & 0x1F) << 3
        value |= (self.link_speed & 0x7) << 8
        value |= (self.port_select & 0xF) << 12
        return value

    @classmethod
    def from_register(cls, value: int) -> PhyAdditionalStatusRegister:
        return cls(
            lane_reversal=bool(value & (1 << 1)),
            link_down_count=(value >> 3) & 0x1F,
            link_speed=(value >> 8) & 0x7,
            port_select=(value >> 12) & 0xF,
        )


# ---------------------------------------------------------------------------
# LTSSM State Machine Register (0x3DAC)
# ---------------------------------------------------------------------------

@dataclass
class LtssmStateMachineRegister:
    """LTSSM State Machine Register (0x3DAC) field access.

    Provides detailed sub-state readback and override capability.
    """

    state_machine_select: int = 0    # bits [4:0], RW
    state_machine_value: int = 0     # bits [15:8], RO
    port_lane_select: int = 0        # bits [19:16], RW
    write_and_hold_enable: bool = False  # bit 25, RW

    def to_register(self, write_and_go: bool = False) -> int:
        value = self.state_machine_select & 0x1F
        value |= (self.state_machine_value & 0xFF) << 8
        value |= (self.port_lane_select & 0xF) << 16
        if write_and_go:
            value |= 1 << 24
        if self.write_and_hold_enable:
            value |= 1 << 25
        return value

    @classmethod
    def from_register(cls, value: int) -> LtssmStateMachineRegister:
        return cls(
            state_machine_select=value & 0x1F,
            state_machine_value=(value >> 8) & 0xFF,
            port_lane_select=(value >> 16) & 0xF,
            write_and_hold_enable=bool(value & (1 << 25)),
        )


# ---------------------------------------------------------------------------
# Ptrace Capture Control Register (0x4000)
# ---------------------------------------------------------------------------

class _PtraceCaptureControlBits(IntFlag):
    """Ptrace Capture Control Register bit definitions."""

    START_CAPTURE = 1 << 0
    STOP_CAPTURE = 1 << 1
    CLEAR_BUFFER = 1 << 2


@dataclass
class PtraceCaptureControlRegister:
    """Ptrace Capture Control Register (0x4000) field access."""

    start_capture: bool = False
    stop_capture: bool = False
    clear_buffer: bool = False

    def to_register(self) -> int:
        value = 0
        if self.start_capture:
            value |= _PtraceCaptureControlBits.START_CAPTURE
        if self.stop_capture:
            value |= _PtraceCaptureControlBits.STOP_CAPTURE
        if self.clear_buffer:
            value |= _PtraceCaptureControlBits.CLEAR_BUFFER
        return value

    @classmethod
    def from_register(cls, value: int) -> PtraceCaptureControlRegister:
        return cls(
            start_capture=bool(value & _PtraceCaptureControlBits.START_CAPTURE),
            stop_capture=bool(value & _PtraceCaptureControlBits.STOP_CAPTURE),
            clear_buffer=bool(value & _PtraceCaptureControlBits.CLEAR_BUFFER),
        )


# ---------------------------------------------------------------------------
# Ptrace Capture Status Register (0x4004)
# ---------------------------------------------------------------------------

@dataclass
class PtraceCaptureStatusRegister:
    """Ptrace Capture Status Register (0x4004) field access."""

    capture_active: bool = False     # bit 0, RO
    trigger_hit: bool = False        # bit 1, RO
    entries_captured: int = 0        # bits [15:2], RO

    @classmethod
    def from_register(cls, value: int) -> PtraceCaptureStatusRegister:
        return cls(
            capture_active=bool(value & (1 << 0)),
            trigger_hit=bool(value & (1 << 1)),
            entries_captured=(value >> 2) & 0x3FFF,
        )


# ---------------------------------------------------------------------------
# Ptrace Capture Config Register (0x4008)
# ---------------------------------------------------------------------------

@dataclass
class PtraceCaptureConfigRegister:
    """Ptrace Capture Config Register (0x4008) field access."""

    cap_port_select: int = 0         # bits [3:0]
    trace_point_select: int = 0      # bits [7:4]
    lane_select: int = 0             # bits [11:8]

    def to_register(self) -> int:
        value = self.cap_port_select & 0xF
        value |= (self.trace_point_select & 0xF) << 4
        value |= (self.lane_select & 0xF) << 8
        return value

    @classmethod
    def from_register(cls, value: int) -> PtraceCaptureConfigRegister:
        return cls(
            cap_port_select=value & 0xF,
            trace_point_select=(value >> 4) & 0xF,
            lane_select=(value >> 8) & 0xF,
        )


# ---------------------------------------------------------------------------
# Ptrace Trigger Condition Register (0x4038)
# ---------------------------------------------------------------------------

@dataclass
class PtraceTriggerCondRegister:
    """Ptrace Trigger Condition Register (0x4038) field access."""

    ltssm_enable: bool = False       # bit 0
    ltssm_state_match: int = 0       # bits [7:1]

    def to_register(self) -> int:
        value = 0
        if self.ltssm_enable:
            value |= 1 << 0
        value |= (self.ltssm_state_match & 0x7F) << 1
        return value

    @classmethod
    def from_register(cls, value: int) -> PtraceTriggerCondRegister:
        return cls(
            ltssm_enable=bool(value & (1 << 0)),
            ltssm_state_match=(value >> 1) & 0x7F,
        )
