"""PCIe Packet Exerciser Pydantic models.

Data models for exerciser configuration, TLP definitions, status readback,
DP BIST control, and the composite PTrace+Exerciser workflow.
Used by API routes and UI pages.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from calypso.hardware.pktexer_regs import TlpType


# ---------------------------------------------------------------------------
# TLP configuration
# ---------------------------------------------------------------------------


class TlpConfig(BaseModel):
    """Configuration for a single TLP to send."""

    tlp_type: TlpType
    address: int = Field(0, ge=0, le=0xFFFFFFFFFFFFFFFF)
    length_dw: int = Field(1, ge=1, le=1024)
    requester_id: int = Field(0, ge=0, le=0xFFFF)
    target_id: int = Field(0, ge=0, le=0xFFFF)
    data: str | None = None  # Hex string for write payload (32-bit)
    relaxed_ordering: bool = False
    poisoned: bool = False
    tag: int | None = None  # None = auto-increment

    @field_validator("data")
    @classmethod
    def validate_hex_data(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        try:
            val = int(v, 16)
        except ValueError:
            raise ValueError(f"data must be a hex string, got: {v!r}")
        if val < 0 or val > 0xFFFFFFFF:
            raise ValueError(f"data must fit in 32 bits, got: 0x{val:X}")
        return v


# ---------------------------------------------------------------------------
# Exerciser send request
# ---------------------------------------------------------------------------


class ExerciserSendRequest(BaseModel):
    """Request to send TLPs via the packet exerciser."""

    port_number: int = Field(0, ge=0, le=143)
    tlps: list[TlpConfig] = Field(..., min_length=1, max_length=256)
    infinite_loop: bool = False
    max_outstanding_np: int = Field(8, ge=1, le=255)


# ---------------------------------------------------------------------------
# Thread status
# ---------------------------------------------------------------------------


class ThreadStatus(BaseModel):
    """Per-thread status."""

    thread_id: int
    running: bool = False
    done: bool = False


# ---------------------------------------------------------------------------
# Exerciser status
# ---------------------------------------------------------------------------


class ExerciserStatus(BaseModel):
    """Status readback from the packet exerciser."""

    enabled: bool = False
    np_pending: bool = False
    uio_p_pending: bool = False
    uio_np_pending: bool = False
    completion_received: bool = False
    completion_ep: bool = False
    completion_ecrc_error: bool = False
    completion_status: int = 0
    completion_data: int = 0
    threads: list[ThreadStatus] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# DP BIST
# ---------------------------------------------------------------------------


class DpBistRequest(BaseModel):
    """Request to run DP BIST."""

    loop_count: int = Field(1, ge=1, le=0xFFFF)
    inner_loop_count: int = Field(1, ge=1, le=0x7FFF)
    delay_count: int = Field(0, ge=0, le=0xFFFF)
    infinite: bool = False


class DpBistStatus(BaseModel):
    """DP BIST status readback."""

    tx_done: bool = False
    rx_done: bool = False
    passed: bool = True
    infinite_loop: bool = False


# ---------------------------------------------------------------------------
# Composite PTrace + Exerciser request
# ---------------------------------------------------------------------------


class CaptureAndSendRequest(BaseModel):
    """Composite request: configure PTrace + send exerciser TLPs + read buffer."""

    port_number: int = Field(0, ge=0, le=143)
    ptrace_direction: str = "egress"  # "ingress" or "egress"
    exerciser: ExerciserSendRequest
    read_buffer: bool = True
    post_trigger_wait_ms: int = Field(100, ge=10, le=5000)
