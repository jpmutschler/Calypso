"""PTrace (Protocol Trace) Pydantic models.

Data models for PTrace capture configuration, trigger settings, status
readback, and trace buffer results. Used by API routes and UI pages.
"""

from __future__ import annotations

import re
from enum import IntEnum, Enum

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PTraceDirection(str, Enum):
    """PTrace capture direction."""

    INGRESS = "ingress"
    EGRESS = "egress"


class TracePointSel(IntEnum):
    """Trace point selection within the station pipeline."""

    ACCUM_DISTRIB = 0  # Accumulator / Distributor
    UNSCRAM_OSGEN = 1  # Unscrambler / OS Generator
    DESKEW_SCRAM = 2  # Deskew / Scrambler
    SCRAMBLED = 3  # Scrambled data


class FlitMatchMode(IntEnum):
    """Flit mode match selection for trigger/filter conditions."""

    MATCH_ALL = 0
    MATCH_DW1 = 1
    MATCH_DW1_4 = 2
    MATCH_DW1_8 = 3
    MATCH_DW1_12 = 4
    MATCH_DW1_16 = 5
    MATCH_H_SLOT = 6
    MATCH_H_OR_G = 7


# ---------------------------------------------------------------------------
# Configuration models
# ---------------------------------------------------------------------------


class PTraceCaptureCfg(BaseModel):
    """Capture configuration for PTrace."""

    direction: PTraceDirection = PTraceDirection.INGRESS
    port_number: int = Field(0, ge=0, le=143)
    lane: int = Field(0, ge=0, le=15)
    trace_point: TracePointSel = TracePointSel.ACCUM_DISTRIB
    filter_en: bool = False
    compress_en: bool = False
    nop_filt: bool = False
    idle_filt: bool = False
    data_cap: bool = False
    raw_filt: bool = False
    trig_out_mask: bool = False


class PTraceTriggerCfg(BaseModel):
    """Trigger configuration for PTrace."""

    trigger_src: int = Field(0, ge=0, le=63)
    rearm_enable: bool = False
    rearm_time: int = Field(0, ge=0, le=0x1FFFFFF)
    cond0_enable: int = Field(0, ge=0, le=0xFFFFFFFF)
    cond0_invert: int = Field(0, ge=0, le=0xFFFFFFFF)
    cond1_enable: int = Field(0, ge=0, le=0xFFFFFFFF)
    cond1_invert: int = Field(0, ge=0, le=0xFFFFFFFF)
    # A0 Flit-mode fields (optional, ignored on B0)
    cond0_inv: bool = False
    cond1_inv: bool = False
    trigger_match_sel0: int = Field(0, ge=0, le=7)
    trigger_match_sel1: int = Field(0, ge=0, le=7)


class PTracePostTriggerCfg(BaseModel):
    """Post-trigger configuration for PTrace."""

    clock_count: int = Field(0, ge=0, le=0xFFFF)
    cap_count: int = Field(0, ge=0, le=0x7FF)
    clock_cnt_mult: int = Field(0, ge=0, le=7)
    count_type: int = Field(0, ge=0, le=3)


class PTraceErrorTriggerCfg(BaseModel):
    """Error trigger enable configuration (28-bit mask)."""

    error_mask: int = Field(0, ge=0, le=0x0FFFFFFF)


class PTraceEventCounterCfg(BaseModel):
    """Event counter configuration."""

    counter_id: int = Field(0, ge=0, le=1)
    event_source: int = Field(0, ge=0, le=63)
    threshold: int = Field(0, ge=0, le=0xFFFF)


class PTraceFilterCfg(BaseModel):
    """512-bit filter configuration (128-char hex strings)."""

    filter_idx: int = Field(0, ge=0, le=1)
    match_hex: str = Field("0" * 128, min_length=128, max_length=128)
    mask_hex: str = Field("0" * 128, min_length=128, max_length=128)

    @field_validator("match_hex", "mask_hex")
    @classmethod
    def _validate_hex(cls, v: str) -> str:
        if not re.fullmatch(r"[0-9a-fA-F]+", v):
            raise ValueError("Must contain only hex characters (0-9, a-f, A-F)")
        return v


