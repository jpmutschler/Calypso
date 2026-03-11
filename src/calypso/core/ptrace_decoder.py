"""PTrace buffer decoder — transforms raw trace buffer DWORDs into structured entries.

Decodes the trace buffer format defined by Broadcom's IPAL (Integrated PCIe
Analyzer Library) specification. Each buffer row contains a footer DWORD with
a 2-bit type discriminator, a metadata DWORD with per-lane tokens, and a
16-DWORD payload of captured protocol data.

Supports both TRACE0 (original) and TRACE1 (updated with link speed,
compression, wider interval count) buffer formats.

Based on Atlas2 ipaldef.h structures. Atlas3-specific extensions (Gen6 link
speed, 19th DWORD purpose) are preserved as raw values pending updated header.

This module is pure-Python with no hardware I/O — it operates entirely on
the ``PTraceBufferResult`` produced by ``PTraceEngine.read_buffer()``.
"""

from __future__ import annotations

from calypso.models.ptrace import (
    DecodedFooter,
    DecodedMetadata,
    DecodedTraceBuffer,
    DecodedTraceEntry,
    PacketToken,
    PTraceBufferResult,
    PTraceBufferRow,
    SymbolToken,
    TraceEntryType,
    TraceFormat,
)
from calypso.utils.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Row layout constants (Atlas3: 19 DWORDs per row)
# ---------------------------------------------------------------------------

_PAYLOAD_DWORDS = 16  # DW[0..15] — 512 bits of trace data
_METADATA_DW_INDEX = 16  # DW[16] — per-lane metadata tokens
_FOOTER_DW_INDEX = 17  # DW[17] — type discriminator + timing fields
# TODO: Confirm DW[18] purpose with Atlas3 ipaldef.h from Broadcom.
# Hypothesis: Gen6 Flit-mode extension field or additional metadata.
_ATLAS3_EXTRA_DW_INDEX = 18  # DW[18] — Atlas3 19th DWORD (purpose TBD)

_TOKEN_WIDTH = 2  # Each lane token is 2 bits
_TOKEN_MASK = 0x3
_LANES_PER_ENTRY = 16  # Maximum lanes in metadata DWORD

_TYPE_SHIFT = 30
_TYPE_MASK = 0x3


# ---------------------------------------------------------------------------
# Footer decoding
# ---------------------------------------------------------------------------


def _decode_footer_trace0(raw: int) -> DecodedFooter:
    """Decode a TRACE0-format footer DWORD.

    TRACE0 layout (all entry types):
      bits [31:30] = Type (2 bits)
      For DATA:     bits [29:16] = IntervalCount (14 bits)
      For TRIGGER:  bit  [29]    = TimestampOrData
    """
    entry_type = TraceEntryType((raw >> _TYPE_SHIFT) & _TYPE_MASK)

    interval_count = 0
    timestamp_or_data: bool | None = None

    if entry_type == TraceEntryType.DATA:
        interval_count = (raw >> 16) & 0x3FFF  # 14 bits
    elif entry_type == TraceEntryType.TRIGGER:
        timestamp_or_data = bool((raw >> 29) & 1)
        # Bits [28:0] are reserved/unused for TRACE0 TRIGGER entries
    elif entry_type == TraceEntryType.COMPRESS:
        # COMPRESS (type 3) is not defined in TRACE0 — log warning
        log.warning("trace0_unexpected_compress", raw_footer=f"0x{raw:08X}")

    return DecodedFooter(
        entry_type=entry_type,
        interval_count=interval_count,
        link_speed=None,
        compress_count=None,
        timestamp_or_data=timestamp_or_data,
        raw=raw,
    )


