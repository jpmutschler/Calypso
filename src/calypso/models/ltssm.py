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

    Pure top-state (sub=0x00) returns just the name, e.g. "L0".
    Non-zero sub-state appends it, e.g. "DETECT (sub=0x01)".
    """
    top = ltssm_top_state(code)
    sub = ltssm_sub_state(code)
    try:
        name = LtssmTopState(top).name
    except ValueError:
        return f"UNKNOWN_0x{code:03X}"
    if sub == 0:
        return name
    return f"{name} (sub=0x{sub:02X})"


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
