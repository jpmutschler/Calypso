"""LTSSM state definitions and API response models.

PCIe spec LTSSM (Link Training and Status State Machine) top-level state
codes and Pydantic models for the LTSSM trace / Ptrace capture feature.

The Atlas3 Recovery Diagnostic register encodes LTSSM state as a 12-bit
value: bits [11:8] = top-level state, bits [7:0] = sub-state within that
top-level state.  ``LtssmTopState`` maps the top-level nibble to the
PCIe-standard LTSSM macro states.
"""

from __future__ import annotations

from enum import IntEnum

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# PCIe 6.0.1 LTSSM Top-Level States (hardware bits [11:8])
# ---------------------------------------------------------------------------


class LtssmTopState(IntEnum):
    """Top-level LTSSM state from hardware bits [11:8].

    Values match the 4-bit encoding in the Atlas3 Recovery Diagnostic
    register's data_value field (upper nibble of the 12-bit LTSSM code).
    """

    DETECT = 0
    POLLING = 1
    CONFIGURATION = 2
    L0 = 3
    RECOVERY = 4
    LOOPBACK = 5
    HOT_RESET = 6
    DISABLED = 7
    L0S = 8
    L1 = 9
    L2 = 0xA


# ---------------------------------------------------------------------------
# 12-bit LTSSM code helpers
# ---------------------------------------------------------------------------


def ltssm_top_state(raw: int) -> int:
    """Extract the top-level state from a 12-bit LTSSM code (bits [11:8])."""
    return (raw >> 8) & 0xF


def ltssm_sub_state(raw: int) -> int:
    """Extract the sub-state from a 12-bit LTSSM code (bits [7:0])."""
    return raw & 0xFF


def is_in_state(raw: int, top: LtssmTopState) -> bool:
    """Check whether *raw* 12-bit code belongs to *top* state."""
    return ltssm_top_state(raw) == top


# State category mapping — keyed by top-state value for O(1) lookup.
LTSSM_STATE_CATEGORY: dict[str, int] = {
    "Detect": LtssmTopState.DETECT,
    "Polling": LtssmTopState.POLLING,
    "Configuration": LtssmTopState.CONFIGURATION,
    "L0": LtssmTopState.L0,
    "Recovery": LtssmTopState.RECOVERY,
    "Loopback": LtssmTopState.LOOPBACK,
    "Hot Reset": LtssmTopState.HOT_RESET,
    "Disabled": LtssmTopState.DISABLED,
    "L0s": LtssmTopState.L0S,
    "L1": LtssmTopState.L1,
    "L2": LtssmTopState.L2,
}


# ---------------------------------------------------------------------------
# Atlas3 LTSSM sub-state names per top-level state
#
# Derived from the Atlas3 trigger-state table which uses the same 12-bit
# LTSSM encoding as the Recovery Diagnostic register readback.  Sub-state
# byte values are sparse (not sequential).  Unknown sub-states fall back
# to hex display.
# ---------------------------------------------------------------------------

