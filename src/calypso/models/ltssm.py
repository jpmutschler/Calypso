"""LTSSM state definitions and API response models.

PCIe spec LTSSM (Link Training and Status State Machine) top-level state
codes and Pydantic models for the LTSSM trace / Ptrace capture feature.
"""

from __future__ import annotations

from enum import IntEnum

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# PCIe 6.0.1 LTSSM Top-Level States
# ---------------------------------------------------------------------------

class LtssmState(IntEnum):
    """PCIe 6.0.1 LTSSM top-level states."""

    DETECT_QUIET = 0x00
    DETECT_ACTIVE = 0x01
    POLLING_ACTIVE = 0x02
    POLLING_CONFIGURATION = 0x03
    POLLING_COMPLIANCE = 0x04
    CONFIG_LINKWIDTH_START = 0x05
    CONFIG_LINKWIDTH_ACCEPT = 0x06
    CONFIG_LANENUM_WAIT = 0x07
    CONFIG_LANENUM_ACCEPT = 0x08
    CONFIG_COMPLETE = 0x09
    CONFIG_IDLE = 0x0A
    RECOVERY_RCVRLOCK = 0x0B
    RECOVERY_SPEED = 0x0C
    RECOVERY_RCVRCFG = 0x0D
    RECOVERY_IDLE = 0x0E
    L0 = 0x0F
    L0S_ENTRY = 0x10
    L0S_IDLE = 0x11
    L0S_FTS = 0x12
    L1_ENTRY = 0x13
    L1_IDLE = 0x14
    L2_IDLE = 0x15
    DISABLED = 0x16
    LOOPBACK_ENTRY = 0x17
    LOOPBACK_ACTIVE = 0x18
    LOOPBACK_EXIT = 0x19
    HOT_RESET = 0x1A


# State category colors for UI display
LTSSM_STATE_CATEGORY: dict[str, list[int]] = {
    "Detect": [0x00, 0x01],
    "Polling": [0x02, 0x03, 0x04],
    "Configuration": [0x05, 0x06, 0x07, 0x08, 0x09, 0x0A],
    "Recovery": [0x0B, 0x0C, 0x0D, 0x0E],
    "L0": [0x0F],
    "L0s": [0x10, 0x11, 0x12],
    "L1": [0x13, 0x14],
    "L2": [0x15],
    "Disabled": [0x16],
    "Loopback": [0x17, 0x18, 0x19],
    "Hot Reset": [0x1A],
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
    """Return the human-readable name for an LTSSM state code."""
    try:
        return LtssmState(code).name
    except ValueError:
        return f"UNKNOWN_0x{code:02X}"


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
