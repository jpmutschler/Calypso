"""Tests for PTrace Pydantic models.

Validates field constraints, enum values, and serialization.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from calypso.models.ptrace import (
    PTraceBufferResult,
    PTraceBufferRow,
    PTraceCaptureCfg,
    PTraceDirection,
    PTraceErrorTriggerCfg,
    PTraceEventCounterCfg,
    PTraceFilterCfg,
    PTraceFullConfigureRequest,
    PTracePostTriggerCfg,
    PTraceStatus,
    PTraceTriggerCfg,
    TracePointSel,
)


class TestPTraceDirection:
    """Direction enum values."""

    def test_ingress(self):
        assert PTraceDirection.INGRESS == "ingress"

    def test_egress(self):
        assert PTraceDirection.EGRESS == "egress"

    def test_string_coercion(self):
        cfg = PTraceCaptureCfg(direction="ingress")
        assert cfg.direction == PTraceDirection.INGRESS


class TestTracePointSel:
    """Trace point selection enum."""

    def test_values(self):
        assert TracePointSel.ACCUM_DISTRIB == 0
        assert TracePointSel.UNSCRAM_OSGEN == 1
        assert TracePointSel.DESKEW_SCRAM == 2
        assert TracePointSel.SCRAMBLED == 3


class TestPTraceCaptureCfg:
    """Capture configuration model validation."""

    def test_defaults(self):
        cfg = PTraceCaptureCfg()
        assert cfg.port_number == 0
        assert cfg.lane == 0
        assert cfg.trace_point == TracePointSel.ACCUM_DISTRIB
        assert not cfg.filter_en
        assert not cfg.compress_en

    def test_valid_port_range(self):
        cfg = PTraceCaptureCfg(port_number=143)
        assert cfg.port_number == 143

    def test_port_too_high(self):
        with pytest.raises(ValidationError):
            PTraceCaptureCfg(port_number=144)

    def test_port_negative(self):
        with pytest.raises(ValidationError):
            PTraceCaptureCfg(port_number=-1)

    def test_lane_range(self):
        cfg = PTraceCaptureCfg(lane=15)
        assert cfg.lane == 15

    def test_lane_too_high(self):
        with pytest.raises(ValidationError):
            PTraceCaptureCfg(lane=16)


class TestPTraceTriggerCfg:
    """Trigger configuration model validation."""

    def test_defaults(self):
        cfg = PTraceTriggerCfg()
        assert cfg.trigger_src == 0
        assert not cfg.rearm_enable
        assert cfg.cond0_enable == 0

    def test_trigger_src_range(self):
        cfg = PTraceTriggerCfg(trigger_src=63)
        assert cfg.trigger_src == 63

    def test_trigger_src_too_high(self):
        with pytest.raises(ValidationError):
            PTraceTriggerCfg(trigger_src=64)

    def test_cond_max_value(self):
        cfg = PTraceTriggerCfg(cond0_enable=0xFFFFFFFF)
        assert cfg.cond0_enable == 0xFFFFFFFF

    def test_cond_too_high(self):
        with pytest.raises(ValidationError):
            PTraceTriggerCfg(cond0_enable=0x100000000)


class TestPTracePostTriggerCfg:
    """Post-trigger configuration model validation."""

    def test_defaults(self):
        cfg = PTracePostTriggerCfg()
        assert cfg.clock_count == 0
        assert cfg.count_type == 0

    def test_clock_count_max(self):
        cfg = PTracePostTriggerCfg(clock_count=0xFFFF)
        assert cfg.clock_count == 0xFFFF

    def test_clock_count_too_high(self):
        with pytest.raises(ValidationError):
            PTracePostTriggerCfg(clock_count=0x10000)

    def test_count_type_range(self):
        cfg = PTracePostTriggerCfg(count_type=3)
        assert cfg.count_type == 3

    def test_count_type_too_high(self):
        with pytest.raises(ValidationError):
            PTracePostTriggerCfg(count_type=4)


class TestPTraceErrorTriggerCfg:
    """Error trigger configuration model validation."""

    def test_defaults(self):
        cfg = PTraceErrorTriggerCfg()
        assert cfg.error_mask == 0

    def test_max_mask(self):
        cfg = PTraceErrorTriggerCfg(error_mask=0x0FFFFFFF)
        assert cfg.error_mask == 0x0FFFFFFF

    def test_mask_too_high(self):
        with pytest.raises(ValidationError):
            PTraceErrorTriggerCfg(error_mask=0x10000000)


class TestPTraceEventCounterCfg:
    """Event counter configuration model validation."""

    def test_defaults(self):
        cfg = PTraceEventCounterCfg()
        assert cfg.counter_id == 0
        assert cfg.event_source == 0
        assert cfg.threshold == 0

    def test_counter_id_range(self):
        cfg = PTraceEventCounterCfg(counter_id=1)
        assert cfg.counter_id == 1

    def test_counter_id_too_high(self):
        with pytest.raises(ValidationError):
            PTraceEventCounterCfg(counter_id=2)

    def test_source_range(self):
        cfg = PTraceEventCounterCfg(event_source=63)
        assert cfg.event_source == 63

    def test_source_too_high(self):
        with pytest.raises(ValidationError):
            PTraceEventCounterCfg(event_source=64)


class TestPTraceFilterCfg:
    """Filter configuration model validation."""

    def test_defaults(self):
        cfg = PTraceFilterCfg()
        assert cfg.filter_idx == 0
        assert len(cfg.match_hex) == 128
        assert len(cfg.mask_hex) == 128

    def test_filter_idx_range(self):
        cfg = PTraceFilterCfg(filter_idx=1)
        assert cfg.filter_idx == 1

    def test_filter_idx_too_high(self):
        with pytest.raises(ValidationError):
            PTraceFilterCfg(filter_idx=2)

    def test_hex_too_short(self):
        with pytest.raises(ValidationError):
            PTraceFilterCfg(match_hex="0" * 64)

    def test_hex_too_long(self):
        with pytest.raises(ValidationError):
            PTraceFilterCfg(match_hex="0" * 256)

    def test_hex_invalid_chars(self):
        with pytest.raises(ValidationError):
            PTraceFilterCfg(match_hex="x" * 128)

    def test_hex_valid_mixed_case(self):
        cfg = PTraceFilterCfg(match_hex="aAbBcCdDeEfF" + "0" * 116)
        assert len(cfg.match_hex) == 128


class TestPTraceFullConfigureRequest:
    """Full configure request model."""

    def test_defaults(self):
        req = PTraceFullConfigureRequest()
        assert req.port_number == 0
        assert req.direction == PTraceDirection.INGRESS

    def test_nested_models(self):
        req = PTraceFullConfigureRequest(
            port_number=42,
            direction=PTraceDirection.EGRESS,
            capture=PTraceCaptureCfg(lane=5, filter_en=True),
            trigger=PTraceTriggerCfg(trigger_src=10),
            post_trigger=PTracePostTriggerCfg(clock_count=100),
        )
        assert req.capture.lane == 5
        assert req.trigger.trigger_src == 10
        assert req.post_trigger.clock_count == 100


class TestPTraceStatus:
    """Status readback model."""

    def test_defaults(self):
        status = PTraceStatus()
        assert not status.capture_in_progress
        assert not status.triggered
        assert status.first_capture_ts == 0

    def test_full_status(self):
        status = PTraceStatus(
            capture_in_progress=True,
            triggered=True,
            tbuf_wrapped=True,
            compress_cnt=42,
            ram_init_done=True,
            first_capture_ts=0x100001000,
            trigger_row_addr=100,
            port_err_status=0x0F,
        )
        assert status.capture_in_progress
        assert status.first_capture_ts == 0x100001000
        assert status.trigger_row_addr == 100


class TestPTraceBufferRow:
    """Buffer row model."""

    def test_basic_row(self):
        row = PTraceBufferRow(
            row_index=0,
            dwords=[0xDEADBEEF] + [0] * 18,
            hex_str="DEADBEEF" + "0" * 144,
        )
        assert row.row_index == 0
        assert len(row.dwords) == 19
        assert row.hex_str.startswith("DEADBEEF")


class TestPTraceBufferResult:
    """Buffer result model."""

    def test_empty_result(self):
        result = PTraceBufferResult(
            direction=PTraceDirection.INGRESS,
            port_number=0,
        )
        assert len(result.rows) == 0
        assert result.total_rows_read == 0

    def test_with_rows(self):
        rows = [
            PTraceBufferRow(row_index=i, dwords=[0] * 19, hex_str="0" * 152)
            for i in range(3)
        ]
        result = PTraceBufferResult(
            direction=PTraceDirection.EGRESS,
            port_number=42,
            rows=rows,
            trigger_row_addr=1,
            triggered=True,
            total_rows_read=3,
        )
        assert len(result.rows) == 3
        assert result.triggered
        assert result.direction == PTraceDirection.EGRESS

    def test_serialization(self):
        result = PTraceBufferResult(
            direction=PTraceDirection.INGRESS,
            port_number=5,
            total_rows_read=0,
        )
        data = result.model_dump()
        assert data["direction"] == "ingress"
        assert data["port_number"] == 5