def _decode_footer_trace1(raw: int) -> DecodedFooter:
    """Decode a TRACE1-format footer DWORD.

    TRACE1 layouts vary by entry type:

    TIMESTAMP:  bits [31:30]=Type, bits [2:0]=LinkSpeed
    TRIGGER_TS: bits [31:30]=Type, bit[29]=TsOrData(0), bits [2:0]=LinkSpeed
    TRIGGER_D:  bits [31:30]=Type, bit[29]=TsOrData(1),
                bits [15:4]=CompressCount, bits [2:0]=LinkSpeed
    DATA:       bits [31:30]=Type, bits [29:10]=IntervalCount(20),
                bits [2:0]=LinkSpeed
    COMPRESS:   bits [31:30]=Type, bits [29:16]=IntervalCount(14),
                bits [15:4]=CompressCount(12), bits [2:0]=LinkSpeed
    """
    entry_type = TraceEntryType((raw >> _TYPE_SHIFT) & _TYPE_MASK)
    link_speed = raw & 0x7  # 3 bits, always present in TRACE1

    interval_count = 0
    compress_count: int | None = None
    timestamp_or_data: bool | None = None

    if entry_type == TraceEntryType.TIMESTAMP:
        pass  # No additional fields beyond link_speed
    elif entry_type == TraceEntryType.TRIGGER:
        timestamp_or_data = bool((raw >> 29) & 1)
        if timestamp_or_data:  # Data captured at trigger point
            compress_count = (raw >> 4) & 0xFFF  # 12 bits
    elif entry_type == TraceEntryType.DATA:
        interval_count = (raw >> 10) & 0xFFFFF  # 20 bits
    elif entry_type == TraceEntryType.COMPRESS:
        interval_count = (raw >> 16) & 0x3FFF  # 14 bits
        compress_count = (raw >> 4) & 0xFFF  # 12 bits

    return DecodedFooter(
        entry_type=entry_type,
        interval_count=interval_count,
        link_speed=link_speed,
        compress_count=compress_count,
        timestamp_or_data=timestamp_or_data,
        raw=raw,
    )


def decode_footer(raw: int, trace_format: TraceFormat) -> DecodedFooter:
    """Decode a footer DWORD using the appropriate format-specific parser."""
    if trace_format == TraceFormat.TRACE0:
        return _decode_footer_trace0(raw)
    return _decode_footer_trace1(raw)


# ---------------------------------------------------------------------------
# Metadata decoding
# ---------------------------------------------------------------------------


def decode_metadata(raw: int) -> DecodedMetadata:
    """Extract 16 two-bit lane tokens from the metadata DWORD.

    Lane 0 token is in bits [1:0], lane 1 in bits [3:2], etc.
    Token interpretation (packet vs symbol mode) is left to the consumer.
    """
    tokens = tuple((raw >> (lane * _TOKEN_WIDTH)) & _TOKEN_MASK for lane in range(_LANES_PER_ENTRY))
    return DecodedMetadata(raw=raw, lane_tokens=tokens)


# ---------------------------------------------------------------------------
# Single entry decoding
# ---------------------------------------------------------------------------


def _decode_single_entry(
    row: PTraceBufferRow,
    trace_format: TraceFormat,
    is_trigger: bool,
) -> DecodedTraceEntry:
    """Decode a single trace buffer row into a structured entry."""
    dwords = row.dwords

    footer = decode_footer(dwords[_FOOTER_DW_INDEX], trace_format)
    entry_type = footer.entry_type

    # Metadata is meaningful for DATA, COMPRESS, and TRIGGER+data entries
    metadata: DecodedMetadata | None = None
    has_metadata = entry_type in (TraceEntryType.DATA, TraceEntryType.COMPRESS) or (
        entry_type == TraceEntryType.TRIGGER and footer.timestamp_or_data
    )
    if has_metadata:
        metadata = decode_metadata(dwords[_METADATA_DW_INDEX])

    # Payload is always DW[0:15]
    payload = tuple(dwords[:_PAYLOAD_DWORDS])
    payload_hex = "".join(f"{d:08X}" for d in payload)

    # Timestamp extraction for TIMESTAMP and TRIGGER-timestamp entries
    timestamp: int | None = None
    if entry_type == TraceEntryType.TIMESTAMP:
        timestamp = (dwords[1] << 32) | dwords[0]
    elif entry_type == TraceEntryType.TRIGGER and not footer.timestamp_or_data:
        timestamp = (dwords[1] << 32) | dwords[0]

    # Atlas3 19th DWORD
    dword_18 = dwords[_ATLAS3_EXTRA_DW_INDEX] if len(dwords) > _ATLAS3_EXTRA_DW_INDEX else 0

    return DecodedTraceEntry(
        row_index=row.row_index,
        entry_type=entry_type,
        footer=footer,
        metadata=metadata,
        payload_dwords=payload,
        payload_hex=payload_hex,
        timestamp=timestamp,
        dword_18=dword_18,
        is_trigger_point=is_trigger,
    )


# ---------------------------------------------------------------------------
# Full buffer decoding
# ---------------------------------------------------------------------------


