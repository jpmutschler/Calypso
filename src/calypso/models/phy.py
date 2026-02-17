"""PCIe Physical Layer (SerDes) models and definitions.

All definitions conform to the PCI Express Base Specification Revision 6.0.1.

Key capabilities:
- Lane Margining at the Receiver (eye height/width measurement)
- TX/RX Equalization presets and coefficients
- Modulation mode (NRZ for Gen1-5, PAM4 for Gen6)
- Physical Layer extended capability status (16GT/32GT EQ phases)
- PRBS pattern testing configuration and results

Reference: PCIe Base Spec 6.0.1, Sections 4.2.3 (Equalization), 7.7.8 (Margining)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import IntEnum, IntFlag
from typing import NamedTuple


# ---------------------------------------------------------------------------
# Modulation Modes (PCIe Base Spec 6.0.1, Section 4.2)
# ---------------------------------------------------------------------------


class Modulation(IntEnum):
    """PCIe link modulation encoding."""

    NRZ = 0  # Non-Return-to-Zero (Gen1-5): 2.5-32 GT/s
    PAM4 = 1  # Pulse Amplitude Modulation 4-level (Gen6): 64 GT/s


class DataRate(IntEnum):
    """PCIe data rates (PCIe Base Spec 6.0.1, Table 4-2)."""

    RATE_2_5GT = 1  # Gen1: 2.5 GT/s, NRZ, 8b/10b
    RATE_5GT = 2  # Gen2: 5.0 GT/s, NRZ, 8b/10b
    RATE_8GT = 3  # Gen3: 8.0 GT/s, NRZ, 128b/130b
    RATE_16GT = 4  # Gen4: 16.0 GT/s, NRZ, 128b/130b
    RATE_32GT = 5  # Gen5: 32.0 GT/s, NRZ, 128b/130b
    RATE_64GT = 6  # Gen6: 64.0 GT/s, PAM4, 242B/256B FLIT

    @property
    def modulation(self) -> Modulation:
        return Modulation.PAM4 if self.value == 6 else Modulation.NRZ

    @property
    def gigatransfers(self) -> float:
        _rates = {1: 2.5, 2: 5.0, 3: 8.0, 4: 16.0, 5: 32.0, 6: 64.0}
        return _rates.get(self.value, 0.0)

    @property
    def encoding(self) -> str:
        if self.value <= 2:
            return "8b/10b"
        if self.value <= 5:
            return "128b/130b"
        return "242B/256B FLIT"


# ---------------------------------------------------------------------------
# TX Equalization Presets (PCIe Base Spec 6.0.1, Section 4.2.3)
# ---------------------------------------------------------------------------


class TxPreset(IntEnum):
    """Transmitter equalization preset values (P0-P10)."""

    P0 = 0x0
    P1 = 0x1
    P2 = 0x2
    P3 = 0x3
    P4 = 0x4
    P5 = 0x5
    P6 = 0x6
    P7 = 0x7
    P8 = 0x8
    P9 = 0x9
    P10 = 0xA


@dataclass
class TxCoefficients:
    """TX equalizer 3-tap FIR coefficients (PCIe Base Spec 6.0.1, Section 4.2.3.3)."""

    pre_cursor: int  # c-1 coefficient (0-63 typical)
    cursor: int  # c0 coefficient (main tap)
    post_cursor: int  # c+1 coefficient (0-63 typical)
    preset: TxPreset | None = None

    @property
    def preshoot_ratio(self) -> float:
        if self.cursor == 0:
            return 0.0
        return self.pre_cursor / self.cursor

    @property
    def de_emphasis_ratio(self) -> float:
        if self.cursor == 0:
            return 0.0
        return self.post_cursor / self.cursor

    @property
    def de_emphasis_db(self) -> float:
        ratio = self.de_emphasis_ratio
        if ratio <= 0:
            return 0.0
        if ratio >= 1:
            return float("inf")
        return 20 * math.log10((1 + ratio) / (1 - ratio))


# Standard TX preset coefficients for 8.0 GT/s (Gen3)
# Reference: PCIe Base Spec 6.0.1, Table 4-15
TX_PRESETS_8GT: dict[TxPreset, TxCoefficients] = {
    TxPreset.P0: TxCoefficients(0, 50, 0, TxPreset.P0),
    TxPreset.P1: TxCoefficients(0, 47, 3, TxPreset.P1),
    TxPreset.P2: TxCoefficients(0, 44, 6, TxPreset.P2),
    TxPreset.P3: TxCoefficients(0, 42, 8, TxPreset.P3),
    TxPreset.P4: TxCoefficients(0, 40, 10, TxPreset.P4),
    TxPreset.P5: TxCoefficients(2, 45, 3, TxPreset.P5),
    TxPreset.P6: TxCoefficients(3, 44, 3, TxPreset.P6),
    TxPreset.P7: TxCoefficients(1, 47, 2, TxPreset.P7),
    TxPreset.P8: TxCoefficients(2, 46, 2, TxPreset.P8),
    TxPreset.P9: TxCoefficients(3, 45, 2, TxPreset.P9),
    TxPreset.P10: TxCoefficients(0, 48, 2, TxPreset.P10),
}


# ---------------------------------------------------------------------------
# RX Equalization Hints (PCIe Base Spec 6.0.1, Section 4.2.3.4)
# ---------------------------------------------------------------------------


class RxPresetHint(IntEnum):
    """Receiver equalization preset hints (Table 4-19)."""

    MINUS_6DB = 0x0
    MINUS_7DB = 0x1
    MINUS_8DB = 0x2
    MINUS_9DB = 0x3
    MINUS_10DB = 0x4
    MINUS_11DB = 0x5
    MINUS_12DB = 0x6
    RESERVED = 0x7


class CtleBoost(IntEnum):
    """CTLE (Continuous Time Linear Equalizer) boost settings."""

    OFF = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    VERY_HIGH = 4
    MAX = 5


# ---------------------------------------------------------------------------
# Lane Margining at the Receiver (PCIe Base Spec 6.0.1, Section 7.7.8)
# ---------------------------------------------------------------------------


class LaneMarginingCap(IntEnum):
    """Lane Margining Extended Capability register offsets."""

    CAP_HEADER = 0x00
    PORT_CAP = 0x04
    PORT_STATUS = 0x06
    LANE_CONTROL_BASE = 0x08  # Lane N Control at 0x08 + (N * 4)
    LANE_STATUS_BASE = 0x0A  # Lane N Status at 0x0A + (N * 4)


class MarginingCapBits(IntFlag):
    """Port Margining Capabilities register bits (Section 7.7.8.2)."""

    USES_DRIVER_SOFTWARE = 1 << 0
    MARGINING_READY = 1 << 16  # In status register


class MarginingCmd(IntEnum):
    """Lane Margining command types (Table 7-51)."""

    NO_COMMAND = 0x0
    ACCESS_RECEIVER_MARGIN_CONTROL = 0x1
    MARGIN_TIMING = 0x3
    MARGIN_VOLTAGE = 0x4
    VENDOR_DEFINED_1 = 0x5
    VENDOR_DEFINED_2 = 0x6
    GO_TO_NORMAL_SETTINGS = 0x7


class MarginingReceiverNumber(IntEnum):
    """Receiver number for margining commands (Section 7.7.8.4).

    Per PCIe 6.0.1 Table 7-51:
    - 000b: Default receiver at NRZ speeds (Gen1-5). RESERVED at 64 GT/s.
    - 001b-011b: Individual PAM4 receivers (valid at all margining speeds).
    - 111b: Broadcast to all receivers (valid at 64 GT/s only).
    """

    BROADCAST = 0x0  # NRZ default receiver. RESERVED at 64 GT/s (Gen6).
    RECEIVER_A = 0x1  # PAM4 upper eye (Rx-a)
    RECEIVER_B = 0x2  # PAM4 middle eye (Rx-b)
    RECEIVER_C = 0x3  # PAM4 lower eye (Rx-c)
    PAM4_BROADCAST = 0x7  # Broadcast to all PAM4 receivers (64 GT/s only)


# PAM4 receiver-to-eye mapping for 3-eye margining (Gen6)
PAM4_RECEIVERS: tuple[MarginingReceiverNumber, ...] = (
    MarginingReceiverNumber.RECEIVER_A,  # upper eye
    MarginingReceiverNumber.RECEIVER_B,  # middle eye
    MarginingReceiverNumber.RECEIVER_C,  # lower eye
)
PAM4_EYE_LABELS: tuple[str, ...] = ("upper", "middle", "lower")


class MarginingReportPayload(IntEnum):
    """Payload values for ACCESS_RECEIVER_MARGIN_CONTROL report commands.

    Per PCIe 6.0.1 Section 7.7.8, capabilities are obtained by sending
    margin_type=001b commands with these payload values, then reading
    the response from the Lane Status register.
    """

    CAPABILITIES = 0x88
    NUM_VOLTAGE_STEPS = 0x89
    NUM_TIMING_STEPS = 0x8A
    MAX_TIMING_OFFSET = 0x8B
    MAX_VOLTAGE_OFFSET = 0x8C
    SAMPLING_RATE_VOLTAGE = 0x8D
    SAMPLING_RATE_TIMING = 0x8E
    SAMPLE_COUNT = 0x8F
    MAX_LANES = 0x90


@dataclass
class MarginingLaneControl:
    """Lane Margining Control register fields (Section 7.7.8.4)."""

    receiver_number: MarginingReceiverNumber
    margin_type: MarginingCmd
    usage_model: int
    margin_payload: int

    def to_register(self) -> int:
        return (
            (self.receiver_number & 0x7)
            | ((self.margin_type & 0x7) << 3)
            | ((self.usage_model & 0x1) << 6)
            | ((self.margin_payload & 0xFF) << 8)
        )

    @classmethod
    def from_register(cls, value: int) -> MarginingLaneControl:
        return cls(
            receiver_number=MarginingReceiverNumber(value & 0x7),
            margin_type=MarginingCmd((value >> 3) & 0x7),
            usage_model=(value >> 6) & 0x1,
            margin_payload=(value >> 8) & 0xFF,
        )


@dataclass
class MarginingLaneStatus:
    """Lane Margining Status register fields (Section 7.7.8.5)."""

    receiver_number: MarginingReceiverNumber
    margin_type: MarginingCmd
    usage_model: int
    margin_payload: int

    @property
    def status_code(self) -> int:
        return (self.margin_payload >> 6) & 0x3

    @property
    def margin_value(self) -> int:
        return self.margin_payload & 0x3F

    @property
    def is_complete(self) -> bool:
        return self.status_code == 0x3

    @property
    def is_in_progress(self) -> bool:
        return self.status_code == 0x1

    @classmethod
    def from_register(cls, value: int) -> MarginingLaneStatus:
        return cls(
            receiver_number=MarginingReceiverNumber(value & 0x7),
            margin_type=MarginingCmd((value >> 3) & 0x7),
            usage_model=(value >> 6) & 0x1,
            margin_payload=(value >> 8) & 0xFF,
        )


# ---------------------------------------------------------------------------
# Eye Diagram Measurements
# ---------------------------------------------------------------------------


class EyeMeasurement(NamedTuple):
    """Eye diagram measurement results from lane margining."""

    lane: int
    eye_height_steps: int
    eye_width_steps: int
    eye_height_mv: float
    eye_width_ui: float
    ber_target: float


@dataclass
class LaneMarginCapabilities:
    """Per-lane margining capability information (Section 7.7.8)."""

    max_timing_offset: int
    max_voltage_offset: int
    num_timing_steps: int
    num_voltage_steps: int
    sample_count: int
    sample_rate_voltage: bool
    sample_rate_timing: bool
    ind_up_down_voltage: bool
    ind_left_right_timing: bool


# ---------------------------------------------------------------------------
# Physical Layer 16 GT/s Extended Capability (Section 7.7.5)
# ---------------------------------------------------------------------------


class PhysLayer16GT(IntEnum):
    """PCIe 4.0 (16 GT/s) Physical Layer Extended Capability offsets."""

    CAP_HEADER = 0x00
    CAPABILITIES = 0x04
    CONTROL = 0x08
    STATUS = 0x0C
    LOCAL_DATA_PARITY_STATUS = 0x10
    FIRST_RETIMER_DATA_PARITY = 0x14
    SECOND_RETIMER_DATA_PARITY = 0x18
    LANE_EQ_CTL_BASE = 0x20


class PhysLayer16GTCtlBits(IntFlag):
    """16 GT/s Control register bits (Section 7.7.5.4)."""

    TARGET_LINK_SPEED_OVERRIDE = 1 << 0


class PhysLayer16GTStsBits(IntFlag):
    """16 GT/s Status register bits (Section 7.7.5.5)."""

    EQ_16GT_COMPLETE = 1 << 0
    EQ_16GT_PHASE1_SUCCESS = 1 << 1
    EQ_16GT_PHASE2_SUCCESS = 1 << 2
    EQ_16GT_PHASE3_SUCCESS = 1 << 3
    LINK_EQ_REQ_16GT = 1 << 4


# ---------------------------------------------------------------------------
# Physical Layer 32 GT/s Extended Capability (Section 7.7.6)
# ---------------------------------------------------------------------------


class PhysLayer32GT(IntEnum):
    """PCIe 5.0 (32 GT/s) Physical Layer Extended Capability offsets."""

    CAP_HEADER = 0x00
    CAPABILITIES = 0x04
    CONTROL = 0x08
    STATUS = 0x0C


class PhysLayer32GTCapBits(IntFlag):
    """32 GT/s Capabilities register bits (Section 7.7.6.3)."""

    EQ_BYPASS_TO_HIGHEST = 1 << 0
    NO_EQ_NEEDED = 1 << 1
    MOD_TS_MODE1_SUPPORTED = 1 << 8
    MOD_TS_MODE2_SUPPORTED = 1 << 9


class PhysLayer32GTStsBits(IntFlag):
    """32 GT/s Status register bits (Section 7.7.6.5)."""

    EQ_32GT_COMPLETE = 1 << 0
    EQ_32GT_PHASE1_SUCCESS = 1 << 1
    EQ_32GT_PHASE2_SUCCESS = 1 << 2
    EQ_32GT_PHASE3_SUCCESS = 1 << 3
    LINK_EQ_REQ_32GT = 1 << 4
    MOD_TS_RECEIVED = 1 << 5
    RX_LANE_MARGIN_CAPABLE = 1 << 6
    RX_LANE_MARGIN_STATUS = 1 << 7


# ---------------------------------------------------------------------------
# Lane Equalization Control (Section 7.7.5.7, 7.7.6.6, 7.7.7.6)
# ---------------------------------------------------------------------------


@dataclass
class LaneEqualizationControl:
    """Per-lane equalization control settings."""

    lane: int
    downstream_tx_preset: TxPreset
    downstream_rx_hint: RxPresetHint
    upstream_tx_preset: TxPreset
    upstream_rx_hint: RxPresetHint

    @classmethod
    def from_register(cls, lane: int, value: int) -> LaneEqualizationControl:
        return cls(
            lane=lane,
            downstream_tx_preset=TxPreset(value & 0xF),
            downstream_rx_hint=RxPresetHint((value >> 4) & 0x7),
            upstream_tx_preset=TxPreset((value >> 8) & 0xF),
            upstream_rx_hint=RxPresetHint((value >> 12) & 0x7),
        )

    def to_register(self) -> int:
        return (
            (self.downstream_tx_preset & 0xF)
            | ((self.downstream_rx_hint & 0x7) << 4)
            | ((self.upstream_tx_preset & 0xF) << 8)
            | ((self.upstream_rx_hint & 0x7) << 12)
        )


# ---------------------------------------------------------------------------
# SerDes Lane Status
# ---------------------------------------------------------------------------


@dataclass
class SerDesLaneStatus:
    """Comprehensive SerDes lane status combining multiple register sources."""

    lane: int
    data_rate: DataRate
    modulation: Modulation
    tx_preset: TxPreset
    tx_coefficients: TxCoefficients | None
    rx_hint: RxPresetHint
    eye_height_mv: float | None = None
    eye_width_ui: float | None = None
    receiver_detected: bool = False
    electrical_idle: bool = False
    eq_complete: bool = False

    @property
    def is_pam4(self) -> bool:
        return self.modulation == Modulation.PAM4


# ---------------------------------------------------------------------------
# PAM4 Specific Definitions (Gen6)
# ---------------------------------------------------------------------------


class PAM4Level(IntEnum):
    """PAM4 voltage levels (4 amplitude levels, 2 bits per symbol)."""

    LEVEL_0 = 0
    LEVEL_1 = 1
    LEVEL_2 = 2
    LEVEL_3 = 3


class PAM4EyeType(IntEnum):
    """PAM4 has three eyes stacked vertically."""

    LOWER_EYE = 0  # Between Level 0 and Level 1
    MIDDLE_EYE = 1  # Between Level 1 and Level 2
    UPPER_EYE = 2  # Between Level 2 and Level 3


@dataclass
class PAM4EyeHeights:
    """Eye heights for all three PAM4 eyes."""

    lower_eye_mv: float
    middle_eye_mv: float
    upper_eye_mv: float

    @property
    def worst_case_mv(self) -> float:
        return min(self.lower_eye_mv, self.middle_eye_mv, self.upper_eye_mv)

    @property
    def is_balanced(self) -> bool:
        avg = (self.lower_eye_mv + self.middle_eye_mv + self.upper_eye_mv) / 3
        if avg == 0:
            return True
        return all(
            abs(eye - avg) / avg <= 0.2
            for eye in [self.lower_eye_mv, self.middle_eye_mv, self.upper_eye_mv]
        )


# ---------------------------------------------------------------------------
# Extended Capability IDs for PHY layers
# ---------------------------------------------------------------------------

PHY_LAYER_EXT_CAP_IDS: dict[int, str] = {
    0x0026: "Physical Layer 16 GT/s",
    0x0027: "Lane Margining at Receiver",
    0x002A: "Physical Layer 32 GT/s",
    0x0031: "Physical Layer 64 GT/s",
}


# ---------------------------------------------------------------------------
# PRBS Testing (Pseudo-Random Bit Sequence)
# ---------------------------------------------------------------------------


class PRBSOption(IntEnum):
    """PRBS operation mode."""

    GENERATE = 1  # Generate PRBS on TX
    CHECK = 2  # Check PRBS on RX


class PRBSPattern(IntEnum):
    """PRBS polynomial pattern types."""

    PRBS7 = 0  # x^7 + x^6 + 1, period 127
    PRBS9 = 1  # x^9 + x^5 + 1, period 511
    PRBS11 = 2  # x^11 + x^9 + 1, period 2047
    PRBS15 = 3  # x^15 + x^14 + 1, period 32767
    PRBS23 = 4  # x^23 + x^18 + 1, period 8388607
    PRBS31 = 5  # x^31 + x^28 + 1, period 2147483647
    PRBS58 = 6  # For PAM4/Gen6 testing
    PRBS49 = 7  # For PAM4/Gen6 testing
    PRBS20 = 8  # x^20 + x^3 + 1
    PRBS10 = 9  # x^10 + x^7 + 1
    PRBS13 = 10  # x^13 + x^12 + x^2 + x + 1


class PRBSRate(IntEnum):
    """PRBS test rate selection (1-indexed to match CLI convention)."""

    RATE_2_5G = 1
    RATE_5G = 2
    RATE_8G = 3
    RATE_16G = 4
    RATE_32G = 5
    RATE_64G = 6

    @property
    def gigatransfers(self) -> float:
        _rates = {1: 2.5, 2: 5.0, 3: 8.0, 4: 16.0, 5: 32.0, 6: 64.0}
        return _rates.get(self.value, 0.0)

    @property
    def is_pam4(self) -> bool:
        return self.value == 6


@dataclass
class PRBSConfig:
    """PRBS test configuration."""

    option: PRBSOption
    lane: int
    pattern: PRBSPattern
    rate: PRBSRate
    sample_count: int | None = None
    infinite: bool = False
    wait_time_ms: int = 100
    invert_polarity: bool = False
    counter: int = 1

    def get_sample_count_parts(self) -> tuple[int, int, int]:
        """Split sample_count into (LSB, MID, MSB) 16-bit parts."""
        if self.sample_count is None:
            return (0, 0, 0)
        count = self.sample_count & 0xFFFFFFFFFFFF
        return (count & 0xFFFF, (count >> 16) & 0xFFFF, (count >> 32) & 0xFFFF)


@dataclass
class PRBSResult:
    """Results from a PRBS test."""

    lane: int
    pattern: PRBSPattern
    rate: PRBSRate
    locked: bool
    error_count: int
    total_bits: int

    @property
    def bit_error_rate(self) -> float:
        if self.total_bits == 0:
            return 0.0
        return self.error_count / self.total_bits

    @property
    def ber_string(self) -> str:
        if not self.locked:
            return "NO LOCK"
        if self.error_count == 0:
            return "0 errors"
        ber = self.bit_error_rate
        if ber < 1e-15:
            return f"{self.error_count} errors (BER < 1e-15)"
        return f"{self.error_count} errors (BER: {ber:.2e})"

    @property
    def passed(self) -> bool:
        return self.locked and self.error_count == 0


# PRBS pattern descriptions
PRBS_PATTERN_INFO: dict[PRBSPattern, dict[str, str | int]] = {
    PRBSPattern.PRBS7: {
        "polynomial": "x^7 + x^6 + 1",
        "period": 127,
        "use_case": "Short pattern, quick tests",
    },
    PRBSPattern.PRBS9: {
        "polynomial": "x^9 + x^5 + 1",
        "period": 511,
        "use_case": "General testing",
    },
    PRBSPattern.PRBS11: {
        "polynomial": "x^11 + x^9 + 1",
        "period": 2047,
        "use_case": "General testing",
    },
    PRBSPattern.PRBS15: {
        "polynomial": "x^15 + x^14 + 1",
        "period": 32767,
        "use_case": "Standard compliance testing",
    },
    PRBSPattern.PRBS23: {
        "polynomial": "x^23 + x^18 + 1",
        "period": 8388607,
        "use_case": "Long pattern testing",
    },
    PRBSPattern.PRBS31: {
        "polynomial": "x^31 + x^28 + 1",
        "period": 2147483647,
        "use_case": "Stress testing, BER measurements",
    },
    PRBSPattern.PRBS58: {
        "polynomial": "PAM4 specific",
        "period": 0,
        "use_case": "Gen6 PAM4 testing",
    },
    PRBSPattern.PRBS49: {
        "polynomial": "PAM4 specific",
        "period": 0,
        "use_case": "Gen6 PAM4 testing",
    },
    PRBSPattern.PRBS20: {
        "polynomial": "x^20 + x^3 + 1",
        "period": 1048575,
        "use_case": "Extended testing",
    },
    PRBSPattern.PRBS10: {
        "polynomial": "x^10 + x^7 + 1",
        "period": 1023,
        "use_case": "General testing",
    },
    PRBSPattern.PRBS13: {
        "polynomial": "x^13 + x^12 + x^2 + x + 1",
        "period": 8191,
        "use_case": "O.150 compliance",
    },
}


# ---------------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------------


def get_modulation_for_speed(speed: int) -> Modulation:
    """Determine modulation type from link speed code (1-6)."""
    return Modulation.PAM4 if speed >= 6 else Modulation.NRZ


def calculate_lane_margining_offset(lane: int, base_offset: int) -> int:
    """Calculate register offset for a specific lane's margining registers."""
    return base_offset + (lane * 4)


def steps_to_voltage_mv(steps: int, max_steps: int, max_mv: float = 500.0) -> float:
    """Convert margining voltage steps to millivolts."""
    if max_steps == 0:
        return 0.0
    return (steps / max_steps) * max_mv


def steps_to_timing_ui(steps: int, max_steps: int) -> float:
    """Convert margining timing steps to Unit Intervals (max 0.5 UI)."""
    if max_steps == 0:
        return 0.0
    return (steps / max_steps) * 0.5


def ui_to_picoseconds(ui: float, data_rate: DataRate) -> float:
    """Convert Unit Intervals to picoseconds."""
    gt_per_sec = data_rate.gigatransfers
    if gt_per_sec == 0:
        return 0.0
    ui_in_ps = 1e12 / (gt_per_sec * 1e9)
    return ui * ui_in_ps
