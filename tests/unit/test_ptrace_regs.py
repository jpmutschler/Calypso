"""Tests for PTrace hardware register definitions.

Tests encode/decode round-trip for all register dataclasses,
address calculation helpers, and enum completeness.
"""

from __future__ import annotations

import pytest

from calypso.hardware.ptrace_regs import (
    FILTER_DWORDS,
    TBUF_MAX_ROWS,
    TBUF_ROW_DWORDS,
    CaptureConfigReg,
    CaptureControlReg,
    CaptureStatusReg,
    EventCounterCfgReg,
    PostTriggerCfgReg,
    PTraceDir,
    PTraceReg,
    PortErrType,
    TBufAccessCtlReg,
    TrigCondEnableReg,
    TriggerSrcSelReg,
    ptrace_reg_abs,
    tbuf_data_offset,
)


class TestPTraceDir:
    """Direction enum values."""

    def test_ingress_offset(self):
        assert PTraceDir.INGRESS == 0x4000

    def test_egress_offset(self):
        assert PTraceDir.EGRESS == 0x5000


class TestPTraceRegAbs:
    """Absolute address calculation."""

    def test_basic_address(self):
        station_base = 0xF00000
        result = ptrace_reg_abs(station_base, PTraceDir.INGRESS, PTraceReg.CAPTURE_CONTROL)
        assert result == 0xF00000 + 0x4000 + 0x000

    def test_egress_address(self):
        station_base = 0xF10000  # station 1
        result = ptrace_reg_abs(station_base, PTraceDir.EGRESS, PTraceReg.CAPTURE_STATUS)
        assert result == 0xF10000 + 0x5000 + 0x004

    def test_filter_address(self):
        station_base = 0xF00000
        result = ptrace_reg_abs(station_base, PTraceDir.INGRESS, PTraceReg.FILTER0_MATCH_BASE)
        assert result == 0xF00000 + 0x4000 + 0x200


class TestTBufDataOffset:
    """Trace buffer data DWORD offset calculation."""

    def test_first_dword(self):
        assert tbuf_data_offset(0) == PTraceReg.TBUF_DATA_0

    def test_last_dword(self):
        assert tbuf_data_offset(18) == PTraceReg.TBUF_DATA_18

    def test_sequential_offsets(self):
        for i in range(TBUF_ROW_DWORDS):
            offset = tbuf_data_offset(i)
            assert offset == PTraceReg.TBUF_DATA_0 + (i * 4)

    def test_out_of_range(self):
        with pytest.raises(ValueError, match="dword_index"):
            tbuf_data_offset(19)

    def test_negative(self):
        with pytest.raises(ValueError, match="dword_index"):
            tbuf_data_offset(-1)


class TestCaptureControlReg:
    """Capture Control Register encode/decode."""

    def test_defaults_encode_to_zero(self):
        reg = CaptureControlReg()
        assert reg.to_register() == 0

    def test_enable_only(self):
        reg = CaptureControlReg(ptrace_enable=True)
        assert reg.to_register() == 0x1

    def test_capture_start(self):
        reg = CaptureControlReg(ptrace_enable=True, capture_start=True)
        assert reg.to_register() == 0x101

    def test_man_stop(self):
        reg = CaptureControlReg(ptrace_enable=True, man_capture_stop=True)
        assert reg.to_register() == 0x201

    def test_clear_triggered_keeps_enable(self):
        reg = CaptureControlReg(ptrace_enable=True, clear_triggered=True)
        val = reg.to_register()
        assert val & (1 << 0)  # PTraceEnable still set
        assert val & (1 << 16)  # ClearTriggered set

    def test_roundtrip(self):
        original = CaptureControlReg(
            ptrace_enable=True,
            capture_start=True,
            man_capture_stop=False,
            clear_triggered=True,
        )
        encoded = original.to_register()
        decoded = CaptureControlReg.from_register(encoded)
        assert decoded.ptrace_enable == original.ptrace_enable
        assert decoded.capture_start == original.capture_start
        assert decoded.man_capture_stop == original.man_capture_stop
        assert decoded.clear_triggered == original.clear_triggered