def decode_trace_buffer(
    buffer: PTraceBufferResult,
    trace_format: TraceFormat = TraceFormat.TRACE1,
) -> DecodedTraceBuffer:
    """Decode a raw trace buffer into structured entries.

    Args:
        buffer: Raw buffer result from ``PTraceEngine.read_buffer()``.
        trace_format: Buffer format version (TRACE0 or TRACE1).
            Defaults to TRACE1 (the newer format with link speed/compression).

    Returns:
        Fully decoded buffer with typed entries and summary statistics.

    Note:
        Entries are returned in buffer-index order. When ``buffer.tbuf_wrapped``
        is True, chronological reordering requires ``BufferEndIndex`` from the
        IPAL buffer header, which is not yet available in PTraceBufferResult.
        The trigger row is marked via ``is_trigger_point`` on the entry.
    """
    entries: list[DecodedTraceEntry] = []
    trigger_index: int | None = None

    counts = {t: 0 for t in TraceEntryType}

    for i, row in enumerate(buffer.rows):
        if len(row.dwords) < _FOOTER_DW_INDEX + 1:
            log.warning("ptrace_row_too_short", row_index=row.row_index, dwords=len(row.dwords))
            continue

        is_trigger = buffer.triggered and row.row_index == buffer.trigger_row_addr
        entry = _decode_single_entry(row, trace_format, is_trigger)
        entries.append(entry)

        counts[entry.entry_type] = counts.get(entry.entry_type, 0) + 1
        if is_trigger:
            trigger_index = i

    log.debug(
        "ptrace_buffer_decoded",
        total=len(entries),
        timestamps=counts[TraceEntryType.TIMESTAMP],
        data=counts[TraceEntryType.DATA],
        triggers=counts[TraceEntryType.TRIGGER],
        compressed=counts[TraceEntryType.COMPRESS],
    )

    return DecodedTraceBuffer(
        direction=buffer.direction,
        port_number=buffer.port_number,
        trace_format=trace_format,
        entries=tuple(entries),
        total_entries=len(entries),
        timestamp_count=counts[TraceEntryType.TIMESTAMP],
        data_count=counts[TraceEntryType.DATA],
        trigger_count=counts[TraceEntryType.TRIGGER],
        compress_count=counts[TraceEntryType.COMPRESS],
        trigger_index=trigger_index,
        buffer_wrapped=buffer.tbuf_wrapped,
    )


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

# Known IPAL link speed codes (from Atlas2 ipaldef.h).
# Atlas3 Gen6 (64 GT/s) code is TBD — awaiting updated header from Broadcom.
_LINK_SPEED_NAMES: dict[int, str] = {
    0: "Gen1 (2.5 GT/s)",
    1: "Gen2 (5 GT/s)",
    2: "Gen3 (8 GT/s)",
    3: "Gen4 (16 GT/s)",
    4: "Gen5 (32 GT/s)",
    # TODO: Gen6 value — likely 5 for 64 GT/s, confirm with Atlas3 ipaldef.h
}

# Display labels for PacketToken — needed because PacketToken.TLP_DLLP_END.name
# produces "TLP_DLLP_END" but we want "TLP/DLLP_END" with the slash.
_PACKET_TOKEN_LABELS: dict[int, str] = {
    PacketToken.NULL: "NULL",
    PacketToken.DLLP_START: "DLLP_START",
    PacketToken.TLP_START: "TLP_START",
    PacketToken.TLP_DLLP_END: "TLP/DLLP_END",
}


def packet_token_name(token: int) -> str:
    """Human-readable name for a packet-mode metadata token."""
    return _PACKET_TOKEN_LABELS.get(token, f"UNKNOWN({token})")


def symbol_token_name(token: int) -> str:
    """Human-readable name for a symbol-mode metadata token."""
    try:
        return SymbolToken(token).name
    except ValueError:
        return f"UNKNOWN({token})"


def link_speed_name(code: int) -> str:
    """Human-readable name for a link speed code.

    Known values from Atlas2 ipaldef.h. Gen6 (64 GT/s) value is TBD
    for Atlas3 — likely code 5 but unconfirmed.
    """
    if code in _LINK_SPEED_NAMES:
        return _LINK_SPEED_NAMES[code]
    if code == 5:
        return "Gen6 (64 GT/s)?"  # TODO: confirm with Atlas3 ipaldef.h
    return f"Unknown({code})"


def entry_type_name(entry_type: TraceEntryType) -> str:
    """Human-readable name for a trace entry type."""
    return entry_type.name
