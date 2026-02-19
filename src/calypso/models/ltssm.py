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
}


# ---------------------------------------------------------------------------
# PCIe 6.0.1 Sub-state names per top-level state
#
# Sub-state byte values follow the PCIe spec presentation order (Section
# 4.2.6).  An empty string means the sub-state index IS the top-state name
# itself (e.g. top=3 sub=0 → "L0").  States with no defined sub-states
# (Hot Reset, Disabled) use an empty dict — sub=0 renders the top name,
# anything else falls back to hex.
# ---------------------------------------------------------------------------

_LTSSM_SUB_STATES: dict[int, dict[int, str]] = {
    LtssmTopState.DETECT: {
        0: "Detect.Quiet",
        1: "Detect.Active",
    },
    LtssmTopState.POLLING: {
        0: "Polling.Active",
        1: "Polling.Configuration",
        2: "Polling.Compliance",
    },
    LtssmTopState.CONFIGURATION: {
        0: "Config.Linkwidth.Start",
        1: "Config.Linkwidth.Accept",
        2: "Config.Lanenum.Wait",
        3: "Config.Lanenum.Accept",
        4: "Config.Complete",
        5: "Config.Idle",
    },
    LtssmTopState.L0: {
        0: "L0",
        1: "L0s.Entry",
        2: "L0s.Idle",
        3: "L0s.FTS",
        4: "L1.Entry",
        5: "L1.Idle",
        6: "L2.Idle",
        7: "L2.TransmitWake",
    },
    LtssmTopState.RECOVERY: {
        0: "Recovery.RcvrLock",
        1: "Recovery.Speed",
        2: "Recovery.RcvrCfg",
        3: "Recovery.Idle",
        4: "Recovery.Equalization",
    },
    LtssmTopState.LOOPBACK: {
        0: "Loopback.Entry",
        1: "Loopback.Active",
        2: "Loopback.Exit",
    },
    LtssmTopState.HOT_RESET: {},
    LtssmTopState.DISABLED: {},
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
