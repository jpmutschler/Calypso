"""Atlas3 PTrace (Protocol Trace) register definitions.

PTrace is the embedded protocol analyser built into every Atlas3 station.
It captures TLP headers/payloads, DLLPs, and ordered sets at ingress and
egress, with hardware triggering, filtering, and a 600-bit-wide trace
buffer (up to 4096 rows per direction).

Register offsets are relative to a *direction base* within the station:
    ingress_base = station_register_base(port) + 0x4000
    egress_base  = station_register_base(port) + 0x5000

Reference: RD101 / RM102 Atlas3 PTrace register specification.

Note: Register offsets are now in ``ptrace_layout.py`` as variant-aware
``PTraceRegLayout`` instances. This file retains direction constants,
address helpers, bitfield dataclasses, and enums.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, IntFlag


# ---------------------------------------------------------------------------
# Direction
# ---------------------------------------------------------------------------


class PTraceDir(IntEnum):
    """Direction base offset relative to station register base."""

    INGRESS = 0x4000
    EGRESS = 0x5000


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TBUF_ROW_DWORDS = 19  # 19 x 32 = 608 bits (600 data + 8 reserved)
TBUF_MAX_ROWS = 4096
FILTER_DWORDS = 16  # 512 bits = 16 DWORDs per filter half
DATA_BLOCK_DWORDS = 16  # 512 bits = 16 DWORDs per condition data block


# ---------------------------------------------------------------------------
# Address helpers
# ---------------------------------------------------------------------------


def ptrace_addr(station_base: int, direction: PTraceDir, offset: int) -> int:
    """Compute absolute BAR 0 offset for a PTrace register.

    Args:
        station_base: Station register base (from ``station_register_base()``).
        direction: Ingress or egress direction base.
        offset: Register offset within the direction block (from layout).

    Returns:
        Absolute 32-bit BAR 0 offset.
    """
    return station_base + int(direction) + offset


def tbuf_data_offset(tbuf_data_base: int, dword_index: int) -> int:
    """Return the register offset for trace buffer data DWORD *dword_index*.

    Args:
        tbuf_data_base: Base offset of TBUF_DATA from layout (typically 0x188).
        dword_index: 0..18 (19 DWORDs per row).

    Returns:
        Register offset relative to direction base.
    """
    if not 0 <= dword_index < TBUF_ROW_DWORDS:
        raise ValueError(f"dword_index must be 0..{TBUF_ROW_DWORDS - 1}, got {dword_index}")
    return tbuf_data_base + (dword_index * 4)


# ---------------------------------------------------------------------------
# Enums — Trigger Source IDs (RD101 p261)
# ---------------------------------------------------------------------------


class TriggerSrcId(IntEnum):
    """Trigger source identifiers (TriggerSrcSel field, 6-bit)."""

    MANUAL = 0x00
    COND0 = 0x01
    COND1 = 0x02
    COND0_AND_COND1 = 0x03
    COND0_OR_COND1 = 0x04
    COND0_XOR_COND1 = 0x05
    COND0_THEN_COND1 = 0x06
    EVENT_COUNTER_THRESHOLD = 0x07
    TRIGGERIN_OR = 0x08
    COND0_THEN_DELAY = 0x09
    PORT_ERROR = 0x3D


class FlitMatchSel(IntEnum):
    """Flit mode match selection (3-bit field in TriggerConfig/FilterControl)."""

    MATCH_ALL = 0
    MATCH_DW1 = 1
    MATCH_DW1_4 = 2
    MATCH_DW1_8 = 3
    MATCH_DW1_12 = 4
    MATCH_DW1_16 = 5
    MATCH_H_SLOT = 6
    MATCH_H_OR_G = 7


class FilterSrcSel(IntEnum):
    """Filter source selection (3-bit field in FilterControl)."""

    FILTER0_ONLY = 0
    FILTER1_ONLY = 1
    FILTER0_OR_1 = 2
    NOT_FILTER0 = 4
    NOT_FILTER1 = 5
    NOT_FILTER0_OR_1 = 6


# ---------------------------------------------------------------------------
# Capture Control Register (+0x000)
# ---------------------------------------------------------------------------


@dataclass
class CaptureControlReg:
    """PTrace Capture Control Register (+0x000).

    Bitfields:
        [0]   PTraceEnable -- master enable for the analyzer
        [8]   CaptureStart -- start capture (self-clearing)
        [9]   ManCaptureStop -- stop capture
        [16]  ClearTriggered -- W1C, must keep PTraceEnable=1
    """

    ptrace_enable: bool = False
    capture_start: bool = False
    man_capture_stop: bool = False
    clear_triggered: bool = False

    def to_register(self) -> int:
        value = 0
        if self.ptrace_enable:
            value |= 1 << 0
        if self.capture_start:
            value |= 1 << 8
        if self.man_capture_stop:
            value |= 1 << 9
        if self.clear_triggered:
            value |= 1 << 16
        return value

    @classmethod
    def from_register(cls, value: int) -> CaptureControlReg:
        return cls(
            ptrace_enable=bool(value & (1 << 0)),
            capture_start=bool(value & (1 << 8)),
            man_capture_stop=bool(value & (1 << 9)),
            clear_triggered=bool(value & (1 << 16)),
        )


# ---------------------------------------------------------------------------
# Capture Status Register (+0x004)
# ---------------------------------------------------------------------------


@dataclass
class CaptureStatusReg:
    """PTrace Capture Status Register (+0x004).

    Bitfields:
        [0]      CaptureInProgress
        [8]      Triggered
        [9]      TBufWrapped -- trace buffer has wrapped
        [27:16]  CompressCnt -- number of compressed entries
        [31]     RAMInitDone -- trace buffer RAM initialization complete
    """

    capture_in_progress: bool = False
    triggered: bool = False
    tbuf_wrapped: bool = False
    compress_cnt: int = 0
    ram_init_done: bool = False

    @classmethod
    def from_register(cls, value: int) -> CaptureStatusReg:
        return cls(
            capture_in_progress=bool(value & (1 << 0)),
            triggered=bool(value & (1 << 8)),
            tbuf_wrapped=bool(value & (1 << 9)),
            compress_cnt=(value >> 16) & 0xFFF,
            ram_init_done=bool(value & (1 << 31)),
        )


# ---------------------------------------------------------------------------
# Capture Config Register (+0x008)
# ---------------------------------------------------------------------------


@dataclass
class CaptureConfigReg:
    """PTrace Capture Config Register (+0x008).

    Bitfields:
        [0]     TrigOutMask -- mask external trigger output
        [1]     FilterEn -- enable capture filtering
        [2]     CompressEn -- enable compression
        [3]     NopFilt -- filter NOP ordered sets
        [4]     IdleFilt -- filter IDLE DLLPs
        [5]     DataCap -- capture data payloads (vs headers only)
        [6]     RawFilt -- raw symbol filter
        [11:8]  CapPortSel -- port select within station (0-15)
        [13:12] TracePointSel -- 0=Accum/Distrib, 1=Unscram/OSGen,
                                 2=Deskew/Scram, 3=Scrambled
        [19:16] LaneSel -- lane select (0-15)
    """

    trig_out_mask: bool = False
    filter_en: bool = False
    compress_en: bool = False
    nop_filt: bool = False
    idle_filt: bool = False
    data_cap: bool = False
    raw_filt: bool = False
    cap_port_sel: int = 0
    trace_point_sel: int = 0
    lane_sel: int = 0

    def to_register(self) -> int:
        value = 0
        if self.trig_out_mask:
            value |= 1 << 0
        if self.filter_en:
            value |= 1 << 1
        if self.compress_en:
            value |= 1 << 2
        if self.nop_filt:
            value |= 1 << 3
        if self.idle_filt:
            value |= 1 << 4
        if self.data_cap:
            value |= 1 << 5
        if self.raw_filt:
            value |= 1 << 6
        value |= (self.cap_port_sel & 0xF) << 8
        value |= (self.trace_point_sel & 0x3) << 12
        value |= (self.lane_sel & 0xF) << 16
        return value

    @classmethod
    def from_register(cls, value: int) -> CaptureConfigReg:
        return cls(
            trig_out_mask=bool(value & (1 << 0)),
            filter_en=bool(value & (1 << 1)),
            compress_en=bool(value & (1 << 2)),
            nop_filt=bool(value & (1 << 3)),
            idle_filt=bool(value & (1 << 4)),
            data_cap=bool(value & (1 << 5)),
            raw_filt=bool(value & (1 << 6)),
            cap_port_sel=(value >> 8) & 0xF,
            trace_point_sel=(value >> 12) & 0x3,
            lane_sel=(value >> 16) & 0xF,
        )


# ---------------------------------------------------------------------------
# Post-Trigger Config Register (+0x00C)
# ---------------------------------------------------------------------------


@dataclass
class PostTriggerCfgReg:
    """PTrace Post-Trigger Config Register (+0x00C).

    Bitfields:
        [15:0]   ClockCount -- post-trigger clock count
        [26:16]  CapCount -- post-trigger capture count
        [29:27]  ClockCntMult -- clock count multiplier (power of 2)
        [31:30]  CountType -- 0=disabled, 1=clock, 2=capture, 3=both
    """

    clock_count: int = 0
    cap_count: int = 0
    clock_cnt_mult: int = 0
    count_type: int = 0

    def to_register(self) -> int:
        value = self.clock_count & 0xFFFF
        value |= (self.cap_count & 0x7FF) << 16
        value |= (self.clock_cnt_mult & 0x7) << 27
        value |= (self.count_type & 0x3) << 30
        return value

    @classmethod
    def from_register(cls, value: int) -> PostTriggerCfgReg:
        return cls(
            clock_count=value & 0xFFFF,
            cap_count=(value >> 16) & 0x7FF,
            clock_cnt_mult=(value >> 27) & 0x7,
            count_type=(value >> 30) & 0x3,
        )


# ---------------------------------------------------------------------------
# Trigger Config Register — A0 (+0x020)
# ---------------------------------------------------------------------------


@dataclass
class TriggerConfigReg:
    """PTrace Trigger Config Register -- A0 layout (+0x020).

    Bitfields:
        [5:0]   TriggerSrcSel -- trigger source ID
        [6]     Cond0Inv -- invert condition 0 result
        [7]     Cond1Inv -- invert condition 1 result
        [26:24] TriggerMatchSel0 -- Flit match mode for condition 0 (3-bit)
        [30:28] TriggerMatchSel1 -- Flit match mode for condition 1 (3-bit)
    """

    trigger_src: int = 0
    cond0_inv: bool = False
    cond1_inv: bool = False
    trigger_match_sel0: int = 0
    trigger_match_sel1: int = 0

    def to_register(self) -> int:
        value = self.trigger_src & 0x3F
        if self.cond0_inv:
            value |= 1 << 6
        if self.cond1_inv:
            value |= 1 << 7
        value |= (self.trigger_match_sel0 & 0x7) << 24
        value |= (self.trigger_match_sel1 & 0x7) << 28
        return value

    @classmethod
    def from_register(cls, value: int) -> TriggerConfigReg:
        return cls(
            trigger_src=value & 0x3F,
            cond0_inv=bool(value & (1 << 6)),
            cond1_inv=bool(value & (1 << 7)),
            trigger_match_sel0=(value >> 24) & 0x7,
            trigger_match_sel1=(value >> 28) & 0x7,
        )


# ---------------------------------------------------------------------------
# Trigger Source Select Register — B0 (+0x020)
# ---------------------------------------------------------------------------


@dataclass
class TriggerSrcSelReg:
    """PTrace Trigger Source Select Register -- B0 layout (+0x020).

    Bitfields:
        [5:0]   TriggerSrc -- trigger source ID (0-63)
        [6]     ReArmEnable -- enable automatic re-arm after trigger
        [31:7]  ReArmTime -- re-arm delay (raw clock ticks)
    """

    trigger_src: int = 0
    rearm_enable: bool = False
    rearm_time: int = 0

    def to_register(self) -> int:
        value = self.trigger_src & 0x3F
        if self.rearm_enable:
            value |= 1 << 6
        value |= (self.rearm_time & 0x1FFFFFF) << 7
        return value

    @classmethod
    def from_register(cls, value: int) -> TriggerSrcSelReg:
        return cls(
            trigger_src=value & 0x3F,
            rearm_enable=bool(value & (1 << 6)),
            rearm_time=(value >> 7) & 0x1FFFFFF,
        )


# ---------------------------------------------------------------------------
# ReArm Time Register — A0 only (+0x024)
# ---------------------------------------------------------------------------


@dataclass
class RearmTimeReg:
    """PTrace ReArm Time Register -- A0 only (+0x024).

    Bitfields:
        [23:0]  ReArmTime -- re-arm delay in clock ticks
    """

    rearm_time: int = 0

    def to_register(self) -> int:
        return self.rearm_time & 0xFFFFFF

    @classmethod
    def from_register(cls, value: int) -> RearmTimeReg:
        return cls(rearm_time=value & 0xFFFFFF)


# ---------------------------------------------------------------------------
# Trigger Condition Enable Register
# ---------------------------------------------------------------------------

# Condition enable bit constants — use these instead of raw 0xFFFFFFFF to avoid
# setting undocumented bits that may enable unwanted 512-bit data block comparison.
COND_ENB_LINK_SPEED: int = 1 << 8
COND_ENB_DLLP_TYPE: int = 1 << 9
COND_ENB_OS_TYPE: int = 1 << 10
COND_ENB_SYMBOL0: int = 1 << 11
COND_ENB_SYMBOL1: int = 1 << 12
COND_ENB_SYMBOL2: int = 1 << 13
COND_ENB_SYMBOL3: int = 1 << 14
COND_ENB_SYMBOL4: int = 1 << 15
COND_ENB_SYMBOL5: int = 1 << 16
COND_ENB_SYMBOL6: int = 1 << 17
COND_ENB_SYMBOL7: int = 1 << 18
COND_ENB_SYMBOL8: int = 1 << 19
COND_ENB_SYMBOL9: int = 1 << 20
COND_ENB_LTSSM: int = 1 << 21
COND_ENB_LINK_WIDTH: int = 1 << 22
COND_ENB_ALL_SYMBOLS: int = sum(1 << i for i in range(11, 21))
COND_ENB_ALL_ATTRS: int = sum(1 << i for i in range(8, 23))


@dataclass
class TrigCondEnableReg:
    """PTrace Trigger Condition Enable / Invert Register.

    Used for Cond0 Enable/Invert and Cond1 Enable/Invert registers.

    Bitfields:
        [8]      LinkSpeedEnb
        [9]      DLLPTypeEnb
        [10]     OsTypeEnb
        [11]     Symbol0Enb
        [12]     Symbol1Enb
        [13]     Symbol2Enb
        [14]     Symbol3Enb
        [15]     Symbol4Enb
        [16]     Symbol5Enb
        [17]     Symbol6Enb
        [18]     Symbol7Enb
        [19]     Symbol8Enb
        [20]     Symbol9Enb
        [21]     LtssmEnb
        [22]     LinkWidthEnb
    """

    raw: int = 0

    def to_register(self) -> int:
        return self.raw & COND_ENB_ALL_ATTRS

    @classmethod
    def from_register(cls, value: int) -> TrigCondEnableReg:
        return cls(raw=value & COND_ENB_ALL_ATTRS)

    @property
    def link_speed_enb(self) -> bool:
        return bool(self.raw & (1 << 8))

    @property
    def dllp_type_enb(self) -> bool:
        return bool(self.raw & (1 << 9))

    @property
    def os_type_enb(self) -> bool:
        return bool(self.raw & (1 << 10))

    @property
    def ltssm_enb(self) -> bool:
        return bool(self.raw & (1 << 21))

    @property
    def link_width_enb(self) -> bool:
        return bool(self.raw & (1 << 22))


# ---------------------------------------------------------------------------
# Filter Control Register — A0 only (+0x030)
# ---------------------------------------------------------------------------


@dataclass
class FilterControlReg:
    """PTrace Filter Control Register -- A0 only (+0x030).

    Bitfields:
        [9]     DLLPTypeEnb
        [10]    OsTypeEnb
        [11]    CxlIoFilterEnb
        [12]    CxlCacheFilterEnb
        [13]    CxlMemFilterEnb
        [14]    Filter256BEnb
        [22:20] FilterSrcSel (3-bit)
        [26:24] FilterMatchSel0 (3-bit, Flit match mode)
        [30:28] FilterMatchSel1 (3-bit, Flit match mode)
    """

    dllp_type_enb: bool = False
    os_type_enb: bool = False
    cxl_io_filter_enb: bool = False
    cxl_cache_filter_enb: bool = False
    cxl_mem_filter_enb: bool = False
    filter_256b_enb: bool = False
    filter_src_sel: int = 0
    filter_match_sel0: int = 0
    filter_match_sel1: int = 0

    def to_register(self) -> int:
        value = 0
        if self.dllp_type_enb:
            value |= 1 << 9
        if self.os_type_enb:
            value |= 1 << 10
        if self.cxl_io_filter_enb:
            value |= 1 << 11
        if self.cxl_cache_filter_enb:
            value |= 1 << 12
        if self.cxl_mem_filter_enb:
            value |= 1 << 13
        if self.filter_256b_enb:
            value |= 1 << 14
        value |= (self.filter_src_sel & 0x7) << 20
        value |= (self.filter_match_sel0 & 0x7) << 24
        value |= (self.filter_match_sel1 & 0x7) << 28
        return value

    @classmethod
    def from_register(cls, value: int) -> FilterControlReg:
        return cls(
            dllp_type_enb=bool(value & (1 << 9)),
            os_type_enb=bool(value & (1 << 10)),
            cxl_io_filter_enb=bool(value & (1 << 11)),
            cxl_cache_filter_enb=bool(value & (1 << 12)),
            cxl_mem_filter_enb=bool(value & (1 << 13)),
            filter_256b_enb=bool(value & (1 << 14)),
            filter_src_sel=(value >> 20) & 0x7,
            filter_match_sel0=(value >> 24) & 0x7,
            filter_match_sel1=(value >> 28) & 0x7,
        )


# ---------------------------------------------------------------------------
# Invert Filter Control Register — A0 only (+0x034)
# ---------------------------------------------------------------------------


@dataclass
class InvertFilterControlReg:
    """PTrace Invert Filter Control Register -- A0 only (+0x034).

    Bitfields:
        [9]  DLLPTypeInv
        [10] OsTypeInv
    """

    dllp_type_inv: bool = False
    os_type_inv: bool = False

    def to_register(self) -> int:
        value = 0
        if self.dllp_type_inv:
            value |= 1 << 9
        if self.os_type_inv:
            value |= 1 << 10
        return value

    @classmethod
    def from_register(cls, value: int) -> InvertFilterControlReg:
        return cls(
            dllp_type_inv=bool(value & (1 << 9)),
            os_type_inv=bool(value & (1 << 10)),
        )


# ---------------------------------------------------------------------------
# Trace Buffer Access Control Register (+0x180)
# ---------------------------------------------------------------------------


@dataclass
class TBufAccessCtlReg:
    """PTrace Trace Buffer Access Control Register (+0x180).

    Bitfields:
        [0]  TBufReadEnb -- enable software read of trace buffer
        [1]  TBufAddrSelfIncEnb -- auto-increment row after full read
    """

    tbuf_read_enb: bool = False
    tbuf_addr_self_inc_enb: bool = False

    def to_register(self) -> int:
        value = 0
        if self.tbuf_read_enb:
            value |= 1 << 0
        if self.tbuf_addr_self_inc_enb:
            value |= 1 << 1
        return value

    @classmethod
    def from_register(cls, value: int) -> TBufAccessCtlReg:
        return cls(
            tbuf_read_enb=bool(value & (1 << 0)),
            tbuf_addr_self_inc_enb=bool(value & (1 << 1)),
        )


# ---------------------------------------------------------------------------
# Port Error Type (for error trigger enable register)
# Updated to match RD101 page 270 for A0 silicon
# ---------------------------------------------------------------------------


class PortErrType(IntFlag):
    """Port error bit definitions for PORT_ERR_TRIG_EN.

    28 named error bits matching RD101 spec (A0 silicon).
    """

    RCVR_ERR = 1 << 0
    BAD_TLP = 1 << 1
    BAD_DLLP = 1 << 2
    REPLAY_NUM_ROLLOVER = 1 << 3
    REPLAY_TIMER_TIMEOUT = 1 << 4
    ADVISORY_NONFATAL = 1 << 5
    CORRECTED_INTERNAL = 1 << 6
    HEADER_LOG_OVERFLOW = 1 << 7
    DATA_LINK_PROTO_ERR = 1 << 8
    SURPRISE_DOWN = 1 << 9
    POISONED_TLP = 1 << 10
    FLOW_CONTROL_PROTO_ERR = 1 << 11
    COMPLETION_TIMEOUT = 1 << 12
    COMPLETER_ABORT = 1 << 13
    UNEXPECTED_COMPLETION = 1 << 14
    RECEIVER_OVERFLOW = 1 << 15
    MALFORMED_TLP = 1 << 16
    ECRC_ERROR = 1 << 17
    UNSUPPORTED_REQUEST = 1 << 18
    ACS_VIOLATION = 1 << 19
    UNCORRECTABLE_INTERNAL = 1 << 20
    POISONED_TLP_EGRESS_BLOCKED = 1 << 21
    DPC_TRIGGERED = 1 << 22
    SURPRISE_DOWN_ERR = 1 << 23
    TRANSLATION_EGRESS_BLOCK = 1 << 24
    FRAMING_ERROR = 1 << 25
    FEC_CORRECTABLE = 1 << 26
    FEC_UNCORRECTABLE = 1 << 27


# Friendly names for each error bit (for UI display)
PORT_ERR_NAMES: dict[int, str] = {
    0: "Receiver Error",
    1: "Bad TLP",
    2: "Bad DLLP",
    3: "Replay Num Rollover",
    4: "Replay Timer Timeout",
    5: "Advisory Non-Fatal",
    6: "Corrected Internal",
    7: "Header Log Overflow",
    8: "Data Link Protocol Error",
    9: "Surprise Down",
    10: "Poisoned TLP Received",
    11: "Flow Control Protocol Error",
    12: "Completion Timeout",
    13: "Completer Abort",
    14: "Unexpected Completion",
    15: "Receiver Overflow",
    16: "Malformed TLP",
    17: "ECRC Error",
    18: "Unsupported Request",
    19: "ACS Violation",
    20: "Uncorrectable Internal",
    21: "Poisoned TLP Egress Blocked",
    22: "DPC Triggered",
    23: "Surprise Down Error",
    24: "Translation Egress Block",
    25: "Framing Error",
    26: "FEC Correctable",
    27: "FEC Uncorrectable",
}


# ---------------------------------------------------------------------------
# Event Counter Config Register
# ---------------------------------------------------------------------------


@dataclass
class EventCounterCfgReg:
    """PTrace Event Counter Config Register (CFG offset).

    Bitfields:
        [5:0]   EventSource -- counter event source ID

    Note: The threshold is in a SEPARATE register at CFG+4 (EVT_CTR0_THRESHOLD
    or EVT_CTR1_THRESHOLD). Use ``EventCounterThresholdReg`` for that register.
    """

    event_source: int = 0

    def to_register(self) -> int:
        return self.event_source & 0x3F

    @classmethod
    def from_register(cls, value: int) -> EventCounterCfgReg:
        return cls(event_source=value & 0x3F)


@dataclass
class EventCounterThresholdReg:
    """PTrace Event Counter Threshold Register (CFG+4 offset).

    Bitfields:
        [15:0]  Threshold -- counter threshold value
    """

    threshold: int = 0

    def to_register(self) -> int:
        return self.threshold & 0xFFFF

    @classmethod
    def from_register(cls, value: int) -> EventCounterThresholdReg:
        return cls(threshold=value & 0xFFFF)
