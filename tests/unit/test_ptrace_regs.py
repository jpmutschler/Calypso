"""Tests for PTrace hardware register definitions.

Tests encode/decode round-trip for all register dataclasses,
address calculation helpers, enum completeness, variant layouts,
and new Flit mode dataclasses.
"""

from __future__ import annotations

import pytest

from calypso.hardware.ptrace_layout import (
    LAYOUT_A0,
    LAYOUT_B0,
    PTraceRegLayout,
    get_ptrace_layout,
)
from calypso.hardware.ptrace_cond_regs import (
    CondAttr2Reg,
    CondAttr3Reg,
    CondAttr4Reg,
    CondAttr5Reg,
    CondAttr6Reg,
)
from calypso.hardware.ptrace_regs import (
    DATA_BLOCK_DWORDS,
    FILTER_DWORDS,
    TBUF_MAX_ROWS,
    TBUF_ROW_DWORDS,
    CaptureConfigReg,
    CaptureControlReg,
    CaptureStatusReg,
    EventCounterCfgReg,
    EventCounterThresholdReg,
    FilterControlReg,
    FilterSrcSel,
    FlitMatchSel,
    InvertFilterControlReg,
    PortErrType,
    PostTriggerCfgReg,
    PTraceDir,
    RearmTimeReg,
    TBufAccessCtlReg,
    TrigCondEnableReg,
    TriggerConfigReg,
    TriggerSrcId,
    TriggerSrcSelReg,
    ptrace_addr,
    tbuf_data_offset,
    PORT_ERR_NAMES,
)


class TestPTraceDir:
    """Direction enum values."""

    def test_ingress_offset(self):
        assert PTraceDir.INGRESS == 0x4000

    def test_egress_offset(self):
        assert PTraceDir.EGRESS == 0x5000


class TestPTraceAddr:
    """Absolute address calculation."""

    def test_basic_address(self):
        result = ptrace_addr(0xF00000, PTraceDir.INGRESS, 0x000)
        assert result == 0xF00000 + 0x4000 + 0x000

    def test_egress_address(self):
        result = ptrace_addr(0xF10000, PTraceDir.EGRESS, 0x004)
        assert result == 0xF10000 + 0x5000 + 0x004

    def test_filter_address(self):
        result = ptrace_addr(0xF00000, PTraceDir.INGRESS, LAYOUT_A0.FILTER0_BASE)
        assert result == 0xF00000 + 0x4000 + 0x200


class TestTBufDataOffset:
    """Trace buffer data DWORD offset calculation."""

    def test_first_dword(self):
        assert tbuf_data_offset(0x188, 0) == 0x188

    def test_last_dword(self):
        assert tbuf_data_offset(0x188, 18) == 0x188 + 18 * 4

    def test_sequential_offsets(self):
        for i in range(TBUF_ROW_DWORDS):
            offset = tbuf_data_offset(0x188, i)
            assert offset == 0x188 + (i * 4)

    def test_out_of_range(self):
        with pytest.raises(ValueError, match="dword_index"):
            tbuf_data_offset(0x188, 19)

    def test_negative(self):
        with pytest.raises(ValueError, match="dword_index"):
            tbuf_data_offset(0x188, -1)


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
        assert val & (1 << 0)
        assert val & (1 << 16)

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
        assert val & (1 << 1)
        assert val & (1 << 2)
        assert val & (1 << 3)
        assert val & (1 << 4)
        assert val & (1 << 5)

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


class TestTriggerConfigReg:
    """A0 Trigger Config Register encode/decode."""

    def test_defaults(self):
        reg = TriggerConfigReg()
        assert reg.to_register() == 0

    def test_trigger_src(self):
        reg = TriggerConfigReg(trigger_src=42)
        assert reg.to_register() & 0x3F == 42

    def test_cond0_inv(self):
        reg = TriggerConfigReg(cond0_inv=True)
        assert reg.to_register() & (1 << 6)

    def test_cond1_inv(self):
        reg = TriggerConfigReg(cond1_inv=True)
        assert reg.to_register() & (1 << 7)

    def test_trigger_match_sel0(self):
        reg = TriggerConfigReg(trigger_match_sel0=5)
        assert (reg.to_register() >> 24) & 0x7 == 5

    def test_trigger_match_sel1(self):
        reg = TriggerConfigReg(trigger_match_sel1=7)
        assert (reg.to_register() >> 28) & 0x7 == 7

    def test_roundtrip(self):
        original = TriggerConfigReg(
            trigger_src=10,
            cond0_inv=True,
            cond1_inv=False,
            trigger_match_sel0=3,
            trigger_match_sel1=6,
        )
        encoded = original.to_register()
        decoded = TriggerConfigReg.from_register(encoded)
        assert decoded.trigger_src == original.trigger_src
        assert decoded.cond0_inv == original.cond0_inv
        assert decoded.cond1_inv == original.cond1_inv
        assert decoded.trigger_match_sel0 == original.trigger_match_sel0
        assert decoded.trigger_match_sel1 == original.trigger_match_sel1


