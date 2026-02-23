"""Atlas3 PTrace (Protocol Trace) register definitions.

PTrace is the embedded protocol analyser built into every Atlas3 station.
It captures TLP headers/payloads, DLLPs, and ordered sets at ingress and
egress, with hardware triggering, filtering, and a 600-bit-wide trace
buffer (up to 4096 rows per direction).

Register offsets are relative to a *direction base* within the station:
    ingress_base = station_register_base(port) + 0x4000
    egress_base  = station_register_base(port) + 0x5000

Reference: RD101 / RM102 Atlas3 PTrace register specification.
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
# Register offsets (relative to direction base)
# ---------------------------------------------------------------------------


class PTraceReg(IntEnum):
    """PTrace register offsets within a direction block."""

    # Control / status
    CAPTURE_CONTROL = 0x000
    CAPTURE_STATUS = 0x004
    CAPTURE_CONFIG = 0x008
    POST_TRIGGER_CFG = 0x00C

    # Trigger source / condition
    TRIGGER_SRC_SEL = 0x020
    MANUAL_TRIGGER = 0x024
    TRIG_COND0_ENABLE = 0x028
    TRIG_COND0_INVERT = 0x02C
    TRIG_COND1_ENABLE = 0x030
    TRIG_COND1_INVERT = 0x034

    # Trigger condition match values
    TRIG_LINK_SPEED = 0x038
    TRIG_DLLP_TYPE = 0x03C
    TRIG_OS_TYPE = 0x040
    TRIG_SYMBOL0 = 0x044
    TRIG_SYMBOL1 = 0x048
    TRIG_SYMBOL2 = 0x04C
    TRIG_SYMBOL3 = 0x050
    TRIG_SYMBOL4 = 0x054
    TRIG_SYMBOL5 = 0x058
    TRIG_SYMBOL6 = 0x05C
    TRIG_SYMBOL7 = 0x060
    TRIG_SYMBOL8 = 0x064
    TRIG_SYMBOL9 = 0x068
    TRIG_LTSSM_STATE = 0x06C
    TRIG_LINK_WIDTH = 0x070

    # Timestamps (64-bit, low/high pairs)
    FIRST_CAPTURE_TS_LOW = 0x080
    FIRST_CAPTURE_TS_HIGH = 0x084
    LAST_CAPTURE_TS_LOW = 0x088
    LAST_CAPTURE_TS_HIGH = 0x08C
    TRIGGER_TS_LOW = 0x090
    TRIGGER_TS_HIGH = 0x094
    LAST_TS_LOW = 0x098
    LAST_TS_HIGH = 0x09C

    # Trigger row address
    TRIGGER_ROW_ADDR = 0x0A0

    # Error status / trigger
    PORT_ERR_STATUS = 0x100
    PORT_ERR_TRIG_EN = 0x140

    # Event counters
    EVT_CTR0_CFG = 0x160
    EVT_CTR0_VALUE = 0x164
    EVT_CTR1_CFG = 0x168
    EVT_CTR1_VALUE = 0x16C

    # Trace buffer access
    TBUF_ACCESS_CTL = 0x180
    TBUF_ADDRESS = 0x184
    TBUF_DATA_0 = 0x188
    TBUF_DATA_1 = 0x18C
    TBUF_DATA_2 = 0x190
    TBUF_DATA_3 = 0x194
    TBUF_DATA_4 = 0x198
    TBUF_DATA_5 = 0x19C
    TBUF_DATA_6 = 0x1A0
    TBUF_DATA_7 = 0x1A4
    TBUF_DATA_8 = 0x1A8
    TBUF_DATA_9 = 0x1AC
    TBUF_DATA_10 = 0x1B0
    TBUF_DATA_11 = 0x1B4
    TBUF_DATA_12 = 0x1B8
    TBUF_DATA_13 = 0x1BC
    TBUF_DATA_14 = 0x1C0
    TBUF_DATA_15 = 0x1C4
    TBUF_DATA_16 = 0x1C8
    TBUF_DATA_17 = 0x1CC
    TBUF_DATA_18 = 0x1D0

    # Filter blocks (512 bits each: 16 DWORDs match + 16 DWORDs mask)
    FILTER0_MATCH_BASE = 0x200
    FILTER0_MASK_BASE = 0x240
    FILTER1_MATCH_BASE = 0x280
    FILTER1_MASK_BASE = 0x2C0


# Constants
TBUF_ROW_DWORDS = 19  # 19 x 32 = 608 bits (600 data + 8 reserved)
TBUF_MAX_ROWS = 4096
FILTER_DWORDS = 16  # 512 bits = 16 DWORDs per filter half


# ---------------------------------------------------------------------------
# Address helpers
# ---------------------------------------------------------------------------


def ptrace_reg_abs(station_base: int, direction: PTraceDir, reg: PTraceReg) -> int:
    """Compute absolute BAR 0 offset for a PTrace register.

    Args:
        station_base: Station register base (from ``station_register_base()``).
        direction: Ingress or egress direction base.
        reg: Register offset within the direction block.

    Returns:
        Absolute 32-bit BAR 0 offset.
    """
    return station_base + int(direction) + int(reg)


def tbuf_data_offset(dword_index: int) -> int:
    """Return the register offset for trace buffer data DWORD *dword_index*.

    Args:
        dword_index: 0..18 (19 DWORDs per row).

    Returns:
        Register offset relative to direction base.
    """
    if not 0 <= dword_index < TBUF_ROW_DWORDS:
        raise ValueError(f"dword_index must be 0..{TBUF_ROW_DWORDS - 1}, got {dword_index}")
    return PTraceReg.TBUF_DATA_0 + (dword_index * 4)


# ---------------------------------------------------------------------------
# Capture Control Register (+0x000)
# ---------------------------------------------------------------------------


@dataclass
class CaptureControlReg:
    """PTrace Capture Control Register (+0x000).

    Bitfields:
        [0]   PTraceEnable — master enable for the analyzer
        [8]   CaptureStart — start capture (self-clearing)
        [9]   ManCaptureStop — stop capture
        [16]  ClearTriggered — W1C, must keep PTraceEnable=1
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
        [9]      TBufWrapped — trace buffer has wrapped
        [27:16]  CompressCnt — number of compressed entries
        [31]     RAMInitDone — trace buffer RAM initialization complete
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
        [0]     TrigOutMask — mask external trigger output
        [1]     FilterEn — enable capture filtering
        [2]     CompressEn — enable compression
        [3]     NopFilt — filter NOP ordered sets
        [4]     IdleFilt — filter IDLE DLLPs
        [5]     DataCap — capture data payloads (vs headers only)
        [6]     RawFilt — raw symbol filter
        [11:8]  CapPortSel — port select within station (0-15)
        [13:12] TracePointSel — 0=Accum/Distrib, 1=Unscram/OSGen,
                                 2=Deskew/Scram, 3=Scrambled
        [19:16] LaneSel — lane select (0-15)
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
        [15:0]   ClockCount — post-trigger clock count
        [26:16]  CapCount — post-trigger capture count
        [29:27]  ClockCntMult — clock count multiplier (power of 2)
        [31:30]  CountType — 0=disabled, 1=clock, 2=capture, 3=both
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
# Trigger Source Select Register (+0x020)
# ---------------------------------------------------------------------------