_LTSSM_SUB_STATES: dict[int, dict[int, str]] = {
    LtssmTopState.DETECT: {
        0x00: "Detect.Quiet",
        0x01: "Detect.Active",
        0x02: "Detect.Rate",
        0x03: "Detect.Wait12ms",
        0x04: "Detect.P1Req",
        0x05: "Detect.Done",
        0x06: "Detect.P0Req",
        0x07: "Detect.RateOk",
        0x09: "Detect.SpcOp",
        0x0A: "Detect.WaitP1",
        0x0B: "Detect.WaitRate",
    },
    LtssmTopState.POLLING: {
        0x00: "Polling.Idle",
        0x01: "Polling.P0Req",
        0x03: "Polling.Active",
        0x06: "Polling.Done",
        0x07: "Polling.Config",
        0x0A: "Polling.TxEIOS",
        0x0B: "Polling.Compliance",
        0x0E: "Polling.EIdle",
        0x0F: "Polling.Speed",
    },
    LtssmTopState.CONFIGURATION: {
        0x00: "Config.Idle",
        0x01: "Config.LwStart.DN",
        0x02: "Config.LnWait.DN",
        0x03: "Config.LwAccept.DN",
        0x04: "Config.TxIdle",
        0x06: "Config.LnAccept.DN",
        0x07: "Config.Complete.DN",
        0x08: "Config.LnWait.UP",
        0x0C: "Config.LnAccept.UP",
        0x0E: "Config.Done",
        0x0F: "Config.TxCtlSkip",
        0x10: "Config.LwStart.UP",
        0x11: "Config.XlinkArbWon",
        0x12: "Config.Complete",
        0x14: "Config.TxSDSM",
        0x18: "Config.LwAccept.UP",
        0x1C: "Config.Complete.UP",
    },
    LtssmTopState.L0: {
        0x00: "L0.Idle",
        0x01: "L0",
        0x02: "L0.L0s",
        0x03: "L0.TxEIOS",
        0x04: "L0.LinkDown",
        0x05: "L0.LDWait",
        0x07: "L0.L1",
        0x09: "L0.Recovery",
        0x0B: "L0.L2",
        0x0D: "L0.ActRec",
    },
    LtssmTopState.RECOVERY: {
        0x00: "Recovery.Idle",
        0x01: "Recovery.RcvrLock",
        0x02: "Recovery.TxEIOS",
        0x03: "Recovery.RcvrCfg",
        0x05: "Recovery.EqPh1.DN",
        0x07: "Recovery.Speed",
        0x08: "Recovery.TxEIEOS",
        0x09: "Recovery.Reset",
        0x0A: "Recovery.Disable",
        0x0B: "Recovery.TxIdle",
        0x0C: "Recovery.ErrCfg",
        0x0D: "Recovery.TxSDSM",
        0x0E: "Recovery.ErrDet",
        0x0F: "Recovery.Loopback",
        0x10: "Recovery.EqPh3.UP",
        0x11: "Recovery.EqPh0.UP",
        0x15: "Recovery.EqPh2.DN",
        0x17: "Recovery.EqPh3.DN",
        0x18: "Recovery.EqPh2.UP",
        0x19: "Recovery.EqPh1.UP",
        0x1E: "Recovery.TxCtlSkp",
        0x1F: "Recovery.MyEqPhase",
    },
    LtssmTopState.LOOPBACK: {
        0x00: "Loopback.Idle",
        0x01: "Loopback.Entry",
        0x04: "Loopback.SlvEntry",
        0x06: "Loopback.TxEIOS",
        0x09: "Loopback.ActMst",
        0x0A: "Loopback.ActSlv",
        0x0B: "Loopback.Exit",
        0x0C: "Loopback.Speed",
        0x0F: "Loopback.EIdle",
    },
    LtssmTopState.HOT_RESET: {
        0x00: "HotReset.Idle",
        0x01: "HotReset.Dir",
        0x02: "HotReset.Rcv",
        0x03: "HotReset.Tx",
        0x04: "HotReset.TxEIOS.1",
        0x05: "HotReset.TxEIEOS",
        0x06: "HotReset.RcvWait",
        0x07: "HotReset.TxEIOS",
    },
    LtssmTopState.DISABLED: {
        0x00: "Disabled.Idle",
        0x01: "Disabled.TxTS1",
        0x03: "Disabled.TxEIOS",
        0x04: "Disabled.Done",
        0x06: "Disabled.P1Req",
        0x07: "Disabled.WaitEIOS",
        0x09: "Disabled.TxEIEOS",
        0x0E: "Disabled.RateOk",
        0x0F: "Disabled.Rate",
    },
    LtssmTopState.L0S: {
        0x00: "L0s.Idle",
        0x01: "L0s.Entry",
        0x02: "L0s.Active",
        0x03: "L0s.TxFTS",
        0x04: "L0s.TxSkp",
        0x0A: "L0s.TxEIE",
        0x0C: "L0s.TxSDSM",
    },
    LtssmTopState.L1: {
        0x00: "L1.Idle",
        0x05: "L1.RxEIOS",
        0x06: "L1.Active",
    },
    LtssmTopState.L2: {
        0x00: "L2.Idle",
        0x08: "L2.RxEIOS",
        0x09: "L2.Rate",
        0x0D: "L2.RateOk",
        0x0F: "L2.Active",
    },
}