class TestTriggerSrcSelReg:
    """B0 Trigger Source Select Register encode/decode."""

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


class TestRearmTimeReg:
    """A0 ReArm Time Register encode/decode."""

    def test_defaults(self):
        reg = RearmTimeReg()
        assert reg.to_register() == 0

    def test_time_value(self):
        reg = RearmTimeReg(rearm_time=0xABCDEF)
        assert reg.to_register() == 0xABCDEF

    def test_mask_24bit(self):
        reg = RearmTimeReg(rearm_time=0xFFFFFFFF)
        assert reg.to_register() == 0xFFFFFF

    def test_roundtrip(self):
        original = RearmTimeReg(rearm_time=12345)
        decoded = RearmTimeReg.from_register(original.to_register())
        assert decoded.rearm_time == 12345


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


class TestFilterControlReg:
    """Filter Control Register (A0 only) encode/decode."""

    def test_defaults(self):
        reg = FilterControlReg()
        assert reg.to_register() == 0

    def test_dllp_type_enb(self):
        reg = FilterControlReg(dllp_type_enb=True)
        assert reg.to_register() & (1 << 9)

    def test_os_type_enb(self):
        reg = FilterControlReg(os_type_enb=True)
        assert reg.to_register() & (1 << 10)

    def test_cxl_filters(self):
        reg = FilterControlReg(
            cxl_io_filter_enb=True,
            cxl_cache_filter_enb=True,
            cxl_mem_filter_enb=True,
        )
        val = reg.to_register()
        assert val & (1 << 11)
        assert val & (1 << 12)
        assert val & (1 << 13)

    def test_filter_256b(self):
        reg = FilterControlReg(filter_256b_enb=True)
        assert reg.to_register() & (1 << 14)

    def test_filter_src_sel(self):
        reg = FilterControlReg(filter_src_sel=5)
        assert (reg.to_register() >> 20) & 0x7 == 5

    def test_filter_match_sel0(self):
        reg = FilterControlReg(filter_match_sel0=3)
        assert (reg.to_register() >> 24) & 0x7 == 3

    def test_filter_match_sel1(self):
        reg = FilterControlReg(filter_match_sel1=7)
        assert (reg.to_register() >> 28) & 0x7 == 7

    def test_roundtrip(self):
        original = FilterControlReg(
            dllp_type_enb=True,
            os_type_enb=True,
            cxl_io_filter_enb=True,
            filter_256b_enb=True,
            filter_src_sel=2,
            filter_match_sel0=4,
            filter_match_sel1=6,
        )
        encoded = original.to_register()
        decoded = FilterControlReg.from_register(encoded)
        assert decoded.dllp_type_enb == original.dllp_type_enb
        assert decoded.os_type_enb == original.os_type_enb
        assert decoded.cxl_io_filter_enb == original.cxl_io_filter_enb
        assert decoded.filter_256b_enb == original.filter_256b_enb
        assert decoded.filter_src_sel == original.filter_src_sel
        assert decoded.filter_match_sel0 == original.filter_match_sel0
        assert decoded.filter_match_sel1 == original.filter_match_sel1


class TestInvertFilterControlReg:
    """Invert Filter Control Register (A0 only) encode/decode."""

    def test_defaults(self):
        reg = InvertFilterControlReg()
        assert reg.to_register() == 0

    def test_dllp_type_inv(self):
        reg = InvertFilterControlReg(dllp_type_inv=True)
        assert reg.to_register() & (1 << 9)

    def test_os_type_inv(self):
        reg = InvertFilterControlReg(os_type_inv=True)
        assert reg.to_register() & (1 << 10)

    def test_roundtrip(self):
        original = InvertFilterControlReg(dllp_type_inv=True, os_type_inv=True)
        decoded = InvertFilterControlReg.from_register(original.to_register())
        assert decoded.dllp_type_inv
        assert decoded.os_type_inv