class PTraceFilterControlCfg(BaseModel):
    """Filter Control configuration (A0 only)."""

    dllp_type_enb: bool = False
    os_type_enb: bool = False
    cxl_io_filter_enb: bool = False
    cxl_cache_filter_enb: bool = False
    cxl_mem_filter_enb: bool = False
    filter_256b_enb: bool = False
    filter_src_sel: int = Field(0, ge=0, le=7)
    filter_match_sel0: int = Field(0, ge=0, le=7)
    filter_match_sel1: int = Field(0, ge=0, le=7)
    # Invert controls
    dllp_type_inv: bool = False
    os_type_inv: bool = False


class PTraceConditionAttrCfg(BaseModel):
    """Condition attribute register configuration."""

    condition_id: int = Field(0, ge=0, le=1)
    link_speed: int = Field(0, ge=0, le=15)
    link_speed_mask: int = Field(0, ge=0, le=15)
    link_width: int = Field(0, ge=0, le=7)
    link_width_mask: int = Field(0, ge=0, le=7)
    dllp_type: int = Field(0, ge=0, le=255)
    dllp_type_mask: int = Field(0, ge=0, le=255)
    os_type: int = Field(0, ge=0, le=255)
    os_type_mask: int = Field(0, ge=0, le=255)
    symbols: list[int] = Field(default_factory=lambda: [0] * 10)
    symbols_mask: list[int] = Field(default_factory=lambda: [0] * 10)
    dlp0: int = Field(0, ge=0, le=255)
    dlp0_mask: int = Field(0, ge=0, le=255)
    dlp1: int = Field(0, ge=0, le=255)
    dlp1_mask: int = Field(0, ge=0, le=255)
    ltssm_state: int = Field(0, ge=0, le=4095)
    ltssm_state_mask: int = Field(0, ge=0, le=4095)
    flit_mode: bool = False
    flit_mode_mask: bool = False
    cxl_mode: bool = False
    cxl_mode_mask: bool = False


class PTraceConditionDataCfg(BaseModel):
    """512-bit condition match/mask data configuration."""

    condition_id: int = Field(0, ge=0, le=1)
    match_hex: str = Field("0" * 128, min_length=128, max_length=128)
    mask_hex: str = Field("0" * 128, min_length=128, max_length=128)

    @field_validator("match_hex", "mask_hex")
    @classmethod
    def _validate_hex(cls, v: str) -> str:
        if not re.fullmatch(r"[0-9a-fA-F]+", v):
            raise ValueError("Must contain only hex characters (0-9, a-f, A-F)")
        return v


# ---------------------------------------------------------------------------
# Full configure request (combines capture + trigger + post-trigger)
# ---------------------------------------------------------------------------


class PTraceFullConfigureRequest(BaseModel):
    """Full configuration request combining all PTrace settings."""

    port_number: int = Field(0, ge=0, le=143)
    direction: PTraceDirection = PTraceDirection.INGRESS
    capture: PTraceCaptureCfg = Field(default_factory=PTraceCaptureCfg)
    trigger: PTraceTriggerCfg = Field(default_factory=PTraceTriggerCfg)
    post_trigger: PTracePostTriggerCfg = Field(default_factory=PTracePostTriggerCfg)
    filter_control: PTraceFilterControlCfg | None = None
    condition_attrs: list[PTraceConditionAttrCfg] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Status / readback models
# ---------------------------------------------------------------------------


class PTraceStatus(BaseModel):
    """Full PTrace status readback."""

    capture_in_progress: bool = False
    triggered: bool = False
    tbuf_wrapped: bool = False
    compress_cnt: int = 0
    ram_init_done: bool = False
    start_ts: int = 0
    trigger_ts: int = 0
    last_ts: int = 0
    global_timer: int = 0
    trigger_row_addr: int = 0
    port_err_status: int = 0


# ---------------------------------------------------------------------------
# Buffer models
# ---------------------------------------------------------------------------


class PTraceBufferRow(BaseModel):
    """A single 600-bit trace buffer row."""

    row_index: int
    dwords: list[int] = Field(default_factory=list)
    hex_str: str = ""