class TestCaptureStatusReg:
    """Capture Status Register decode (read-only)."""

    def test_all_clear(self):
        reg = CaptureStatusReg.from_register(0)
        assert not reg.capture_in_progress
        assert not reg.triggered
        assert not reg.tbuf_wrapped
        assert reg.compress_cnt == 0
        assert not reg.ram_init_done

    def test_capture_active(self):
        reg = CaptureStatusReg.from_register(1 << 0)
        assert reg.capture_in_progress

    def test_triggered(self):
        reg = CaptureStatusReg.from_register(1 << 8)
        assert reg.triggered

    def test_wrapped(self):
        reg = CaptureStatusReg.from_register(1 << 9)
        assert reg.tbuf_wrapped

    def test_compress_cnt(self):
        reg = CaptureStatusReg.from_register(0x00AB0000)
        assert reg.compress_cnt == 0x0AB

    def test_ram_init_done(self):
        reg = CaptureStatusReg.from_register(1 << 31)
        assert reg.ram_init_done

    def test_combined(self):
        value = (1 << 0) | (1 << 8) | (1 << 9) | (0x123 << 16) | (1 << 31)
        reg = CaptureStatusReg.from_register(value)
        assert reg.capture_in_progress
        assert reg.triggered
        assert reg.tbuf_wrapped
        assert reg.compress_cnt == 0x123
        assert reg.ram_init_done


class TestCaptureConfigReg:
    """Capture Config Register encode/decode."""

    def test_defaults(self):
        reg = CaptureConfigReg()
        assert reg.to_register() == 0

    def test_port_select(self):
        reg = CaptureConfigReg(cap_port_sel=5)
        assert (reg.to_register() >> 8) & 0xF == 5

    def test_trace_point(self):
        reg = CaptureConfigReg(trace_point_sel=3)
        assert (reg.to_register() >> 12) & 0x3 == 3

    def test_lane_sel(self):
        reg = CaptureConfigReg(lane_sel=15)
        assert (reg.to_register() >> 16) & 0xF == 15

    def test_filter_flags(self):
        reg = CaptureConfigReg(
            filter_en=True,
            compress_en=True,
            nop_filt=True,
            idle_filt=True,
            data_cap=True,
        )
        val = reg.to_register()
        assert val & (1 << 1)  # FilterEn
        assert val & (1 << 2)  # CompressEn
        assert val & (1 << 3)  # NopFilt
        assert val & (1 << 4)  # IdleFilt
        assert val & (1 << 5)  # DataCap

    def test_roundtrip(self):
        original = CaptureConfigReg(
            trig_out_mask=True,
            filter_en=True,
            compress_en=False,
            nop_filt=True,
            idle_filt=False,
            data_cap=True,
            raw_filt=True,
            cap_port_sel=7,
            trace_point_sel=2,
            lane_sel=11,
        )
        encoded = original.to_register()
        decoded = CaptureConfigReg.from_register(encoded)
        assert decoded.trig_out_mask == original.trig_out_mask
        assert decoded.filter_en == original.filter_en
        assert decoded.compress_en == original.compress_en
        assert decoded.nop_filt == original.nop_filt
        assert decoded.idle_filt == original.idle_filt
        assert decoded.data_cap == original.data_cap
        assert decoded.raw_filt == original.raw_filt
        assert decoded.cap_port_sel == original.cap_port_sel
        assert decoded.trace_point_sel == original.trace_point_sel
        assert decoded.lane_sel == original.lane_sel


class TestPostTriggerCfgReg:
    """Post-Trigger Config Register encode/decode."""

    def test_defaults(self):
        reg = PostTriggerCfgReg()
        assert reg.to_register() == 0

    def test_clock_count(self):
        reg = PostTriggerCfgReg(clock_count=0xABCD)
        assert reg.to_register() & 0xFFFF == 0xABCD

    def test_cap_count(self):
        reg = PostTriggerCfgReg(cap_count=0x7FF)
        assert (reg.to_register() >> 16) & 0x7FF == 0x7FF

    def test_count_type(self):
        reg = PostTriggerCfgReg(count_type=3)
        assert (reg.to_register() >> 30) & 0x3 == 3

    def test_roundtrip(self):
        original = PostTriggerCfgReg(
            clock_count=1000,
            cap_count=500,
            clock_cnt_mult=5,
            count_type=2,
        )
        encoded = original.to_register()
        decoded = PostTriggerCfgReg.from_register(encoded)
        assert decoded.clock_count == original.clock_count
        assert decoded.cap_count == original.cap_count
        assert decoded.clock_cnt_mult == original.clock_cnt_mult
        assert decoded.count_type == original.count_type