class TestCondAttr2Reg:
    """Condition Attribute 2 Register encode/decode."""

    def test_defaults(self):
        reg = CondAttr2Reg()
        assert reg.to_register() == 0

    def test_link_speed(self):
        reg = CondAttr2Reg(link_speed=0xA)
        assert (reg.to_register() >> 8) & 0xF == 0xA

    def test_link_width(self):
        reg = CondAttr2Reg(link_width=5)
        assert (reg.to_register() >> 12) & 0x7 == 5

    def test_dllp_type(self):
        reg = CondAttr2Reg(dllp_type=0xAB)
        assert (reg.to_register() >> 16) & 0xFF == 0xAB

    def test_os_type(self):
        reg = CondAttr2Reg(os_type=0xCD)
        assert (reg.to_register() >> 24) & 0xFF == 0xCD

    def test_roundtrip(self):
        original = CondAttr2Reg(link_speed=7, link_width=3, dllp_type=0x42, os_type=0xAB)
        decoded = CondAttr2Reg.from_register(original.to_register())
        assert decoded.link_speed == original.link_speed
        assert decoded.link_width == original.link_width
        assert decoded.dllp_type == original.dllp_type
        assert decoded.os_type == original.os_type


class TestCondAttr3Reg:
    """Condition Attribute 3 Register encode/decode."""

    def test_roundtrip(self):
        original = CondAttr3Reg(symbol0=0x11, symbol1=0x22, symbol2=0x33, symbol3=0x44)
        decoded = CondAttr3Reg.from_register(original.to_register())
        assert decoded.symbol0 == 0x11
        assert decoded.symbol1 == 0x22
        assert decoded.symbol2 == 0x33
        assert decoded.symbol3 == 0x44


class TestCondAttr4Reg:
    """Condition Attribute 4 Register encode/decode."""

    def test_roundtrip(self):
        original = CondAttr4Reg(symbol4=0xAA, symbol5=0xBB, symbol6=0xCC, symbol7=0xDD)
        decoded = CondAttr4Reg.from_register(original.to_register())
        assert decoded.symbol4 == 0xAA
        assert decoded.symbol5 == 0xBB
        assert decoded.symbol6 == 0xCC
        assert decoded.symbol7 == 0xDD


class TestCondAttr5Reg:
    """Condition Attribute 5 Register encode/decode."""

    def test_roundtrip(self):
        original = CondAttr5Reg(symbol8=0x11, symbol9=0x22, dlp0=0x33, dlp1=0x44)
        decoded = CondAttr5Reg.from_register(original.to_register())
        assert decoded.symbol8 == 0x11
        assert decoded.symbol9 == 0x22
        assert decoded.dlp0 == 0x33
        assert decoded.dlp1 == 0x44


class TestCondAttr6Reg:
    """Condition Attribute 6 Register encode/decode."""

    def test_defaults(self):
        reg = CondAttr6Reg()
        assert reg.to_register() == 0

    def test_ltssm_state_9bit(self):
        reg = CondAttr6Reg(ltssm_state=0x1FF)
        assert reg.to_register() & 0xFFF == 0x1FF

    def test_ltssm_state_12bit(self):
        """Full 12-bit LTSSM values (e.g. 0x301 = L0 sub-1) must survive."""
        reg = CondAttr6Reg(ltssm_state=0x301)
        assert reg.to_register() & 0xFFF == 0x301

    def test_ltssm_state_12bit_max(self):
        """Maximum 12-bit LTSSM value must survive roundtrip."""
        reg = CondAttr6Reg(ltssm_state=0xFFF)
        decoded = CondAttr6Reg.from_register(reg.to_register())
        assert decoded.ltssm_state == 0xFFF

    def test_ltssm_state_truncates_above_12bit(self):
        """Values above 12-bit should be masked, not leak into reserved bits."""
        reg = CondAttr6Reg(ltssm_state=0x1FFF)
        assert reg.to_register() & 0xFFF == 0xFFF
        assert reg.to_register() & (1 << 12) == 0

    def test_flit_mode(self):
        reg = CondAttr6Reg(flit_mode=True)
        assert reg.to_register() & (1 << 16)

    def test_cxl_mode(self):
        reg = CondAttr6Reg(cxl_mode=True)
        assert reg.to_register() & (1 << 17)

    def test_roundtrip(self):
        original = CondAttr6Reg(ltssm_state=0x123, flit_mode=True, cxl_mode=True)
        decoded = CondAttr6Reg.from_register(original.to_register())
        assert decoded.ltssm_state == original.ltssm_state
        assert decoded.flit_mode == original.flit_mode
        assert decoded.cxl_mode == original.cxl_mode


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
    """Event Counter Config Register — source only (threshold is separate)."""

    def test_defaults(self):
        reg = EventCounterCfgReg()
        assert reg.to_register() == 0

    def test_source(self):
        reg = EventCounterCfgReg(event_source=42)
        assert reg.to_register() & 0x3F == 42

    def test_source_roundtrip(self):
        original = EventCounterCfgReg(event_source=33)
        decoded = EventCounterCfgReg.from_register(original.to_register())
        assert decoded.event_source == original.event_source

    def test_source_only_no_high_bits(self):
        """CFG register should only use bits [5:0], no threshold bits."""
        reg = EventCounterCfgReg(event_source=63)
        assert reg.to_register() == 63


