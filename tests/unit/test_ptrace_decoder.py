"""Tests for PTrace buffer decoder."""

from __future__ import annotations

import pytest

from calypso.core.ptrace_decoder import (
    _decode_footer_trace0,
    _decode_footer_trace1,
    decode_footer,
    decode_metadata,
    decode_trace_buffer,
    entry_type_name,
    link_speed_name,
    packet_token_name,
    symbol_token_name,
)
from calypso.models.ptrace import (
    PTraceBufferResult,
    PTraceBufferRow,
    PTraceDirection,
    TraceEntryType,
    TraceFormat,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_row(
    row_index: int = 0,
    payload: list[int] | None = None,
    metadata: int = 0,
    footer: int = 0,
    dword_18: int = 0,
) -> PTraceBufferRow:
    """Build a 19-DWORD row with specified footer/metadata."""
    dwords = list(payload or [0] * 16)
    assert len(dwords) == 16, "payload must be 16 DWORDs"
    dwords.append(metadata)  # DW[16]
    dwords.append(footer)  # DW[17]
    dwords.append(dword_18)  # DW[18]
    hex_str = "".join(f"{d:08X}" for d in dwords)
    return PTraceBufferRow(row_index=row_index, dwords=dwords, hex_str=hex_str)


def _footer_bits(
    entry_type: int,
    interval_count: int = 0,
    timestamp_or_data: int = 0,
) -> int:
    """Build a TRACE0 footer DWORD."""
    val = (entry_type & 0x3) << 30
    if entry_type == 2:  # DATA
        val |= (interval_count & 0x3FFF) << 16
    elif entry_type == 1:  # TRIGGER
        val |= (timestamp_or_data & 1) << 29
    return val


def _footer_bits_t1(
    entry_type: int,
    interval_count: int = 0,
    link_speed: int = 0,
    compress_count: int = 0,
    timestamp_or_data: int = 0,
) -> int:
    """Build a TRACE1 footer DWORD."""
    val = (entry_type & 0x3) << 30
    val |= link_speed & 0x7
    if entry_type == 2:  # DATA
        val |= (interval_count & 0xFFFFF) << 10
    elif entry_type == 3:  # COMPRESS
        val |= (interval_count & 0x3FFF) << 16
        val |= (compress_count & 0xFFF) << 4
    elif entry_type == 1:  # TRIGGER
        val |= (timestamp_or_data & 1) << 29
        if timestamp_or_data:
            val |= (compress_count & 0xFFF) << 4
    return val


def _make_buffer(
    rows: list[PTraceBufferRow],
    triggered: bool = False,
    trigger_row_addr: int = 0,
    tbuf_wrapped: bool = False,
) -> PTraceBufferResult:
    return PTraceBufferResult(
        direction=PTraceDirection.INGRESS,
        port_number=0,
        rows=rows,
        trigger_row_addr=trigger_row_addr,
        triggered=triggered,
        tbuf_wrapped=tbuf_wrapped,
        total_rows_read=len(rows),
    )


# ---------------------------------------------------------------------------
# Footer decoding — TRACE0
# ---------------------------------------------------------------------------


class TestDecodeFooterTrace0:
    def test_timestamp_type(self):
        raw = _footer_bits(entry_type=0)
        f = _decode_footer_trace0(raw)
        assert f.entry_type == TraceEntryType.TIMESTAMP
        assert f.interval_count == 0
        assert f.link_speed is None
        assert f.compress_count is None
        assert f.timestamp_or_data is None

    def test_trigger_type_timestamp(self):
        raw = _footer_bits(entry_type=1, timestamp_or_data=0)
        f = _decode_footer_trace0(raw)
        assert f.entry_type == TraceEntryType.TRIGGER
        assert f.timestamp_or_data is False

    def test_trigger_type_data(self):
        raw = _footer_bits(entry_type=1, timestamp_or_data=1)
        f = _decode_footer_trace0(raw)
        assert f.entry_type == TraceEntryType.TRIGGER
        assert f.timestamp_or_data is True

    def test_data_type(self):
        raw = _footer_bits(entry_type=2, interval_count=1234)
        f = _decode_footer_trace0(raw)
        assert f.entry_type == TraceEntryType.DATA
        assert f.interval_count == 1234
        assert f.link_speed is None

    def test_data_max_interval_count(self):
        raw = _footer_bits(entry_type=2, interval_count=0x3FFF)
        f = _decode_footer_trace0(raw)
        assert f.interval_count == 0x3FFF

    def test_compress_type_warns(self):
        """TRACE0 doesn't define COMPRESS — type 3 should still decode."""
        raw = 3 << 30
        f = _decode_footer_trace0(raw)
        assert f.entry_type == TraceEntryType.COMPRESS

    def test_all_zeros(self):
        f = _decode_footer_trace0(0x00000000)
        assert f.entry_type == TraceEntryType.TIMESTAMP
        assert f.raw == 0

    def test_all_ones(self):
        f = _decode_footer_trace0(0xFFFFFFFF)
        assert f.entry_type == TraceEntryType.COMPRESS
        assert f.raw == 0xFFFFFFFF

    def test_raw_preserved(self):
        raw = _footer_bits(entry_type=2, interval_count=42)
        f = _decode_footer_trace0(raw)
        assert f.raw == raw


# ---------------------------------------------------------------------------
# Footer decoding — TRACE1
# ---------------------------------------------------------------------------


class TestDecodeFooterTrace1:
    def test_timestamp_type(self):
        raw = _footer_bits_t1(entry_type=0, link_speed=3)
        f = _decode_footer_trace1(raw)
        assert f.entry_type == TraceEntryType.TIMESTAMP
        assert f.link_speed == 3
        assert f.interval_count == 0

    def test_data_type(self):
        raw = _footer_bits_t1(entry_type=2, interval_count=0xABCDE, link_speed=4)
        f = _decode_footer_trace1(raw)
        assert f.entry_type == TraceEntryType.DATA
        assert f.interval_count == 0xABCDE
        assert f.link_speed == 4
        assert f.compress_count is None

    def test_data_max_interval_count(self):
        raw = _footer_bits_t1(entry_type=2, interval_count=0xFFFFF, link_speed=0)
        f = _decode_footer_trace1(raw)
        assert f.interval_count == 0xFFFFF

    def test_compress_type(self):
        raw = _footer_bits_t1(entry_type=3, interval_count=500, compress_count=100, link_speed=2)
        f = _decode_footer_trace1(raw)
        assert f.entry_type == TraceEntryType.COMPRESS
        assert f.interval_count == 500
        assert f.compress_count == 100
        assert f.link_speed == 2

    def test_compress_max_counts(self):
        raw = _footer_bits_t1(
            entry_type=3, interval_count=0x3FFF, compress_count=0xFFF, link_speed=7
        )
        f = _decode_footer_trace1(raw)
        assert f.interval_count == 0x3FFF
        assert f.compress_count == 0xFFF
        assert f.link_speed == 7

    def test_trigger_async_timestamp(self):
        raw = _footer_bits_t1(entry_type=1, timestamp_or_data=0, link_speed=1)
        f = _decode_footer_trace1(raw)
        assert f.entry_type == TraceEntryType.TRIGGER
        assert f.timestamp_or_data is False
        assert f.compress_count is None
        assert f.link_speed == 1

    def test_trigger_data_with_compress(self):
        raw = _footer_bits_t1(entry_type=1, timestamp_or_data=1, compress_count=55, link_speed=4)
        f = _decode_footer_trace1(raw)
        assert f.entry_type == TraceEntryType.TRIGGER
        assert f.timestamp_or_data is True
        assert f.compress_count == 55
        assert f.link_speed == 4


# ---------------------------------------------------------------------------
# Footer dispatch
# ---------------------------------------------------------------------------


class TestDecodeFooterDispatch:
    def test_dispatch_trace0(self):
        raw = _footer_bits(entry_type=2, interval_count=100)
        f = decode_footer(raw, TraceFormat.TRACE0)
        assert f.link_speed is None  # TRACE0 never has link_speed

    def test_dispatch_trace1(self):
        raw = _footer_bits_t1(entry_type=2, interval_count=100, link_speed=3)
        f = decode_footer(raw, TraceFormat.TRACE1)
        assert f.link_speed == 3


# ---------------------------------------------------------------------------
# Metadata decoding
# ---------------------------------------------------------------------------


class TestDecodeMetadata:
    def test_all_zeros(self):
        md = decode_metadata(0x00000000)
        assert len(md.lane_tokens) == 16
        assert all(t == 0 for t in md.lane_tokens)

    def test_all_threes(self):
        md = decode_metadata(0xFFFFFFFF)
        assert all(t == 3 for t in md.lane_tokens)

    def test_lane0_only(self):
        md = decode_metadata(0x00000001)
        assert md.lane_tokens[0] == 1
        assert all(md.lane_tokens[i] == 0 for i in range(1, 16))

    def test_lane15_only(self):
        md = decode_metadata(0x80000000)
        assert md.lane_tokens[15] == 2  # bits [31:30] = 0b10 = 2
        assert all(md.lane_tokens[i] == 0 for i in range(15))

    def test_alternating_pattern(self):
        # 0x55555555 = 01 01 01 01 ... (each lane = 1)
        md = decode_metadata(0x55555555)
        assert all(t == 1 for t in md.lane_tokens)

    def test_raw_preserved(self):
        md = decode_metadata(0xDEADBEEF)
        assert md.raw == 0xDEADBEEF

    def test_known_pattern(self):
        # Set lane 0=2, lane 1=1, lane 2=3, rest=0
        # bits: ... 00 | 11 | 01 | 10  = 0x0000001E
        val = (2 << 0) | (1 << 2) | (3 << 4)
        md = decode_metadata(val)
        assert md.lane_tokens[0] == 2
        assert md.lane_tokens[1] == 1
        assert md.lane_tokens[2] == 3
        assert md.lane_tokens[3] == 0


# ---------------------------------------------------------------------------
# Single entry decoding
# ---------------------------------------------------------------------------


class TestDecodeSingleEntry:
    def test_timestamp_entry(self):
        ts_lo = 0x12345678
        ts_hi = 0xABCDEF00
        payload = [ts_lo, ts_hi] + [0] * 14
        footer = _footer_bits_t1(entry_type=0, link_speed=2)
        row = _make_row(payload=payload, footer=footer)
        buf = _make_buffer([row])
        result = decode_trace_buffer(buf, TraceFormat.TRACE1)
        entry = result.entries[0]
        assert entry.entry_type == TraceEntryType.TIMESTAMP
        assert entry.timestamp == (ts_hi << 32) | ts_lo
        assert entry.metadata is None

    def test_data_entry(self):
        payload = [i + 1 for i in range(16)]
        metadata = 0x00000005  # lane 0=1, lane 1=1
        footer = _footer_bits_t1(entry_type=2, interval_count=42, link_speed=4)
        row = _make_row(payload=payload, metadata=metadata, footer=footer)
        buf = _make_buffer([row])
        result = decode_trace_buffer(buf, TraceFormat.TRACE1)
        entry = result.entries[0]
        assert entry.entry_type == TraceEntryType.DATA
        assert entry.payload_dwords == tuple(payload)
        assert entry.metadata is not None
        assert entry.metadata.lane_tokens[0] == 1
        assert entry.timestamp is None

    def test_payload_hex(self):
        payload = [0xDEADBEEF] + [0] * 15
        footer = _footer_bits_t1(entry_type=2)
        row = _make_row(payload=payload, footer=footer)
        buf = _make_buffer([row])
        result = decode_trace_buffer(buf, TraceFormat.TRACE1)
        entry = result.entries[0]
        assert entry.payload_hex.startswith("DEADBEEF")
        assert len(entry.payload_hex) == 128  # 16 * 8 chars

    def test_dword_18_preserved(self):
        footer = _footer_bits_t1(entry_type=2)
        row = _make_row(footer=footer, dword_18=0xCAFEBABE)
        buf = _make_buffer([row])
        result = decode_trace_buffer(buf, TraceFormat.TRACE1)
        assert result.entries[0].dword_18 == 0xCAFEBABE

    def test_trigger_async_has_timestamp(self):
        ts_lo = 0x11111111
        ts_hi = 0x22222222
        payload = [ts_lo, ts_hi] + [0] * 14
        footer = _footer_bits_t1(entry_type=1, timestamp_or_data=0, link_speed=0)
        row = _make_row(payload=payload, footer=footer)
        buf = _make_buffer([row])
        result = decode_trace_buffer(buf, TraceFormat.TRACE1)
        entry = result.entries[0]
        assert entry.entry_type == TraceEntryType.TRIGGER
        assert entry.timestamp == (ts_hi << 32) | ts_lo

    def test_trigger_data_has_metadata(self):
        footer = _footer_bits_t1(entry_type=1, timestamp_or_data=1, link_speed=3)
        metadata = 0x0000000A  # lane 0=2, lane 1=2
        row = _make_row(footer=footer, metadata=metadata)
        buf = _make_buffer([row])
        result = decode_trace_buffer(buf, TraceFormat.TRACE1)
        entry = result.entries[0]
        assert entry.entry_type == TraceEntryType.TRIGGER
        assert entry.metadata is not None
        assert entry.timestamp is None

    def test_compress_entry_has_metadata(self):
        metadata = 0x0000000A
        footer = _footer_bits_t1(entry_type=3, interval_count=10, compress_count=5)
        row = _make_row(footer=footer, metadata=metadata)
        buf = _make_buffer([row])
        result = decode_trace_buffer(buf, TraceFormat.TRACE1)
        assert result.entries[0].metadata is not None
        assert result.entries[0].metadata.raw == 0x0000000A

    def test_18_dword_row_defaults_dword18_to_zero(self):
        """Rows with exactly 18 DWORDs (no 19th) default dword_18 to 0."""
        dwords = [0] * 16 + [0x0, _footer_bits_t1(entry_type=2)]
        row = PTraceBufferRow(row_index=0, dwords=dwords, hex_str="")
        buf = _make_buffer([row])
        result = decode_trace_buffer(buf)
        assert result.entries[0].dword_18 == 0


# ---------------------------------------------------------------------------
# Full buffer decoding
# ---------------------------------------------------------------------------


class TestDecodeTraceBuffer:
    def test_empty_buffer(self):
        buf = _make_buffer([])
        result = decode_trace_buffer(buf)
        assert result.total_entries == 0
        assert result.entries == ()
        assert result.trigger_index is None

    def test_single_data_row(self):
        footer = _footer_bits_t1(entry_type=2, interval_count=10, link_speed=4)
        row = _make_row(footer=footer)
        buf = _make_buffer([row])
        result = decode_trace_buffer(buf)
        assert result.total_entries == 1
        assert result.data_count == 1
        assert result.timestamp_count == 0

    def test_mixed_types(self):
        rows = [
            _make_row(row_index=0, footer=_footer_bits_t1(entry_type=0)),
            _make_row(row_index=1, footer=_footer_bits_t1(entry_type=2, interval_count=5)),
            _make_row(row_index=2, footer=_footer_bits_t1(entry_type=2, interval_count=10)),
            _make_row(row_index=3, footer=_footer_bits_t1(entry_type=1, timestamp_or_data=1)),
        ]
        buf = _make_buffer(rows, triggered=True, trigger_row_addr=3)
        result = decode_trace_buffer(buf)
        assert result.total_entries == 4
        assert result.timestamp_count == 1
        assert result.data_count == 2
        assert result.trigger_count == 1
        assert result.trigger_index == 3

    def test_trigger_identification(self):
        rows = [
            _make_row(row_index=0, footer=_footer_bits_t1(entry_type=2)),
            _make_row(row_index=1, footer=_footer_bits_t1(entry_type=2)),
            _make_row(row_index=2, footer=_footer_bits_t1(entry_type=2)),
        ]
        buf = _make_buffer(rows, triggered=True, trigger_row_addr=1)
        result = decode_trace_buffer(buf)
        assert result.trigger_index == 1
        assert result.entries[1].is_trigger_point is True
        assert result.entries[0].is_trigger_point is False
        assert result.entries[2].is_trigger_point is False

    def test_no_trigger(self):
        rows = [_make_row(row_index=0, footer=_footer_bits_t1(entry_type=2))]
        buf = _make_buffer(rows, triggered=False)
        result = decode_trace_buffer(buf)
        assert result.trigger_index is None
        assert result.entries[0].is_trigger_point is False

    def test_default_format_is_trace1(self):
        footer = _footer_bits_t1(entry_type=2, link_speed=4)
        row = _make_row(footer=footer)
        buf = _make_buffer([row])
        result = decode_trace_buffer(buf)
        assert result.trace_format == TraceFormat.TRACE1
        assert result.entries[0].footer.link_speed == 4

    def test_trace0_format(self):
        footer = _footer_bits(entry_type=2, interval_count=77)
        row = _make_row(footer=footer)
        buf = _make_buffer([row])
        result = decode_trace_buffer(buf, TraceFormat.TRACE0)
        assert result.trace_format == TraceFormat.TRACE0
        assert result.entries[0].footer.link_speed is None
        assert result.entries[0].footer.interval_count == 77

    def test_buffer_wrapped_flag(self):
        buf = _make_buffer([], tbuf_wrapped=True)
        result = decode_trace_buffer(buf)
        assert result.buffer_wrapped is True

    def test_direction_and_port_preserved(self):
        buf = PTraceBufferResult(
            direction=PTraceDirection.EGRESS,
            port_number=42,
            rows=[],
            total_rows_read=0,
        )
        result = decode_trace_buffer(buf)
        assert result.direction == PTraceDirection.EGRESS
        assert result.port_number == 42

    def test_compress_entry_counted(self):
        footer = _footer_bits_t1(entry_type=3, interval_count=10, compress_count=5)
        row = _make_row(footer=footer)
        buf = _make_buffer([row])
        result = decode_trace_buffer(buf)
        assert result.compress_count == 1
        assert result.entries[0].entry_type == TraceEntryType.COMPRESS
        assert result.entries[0].footer.compress_count == 5

    def test_short_row_skipped(self):
        """Rows with fewer than 18 DWORDs are skipped with a warning."""
        short_row = PTraceBufferRow(row_index=0, dwords=[0] * 10, hex_str="")
        buf = _make_buffer([short_row])
        result = decode_trace_buffer(buf)
        assert result.total_entries == 0


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


class TestPacketTokenName:
    @pytest.mark.parametrize(
        "token,expected",
        [(0, "NULL"), (1, "DLLP_START"), (2, "TLP_START"), (3, "TLP/DLLP_END")],
    )
    def test_valid_tokens(self, token, expected):
        assert packet_token_name(token) == expected

    def test_unknown(self):
        assert packet_token_name(99) == "UNKNOWN(99)"


class TestSymbolTokenName:
    @pytest.mark.parametrize(
        "token,expected",
        [(0, "UNDEFINED"), (1, "START_OS_BLOCK"), (2, "DATA_BLOCK"), (3, "RESERVED")],
    )
    def test_valid_tokens(self, token, expected):
        assert symbol_token_name(token) == expected

    def test_unknown(self):
        assert symbol_token_name(-1) == "UNKNOWN(-1)"


class TestLinkSpeedName:
    @pytest.mark.parametrize(
        "code,expected",
        [
            (0, "Gen1 (2.5 GT/s)"),
            (1, "Gen2 (5 GT/s)"),
            (2, "Gen3 (8 GT/s)"),
            (3, "Gen4 (16 GT/s)"),
            (4, "Gen5 (32 GT/s)"),
        ],
    )
    def test_known_speeds(self, code, expected):
        assert link_speed_name(code) == expected

    def test_gen6_tentative(self):
        assert "Gen6" in link_speed_name(5)
        assert "?" in link_speed_name(5)

    def test_unknown(self):
        assert link_speed_name(6) == "Unknown(6)"


class TestEntryTypeName:
    @pytest.mark.parametrize(
        "et,expected",
        [
            (TraceEntryType.TIMESTAMP, "TIMESTAMP"),
            (TraceEntryType.TRIGGER, "TRIGGER"),
            (TraceEntryType.DATA, "DATA"),
            (TraceEntryType.COMPRESS, "COMPRESS"),
        ],
    )
    def test_all_types(self, et, expected):
        assert entry_type_name(et) == expected