class PTraceBufferResult(BaseModel):
    """Result of reading the PTrace trace buffer."""

    direction: PTraceDirection
    port_number: int
    rows: list[PTraceBufferRow] = Field(default_factory=list)
    trigger_row_addr: int = 0
    triggered: bool = False
    tbuf_wrapped: bool = False
    total_rows_read: int = 0


# ---------------------------------------------------------------------------
# Decoded trace buffer models (used by ptrace_decoder)
# ---------------------------------------------------------------------------


class TraceFormat(IntEnum):
    """Trace buffer format version (from IPAL_BUFFER_HEADER.TraceFormat)."""

    TRACE0 = 0  # Original format
    TRACE1 = 1  # Updated format with link speed, compression, wider interval count


class TraceEntryType(IntEnum):
    """Trace entry type discriminator (footer bits [31:30])."""

    TIMESTAMP = 0  # 00b — timestamp marker
    TRIGGER = 1  # 01b — trigger event marker
    DATA = 2  # 10b — captured trace data
    COMPRESS = 3  # 11b — compressed repeat (TRACE1 only)


class PacketToken(IntEnum):
    """Per-lane metadata token for TLP/DLLP capture modes (IPAL_DATA0_PACKET_TOKEN)."""

    NULL = 0  # Filler / no packet boundary
    DLLP_START = 1  # This DWORD starts a DLLP
    TLP_START = 2  # This DWORD starts a TLP
    TLP_DLLP_END = 3  # This DWORD ends a TLP or DLLP


class SymbolToken(IntEnum):
    """Per-lane metadata token for symbol capture modes (IPAL_DATA0_SYMBOL_TOKEN)."""

    UNDEFINED = 0  # No additional information
    START_OS_BLOCK = 1  # Start of ordered-set block (sync header 01b, Gen3-5)
    DATA_BLOCK = 2  # Part of a data block (Gen3-5)
    RESERVED = 3  # Reserved for future use


class DecodedFooter(BaseModel, frozen=True):
    """Decoded footer DWORD from a trace buffer entry."""

    entry_type: TraceEntryType
    interval_count: int = 0
    link_speed: int | None = None  # 3-bit field, TRACE1 only; None for TRACE0
    compress_count: int | None = None  # 12-bit field, TRACE1 COMPRESS/TRIGGER_DATA only
    timestamp_or_data: bool | None = None  # Bit 29, TRIGGER entries only
    raw: int = Field(0, ge=0, le=0xFFFFFFFF)


class DecodedMetadata(BaseModel, frozen=True):
    """Decoded metadata DWORD — 2-bit token per captured lane."""

    raw: int = Field(0, ge=0, le=0xFFFFFFFF)
    lane_tokens: tuple[int, ...] = Field(
        default_factory=lambda: (0,) * 16,
        description="16 two-bit token values, indexed by lane number",
    )


class DecodedTraceEntry(BaseModel, frozen=True):
    """A fully decoded trace buffer entry."""

    row_index: int
    entry_type: TraceEntryType
    footer: DecodedFooter
    metadata: DecodedMetadata | None = None  # None for TIMESTAMP entries
    payload_dwords: tuple[int, ...] = Field(default_factory=tuple)  # DW[0:15]
    payload_hex: str = ""  # DW[0:15] as hex string
    timestamp: int | None = None  # 64-bit value, TIMESTAMP entries only
    dword_18: int = 0  # Atlas3 19th DWORD (purpose TBD, stored for forward compat)
    is_trigger_point: bool = False


class DecodedTraceBuffer(BaseModel, frozen=True):
    """Fully decoded trace buffer with summary statistics."""

    direction: PTraceDirection
    port_number: int
    trace_format: TraceFormat
    entries: tuple[DecodedTraceEntry, ...] = Field(default_factory=tuple)
    total_entries: int = 0
    timestamp_count: int = 0
    data_count: int = 0
    trigger_count: int = 0
    compress_count: int = 0
    trigger_index: int | None = None  # Index into entries list, or None
    buffer_wrapped: bool = False