class TestEventCounterThresholdReg:
    """Event Counter Threshold Register — separate from CFG."""

    def test_defaults(self):
        reg = EventCounterThresholdReg()
        assert reg.to_register() == 0

    def test_threshold(self):
        reg = EventCounterThresholdReg(threshold=0xABCD)
        assert reg.to_register() == 0xABCD

    def test_roundtrip(self):
        original = EventCounterThresholdReg(threshold=1000)
        decoded = EventCounterThresholdReg.from_register(original.to_register())
        assert decoded.threshold == original.threshold

    def test_threshold_truncates_above_16bit(self):
        reg = EventCounterThresholdReg(threshold=0x1FFFF)
        assert reg.to_register() == 0xFFFF


class TestPortErrType:
    """Port error type IntFlag — updated for RD101 p270."""

    def test_has_28_bits(self):
        all_bits = 0
        for member in PortErrType:
            all_bits |= member
        assert all_bits < (1 << 28)

    def test_rcvr_err(self):
        assert PortErrType.RCVR_ERR == 1

    def test_fec_uncorrectable(self):
        assert PortErrType.FEC_UNCORRECTABLE == (1 << 27)

    def test_dpc_triggered(self):
        assert PortErrType.DPC_TRIGGERED == (1 << 22)

    def test_framing_error(self):
        assert PortErrType.FRAMING_ERROR == (1 << 25)

    def test_fec_correctable(self):
        assert PortErrType.FEC_CORRECTABLE == (1 << 26)

    def test_combine_flags(self):
        combined = PortErrType.BAD_TLP | PortErrType.BAD_DLLP
        assert combined == (1 << 1) | (1 << 2)

    def test_port_err_names_match_enum_count(self):
        assert len(PORT_ERR_NAMES) == 28

    def test_port_err_names_updated_bits(self):
        assert PORT_ERR_NAMES[21] == "Poisoned TLP Egress Blocked"
        assert PORT_ERR_NAMES[22] == "DPC Triggered"
        assert PORT_ERR_NAMES[23] == "Surprise Down Error"
        assert PORT_ERR_NAMES[24] == "Translation Egress Block"
        assert PORT_ERR_NAMES[25] == "Framing Error"
        assert PORT_ERR_NAMES[26] == "FEC Correctable"
        assert PORT_ERR_NAMES[27] == "FEC Uncorrectable"


class TestEnums:
    """New enums: TriggerSrcId, FlitMatchSel, FilterSrcSel."""

    def test_trigger_src_manual(self):
        assert TriggerSrcId.MANUAL == 0

    def test_trigger_src_port_error(self):
        assert TriggerSrcId.PORT_ERROR == 0x3D

    def test_trigger_src_cond0_then_cond1(self):
        assert TriggerSrcId.COND0_THEN_COND1 == 0x06

    def test_flit_match_all(self):
        assert FlitMatchSel.MATCH_ALL == 0

    def test_flit_match_h_or_g(self):
        assert FlitMatchSel.MATCH_H_OR_G == 7

    def test_filter_src_sel_values(self):
        assert FilterSrcSel.FILTER0_ONLY == 0
        assert FilterSrcSel.FILTER1_ONLY == 1
        assert FilterSrcSel.NOT_FILTER0 == 4


class TestConstants:
    """Module-level constants."""

    def test_tbuf_row_dwords(self):
        assert TBUF_ROW_DWORDS == 19

    def test_tbuf_max_rows(self):
        assert TBUF_MAX_ROWS == 4096

    def test_filter_dwords(self):
        assert FILTER_DWORDS == 16

    def test_data_block_dwords(self):
        assert DATA_BLOCK_DWORDS == 16