LINK_SPEED_NAMES: dict[int, str] = {
    0: "Gen1 (2.5 GT/s)",
    1: "Gen2 (5.0 GT/s)",
    2: "Gen3 (8.0 GT/s)",
    3: "Gen4 (16.0 GT/s)",
    4: "Gen5 (32.0 GT/s)",
    5: "Gen6 (64.0 GT/s)",
}


def ltssm_state_name(code: int) -> str:
    """Return the human-readable name for a 12-bit LTSSM state code.

    Uses PCIe 6.0.1 Section 4.2.6 sub-state naming.  Known sub-states
    render as e.g. "Recovery.RcvrLock"; unknown sub-states fall back to
    hex, e.g. "RECOVERY (sub=0x09)".
    """
    top = ltssm_top_state(code)
    sub = ltssm_sub_state(code)
    try:
        top_name = LtssmTopState(top).name
    except ValueError:
        return f"UNKNOWN_0x{code:03X}"
    sub_table = _LTSSM_SUB_STATES.get(top, {})
    sub_name = sub_table.get(sub)
    if sub_name is not None:
        return sub_name
    if sub == 0:
        return top_name
    return f"{top_name} (sub=0x{sub:02X})"


def link_speed_name(code: int) -> str:
    """Return the human-readable name for a link speed code."""
    return LINK_SPEED_NAMES.get(code, f"Unknown ({code})")


# ---------------------------------------------------------------------------
# Phase 1: Polling / Retrain-and-Watch Models
# ---------------------------------------------------------------------------


class PortLtssmSnapshot(BaseModel):
    """Current LTSSM state snapshot for a port."""

    port_number: int
    port_select: int
    ltssm_state: int
    ltssm_state_name: str
    link_speed: int
    link_speed_name: str
    recovery_count: int
    link_down_count: int
    lane_reversal: bool
    rx_eval_count: int
    # Diagnostic raw register values (hex strings) for troubleshooting
    diag_reg_base: str = ""  # Absolute BAR 0 offset used
    diag_raw_recovery_diag: str = ""  # Recovery Diagnostic readback
    diag_raw_phy_status: str = ""  # PHY Additional Status readback
    diag_raw_phy_cmd_status: str = ""  # PHY Cmd/Status (num_ports sanity check)
    diag_raw_recovery_prewrite: str = ""  # Recovery Diag BEFORE our write


class LtssmTransition(BaseModel):
    """A single recorded LTSSM state transition."""

    timestamp_ms: float
    state: int
    state_name: str


class RetrainWatchResult(BaseModel):
    """Result of a retrain-and-watch operation."""

    port_number: int
    port_select: int
    transitions: list[LtssmTransition]
    final_state: int
    final_state_name: str
    final_speed: int
    final_speed_name: str
    duration_ms: float
    settled: bool


class RetrainWatchProgress(BaseModel):
    """Progress tracking for an active retrain-and-watch."""

    status: str  # "idle", "running", "complete", "error"
    port_number: int
    port_select: int
    elapsed_ms: float = 0.0
    transition_count: int = 0
    error: str | None = None


# ---------------------------------------------------------------------------
# Phase 2: Ptrace Capture Models
# ---------------------------------------------------------------------------


class PtraceConfig(BaseModel):
    """Configuration for a Ptrace capture session.

    port_select is auto-computed by LtssmTracer from the global port number.
    """

    trace_point: int = 0
    lane_select: int = 0
    trigger_on_ltssm: bool = False
    ltssm_trigger_state: int | None = None


class PtraceCaptureEntry(BaseModel):
    """A single captured Ptrace buffer entry."""

    index: int
    raw_data: str  # hex string of captured DWORD


class PtraceCaptureResult(BaseModel):
    """Result of reading the Ptrace capture buffer."""

    port_number: int
    entries: list[PtraceCaptureEntry]
    trigger_hit: bool
    total_captured: int


class PtraceStatusResponse(BaseModel):
    """Current Ptrace capture status."""

    capture_active: bool
    trigger_hit: bool
    entries_captured: int