class TestTriggerSrcSelReg:
    """Trigger Source Select Register encode/decode."""

    def test_defaults(self):
        reg = TriggerSrcSelReg()
        assert reg.to_register() == 0

    def test_trigger_src(self):
        reg = TriggerSrcSelReg(trigger_src=42)
        assert reg.to_register() & 0x3F == 42

    def test_rearm_enable(self):
        reg = TriggerSrcSelReg(rearm_enable=True)
        assert reg.to_register() & (1 << 6)

    def test_rearm_time(self):
        reg = TriggerSrcSelReg(rearm_time=0x1000)
        assert (reg.to_register() >> 7) & 0x1FFFFFF == 0x1000

    def test_roundtrip(self):
        original = TriggerSrcSelReg(trigger_src=63, rearm_enable=True, rearm_time=999)
        encoded = original.to_register()
        decoded = TriggerSrcSelReg.from_register(encoded)
        assert decoded.trigger_src == original.trigger_src
        assert decoded.rearm_enable == original.rearm_enable
        assert decoded.rearm_time == original.rearm_time


class TestTrigCondEnableReg:
    """Trigger Condition Enable Register encode/decode."""

    def test_defaults(self):
        reg = TrigCondEnableReg()
        assert reg.to_register() == 0

    def test_raw_roundtrip(self):
        reg = TrigCondEnableReg(raw=0x00400300)
        assert reg.to_register() == 0x00400300
        decoded = TrigCondEnableReg.from_register(0x00400300)
        assert decoded.raw == 0x00400300

    def test_link_speed_bit(self):
        reg = TrigCondEnableReg(raw=(1 << 8))
        assert reg.link_speed_enb

    def test_ltssm_bit(self):
        reg = TrigCondEnableReg(raw=(1 << 21))
        assert reg.ltssm_enb

    def test_link_width_bit(self):
        reg = TrigCondEnableReg(raw=(1 << 22))
        assert reg.link_width_enb


class TestTBufAccessCtlReg:
    """Trace Buffer Access Control Register encode/decode."""

    def test_defaults(self):
        reg = TBufAccessCtlReg()
        assert reg.to_register() == 0

    def test_read_enable(self):
        reg = TBufAccessCtlReg(tbuf_read_enb=True)
        assert reg.to_register() == 1

    def test_auto_increment(self):
        reg = TBufAccessCtlReg(tbuf_read_enb=True, tbuf_addr_self_inc_enb=True)
        assert reg.to_register() == 3

    def test_roundtrip(self):
        original = TBufAccessCtlReg(tbuf_read_enb=True, tbuf_addr_self_inc_enb=True)
        decoded = TBufAccessCtlReg.from_register(original.to_register())
        assert decoded.tbuf_read_enb
        assert decoded.tbuf_addr_self_inc_enb


class TestEventCounterCfgReg:
    """Event Counter Config Register encode/decode."""

    def test_defaults(self):
        reg = EventCounterCfgReg()
        assert reg.to_register() == 0

    def test_source(self):
        reg = EventCounterCfgReg(event_source=42)
        assert reg.to_register() & 0x3F == 42

    def test_threshold(self):
        reg = EventCounterCfgReg(threshold=0xABCD)
        assert (reg.to_register() >> 16) & 0xFFFF == 0xABCD

    def test_roundtrip(self):
        original = EventCounterCfgReg(event_source=33, threshold=1000)
        decoded = EventCounterCfgReg.from_register(original.to_register())
        assert decoded.event_source == original.event_source
        assert decoded.threshold == original.threshold


class TestPortErrType:
    """Port error type IntFlag."""

    def test_has_28_bits(self):
        # All named bits should be within 28-bit range
        all_bits = 0
        for member in PortErrType:
            all_bits |= member
        assert all_bits < (1 << 28)

    def test_rcvr_err(self):
        assert PortErrType.RCVR_ERR == 1

    def test_misrouted_ide_tlp(self):
        assert PortErrType.MISROUTED_IDE_TLP == (1 << 27)

    def test_combine_flags(self):
        combined = PortErrType.BAD_TLP | PortErrType.BAD_DLLP
        assert combined == (1 << 1) | (1 << 2)


class TestConstants:
    """Module-level constants."""

    def test_tbuf_row_dwords(self):
        assert TBUF_ROW_DWORDS == 19

    def test_tbuf_max_rows(self):
        assert TBUF_MAX_ROWS == 4096

    def test_filter_dwords(self):
        assert FILTER_DWORDS == 16