class TestPTraceRegLayout:
    """Variant-aware register layout instances."""

    def test_a0_layout_is_frozen(self):
        with pytest.raises(AttributeError):
            LAYOUT_A0.CAPTURE_CONTROL = 0xFF  # type: ignore[misc]

    def test_b0_layout_is_frozen(self):
        with pytest.raises(AttributeError):
            LAYOUT_B0.CAPTURE_CONTROL = 0xFF  # type: ignore[misc]

    def test_a0_capture_control(self):
        assert LAYOUT_A0.CAPTURE_CONTROL == 0x000

    def test_a0_manual_trigger(self):
        assert LAYOUT_A0.MANUAL_TRIGGER == 0x014

    def test_a0_trigger_config(self):
        assert LAYOUT_A0.TRIGGER_CONFIG == 0x020

    def test_a0_rearm_time(self):
        assert LAYOUT_A0.REARM_TIME == 0x024

    def test_a0_trig_cond0_enable(self):
        assert LAYOUT_A0.TRIG_COND0_ENABLE == 0x038

    def test_a0_evt_ctr0_cfg(self):
        assert LAYOUT_A0.EVT_CTR0_CFG == 0x100

    def test_a0_port_err_status(self):
        assert LAYOUT_A0.PORT_ERR_STATUS == 0x144

    def test_a0_start_ts_low(self):
        assert LAYOUT_A0.START_TS_LOW == 0x130

    def test_a0_trigger_ts_low(self):
        assert LAYOUT_A0.TRIGGER_TS_LOW == 0x120

    def test_a0_last_ts_low(self):
        assert LAYOUT_A0.LAST_TS_LOW == 0x170

    def test_a0_global_timer_low(self):
        assert LAYOUT_A0.GLOBAL_TIMER_LOW == 0x138

    def test_a0_filter0_base(self):
        assert LAYOUT_A0.FILTER0_BASE == 0x200

    def test_a0_cond0_data_base(self):
        assert LAYOUT_A0.COND0_DATA_BASE == 0x300

    def test_a0_feature_flags(self):
        assert LAYOUT_A0.has_filter_control is True
        assert LAYOUT_A0.has_flit_match_sel is True
        assert LAYOUT_A0.has_condition_data is True
        assert LAYOUT_A0.interleaved_filter_layout is True

    def test_b0_manual_trigger(self):
        assert LAYOUT_B0.MANUAL_TRIGGER == 0x024

    def test_b0_trig_cond0_enable(self):
        assert LAYOUT_B0.TRIG_COND0_ENABLE == 0x028

    def test_b0_evt_ctr0_cfg(self):
        assert LAYOUT_B0.EVT_CTR0_CFG == 0x160

    def test_b0_port_err_status(self):
        assert LAYOUT_B0.PORT_ERR_STATUS == 0x100

    def test_b0_feature_flags(self):
        assert LAYOUT_B0.has_filter_control is False
        assert LAYOUT_B0.has_flit_match_sel is False
        assert LAYOUT_B0.has_condition_data is False

    def test_a0_no_offset_overlaps_in_key_regs(self):
        key_offsets = [
            LAYOUT_A0.CAPTURE_CONTROL,
            LAYOUT_A0.CAPTURE_STATUS,
            LAYOUT_A0.CAPTURE_CONFIG,
            LAYOUT_A0.MANUAL_TRIGGER,
            LAYOUT_A0.TRIGGER_CONFIG,
            LAYOUT_A0.REARM_TIME,
            LAYOUT_A0.TRIG_COND0_ENABLE,
            LAYOUT_A0.TRIG_COND1_ENABLE,
            LAYOUT_A0.EVT_CTR0_CFG,
            LAYOUT_A0.EVT_CTR1_CFG,
            LAYOUT_A0.PORT_ERR_STATUS,
            LAYOUT_A0.PORT_ERR_TRIG_EN,
            LAYOUT_A0.TBUF_ACCESS_CTL,
        ]
        assert len(key_offsets) == len(set(key_offsets))


class TestGetPTraceLayout:
    """Layout selection by chip ID."""

    def test_a0_chip_0x0144(self):
        assert get_ptrace_layout(0x0144) is LAYOUT_A0

    def test_a0_chip_0x0080(self):
        assert get_ptrace_layout(0x0080) is LAYOUT_A0

    def test_b0_chip_0xA024(self):
        assert get_ptrace_layout(0xA024) is LAYOUT_B0

    def test_b0_chip_0xA080(self):
        assert get_ptrace_layout(0xA080) is LAYOUT_B0

    def test_b0_chip_0xA096(self):
        assert get_ptrace_layout(0xA096) is LAYOUT_B0

    def test_unknown_defaults_to_a0(self):
        assert get_ptrace_layout(0x9999) is LAYOUT_A0

    def test_zero_defaults_to_a0(self):
        assert get_ptrace_layout(0) is LAYOUT_A0