@dataclass
class TriggerSrcSelReg:
    """PTrace Trigger Source Select Register (+0x020).

    Bitfields:
        [5:0]   TriggerSrc — trigger source ID (0-63)
        [6]     ReArmEnable — enable automatic re-arm after trigger
        [31:7]  ReArmTime — re-arm delay (raw clock ticks)
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
# Trigger Condition Enable Register (+0x028/0x02C/0x030/0x034)
# ---------------------------------------------------------------------------


@dataclass
class TrigCondEnableReg:
    """PTrace Trigger Condition Enable / Invert Register.

    Used for offsets +0x028 (Cond0 Enable), +0x02C (Cond0 Invert),
    +0x030 (Cond1 Enable), +0x034 (Cond1 Invert).

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
        [19]     Symbol8Enb — (also Symbol8Enb in some docs)
        [20]     Symbol9Enb
        [21]     LtssmEnb
        [22]     LinkWidthEnb
    """

    raw: int = 0

    def to_register(self) -> int:
        return self.raw & 0xFFFFFFFF

    @classmethod
    def from_register(cls, value: int) -> TrigCondEnableReg:
        return cls(raw=value & 0xFFFFFFFF)

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
# Trace Buffer Access Control Register (+0x180)
# ---------------------------------------------------------------------------


@dataclass
class TBufAccessCtlReg:
    """PTrace Trace Buffer Access Control Register (+0x180).

    Bitfields:
        [0]  TBufReadEnb — enable software read of trace buffer
        [1]  TBufAddrSelfIncEnb — auto-increment row after full read
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
# Port Error Type (for error trigger enable register +0x140)
# ---------------------------------------------------------------------------


class PortErrType(IntFlag):
    """Port error bit definitions for PORT_ERR_TRIG_EN (+0x140).

    28 named error bits matching RD101 spec.
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
    MC_BLOCKED_TLP = 1 << 21
    ATOMIC_OP_EGRESS_BLOCKED = 1 << 22
    TLP_PREFIX_BLOCKED = 1 << 23
    POISONED_TLP_EGRESS_BLOCKED = 1 << 24
    DMWR_REQUEST_EGRESS_BLOCKED = 1 << 25
    IDE_CHECK_FAILED = 1 << 26
    MISROUTED_IDE_TLP = 1 << 27


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
    21: "MC Blocked TLP",
    22: "AtomicOp Egress Blocked",
    23: "TLP Prefix Blocked",
    24: "Poisoned TLP Egress Blocked",
    25: "DMWr Request Egress Blocked",
    26: "IDE Check Failed",
    27: "Misrouted IDE TLP",
}


# ---------------------------------------------------------------------------
# Event Counter Config Register (+0x160 / +0x168)
# ---------------------------------------------------------------------------


@dataclass
class EventCounterCfgReg:
    """PTrace Event Counter Config Register (+0x160 or +0x168).

    Bitfields:
        [5:0]   EventSource — counter event source ID
        [31:16] Threshold — counter threshold value
    """

    event_source: int = 0
    threshold: int = 0

    def to_register(self) -> int:
        value = self.event_source & 0x3F
        value |= (self.threshold & 0xFFFF) << 16
        return value

    @classmethod
    def from_register(cls, value: int) -> EventCounterCfgReg:
        return cls(
            event_source=value & 0x3F,
            threshold=(value >> 16) & 0xFFFF,
        )
