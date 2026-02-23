"""Tests for PTraceEngine domain logic.

Uses mocked SDK register I/O to verify control flow, register addresses,
and buffer read protocol without real hardware. Parameterized for both
A0 and B0 register layouts.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from calypso.core.ptrace import PTraceEngine
from calypso.hardware.ptrace_layout import LAYOUT_A0, LAYOUT_B0
from calypso.hardware.ptrace_regs import (
    TBUF_ROW_DWORDS,
    PTraceDir,
)
from calypso.models.ptrace import (
    PTraceCaptureCfg,
    PTraceConditionAttrCfg,
    PTraceConditionDataCfg,
    PTraceDirection,
    PTraceErrorTriggerCfg,
    PTraceEventCounterCfg,
    PTraceFilterControlCfg,
    PTracePostTriggerCfg,
    PTraceTriggerCfg,
    TracePointSel,
)


@pytest.fixture
def mock_device():
    return MagicMock()


@pytest.fixture
def mock_key():
    key = MagicMock()
    key.ChipID = 0x0144
    return key


@pytest.fixture
def engine_a0(mock_device, mock_key):
    with patch("calypso.core.ptrace.station_register_base", return_value=0xF00000):
        return PTraceEngine(mock_device, mock_key, port_number=5, layout=LAYOUT_A0)


@pytest.fixture
def engine_b0(mock_device, mock_key):
    with patch("calypso.core.ptrace.station_register_base", return_value=0xF00000):
        return PTraceEngine(mock_device, mock_key, port_number=5, layout=LAYOUT_B0)


class TestInit:
    """Engine initialization and port calculations."""

    def test_port_select(self, engine_a0):
        assert engine_a0._port_select == 5

    def test_station_base(self, engine_a0):
        assert engine_a0._station_base == 0xF00000

    def test_port_number(self, engine_a0):
        assert engine_a0._port_number == 5

    def test_layout_stored(self, engine_a0):
        assert engine_a0._layout is LAYOUT_A0

    def test_invalid_port_negative(self, mock_device, mock_key):
        with pytest.raises(ValueError, match="out of range"):
            PTraceEngine(mock_device, mock_key, port_number=-1)

    def test_invalid_port_too_high(self, mock_device, mock_key):
        with pytest.raises(ValueError, match="out of range"):
            PTraceEngine(mock_device, mock_key, port_number=144)

    def test_port_select_station_boundary(self, mock_device, mock_key):
        with patch("calypso.core.ptrace.station_register_base", return_value=0xF10000):
            eng = PTraceEngine(mock_device, mock_key, port_number=16, layout=LAYOUT_A0)
            assert eng._port_select == 0

    def test_port_select_last_in_station(self, mock_device, mock_key):
        with patch("calypso.core.ptrace.station_register_base", return_value=0xF00000):
            eng = PTraceEngine(mock_device, mock_key, port_number=15, layout=LAYOUT_A0)
            assert eng._port_select == 15

    def test_auto_layout_a0(self, mock_device, mock_key):
        mock_key.ChipID = 0x0144
        with patch("calypso.core.ptrace.station_register_base", return_value=0xF00000):
            eng = PTraceEngine(mock_device, mock_key, port_number=0)
            assert eng._layout is LAYOUT_A0

    def test_auto_layout_b0(self, mock_device, mock_key):
        mock_key.ChipID = 0xA080
        with patch("calypso.core.ptrace.station_register_base", return_value=0xF00000):
            eng = PTraceEngine(mock_device, mock_key, port_number=0)
            assert eng._layout is LAYOUT_B0


class TestControlA0:
    """Control methods using A0 layout offsets."""

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_enable_ingress(self, mock_write, engine_a0):
        engine_a0.enable(PTraceDirection.INGRESS)
        addr = 0xF00000 + 0x4000 + LAYOUT_A0.CAPTURE_CONTROL
        mock_write.assert_called_once_with(engine_a0._device, addr, 0x1)

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_enable_egress(self, mock_write, engine_a0):
        engine_a0.enable(PTraceDirection.EGRESS)
        addr = 0xF00000 + 0x5000 + LAYOUT_A0.CAPTURE_CONTROL
        mock_write.assert_called_once_with(engine_a0._device, addr, 0x1)

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_disable(self, mock_write, engine_a0):
        engine_a0.disable(PTraceDirection.INGRESS)
        addr = 0xF00000 + 0x4000 + LAYOUT_A0.CAPTURE_CONTROL
        mock_write.assert_called_once_with(engine_a0._device, addr, 0)

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_start_capture(self, mock_write, engine_a0):
        engine_a0.start_capture(PTraceDirection.INGRESS)
        addr = 0xF00000 + 0x4000 + LAYOUT_A0.CAPTURE_CONTROL
        mock_write.assert_called_once_with(engine_a0._device, addr, 0x101)

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_stop_capture(self, mock_write, engine_a0):
        engine_a0.stop_capture(PTraceDirection.INGRESS)
        addr = 0xF00000 + 0x4000 + LAYOUT_A0.CAPTURE_CONTROL
        mock_write.assert_called_once_with(engine_a0._device, addr, 0x201)

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_clear_triggered(self, mock_write, engine_a0):
        engine_a0.clear_triggered(PTraceDirection.INGRESS)
        addr = 0xF00000 + 0x4000 + LAYOUT_A0.CAPTURE_CONTROL
        mock_write.assert_called_once_with(engine_a0._device, addr, 0x10001)

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_manual_trigger(self, mock_write, engine_a0):
        engine_a0.manual_trigger(PTraceDirection.INGRESS)
        addr = 0xF00000 + 0x4000 + LAYOUT_A0.MANUAL_TRIGGER
        mock_write.assert_called_once_with(engine_a0._device, addr, 1)


class TestConfigureCaptureA0:
    """Capture configuration using A0 layout."""

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_basic_config(self, mock_write, engine_a0):
        cfg = PTraceCaptureCfg(
            direction=PTraceDirection.INGRESS,
            port_number=5,
            lane=3,
            trace_point=TracePointSel.DESKEW_SCRAM,
        )
        engine_a0.configure_capture(PTraceDirection.INGRESS, cfg)

        addr = 0xF00000 + 0x4000 + LAYOUT_A0.CAPTURE_CONFIG
        mock_write.assert_called_once()
        call_addr = mock_write.call_args[0][1]
        call_val = mock_write.call_args[0][2]
        assert call_addr == addr
        assert (call_val >> 8) & 0xF == 5
        assert (call_val >> 12) & 0x3 == 2
        assert (call_val >> 16) & 0xF == 3


class TestConfigureTriggerA0:
    """Trigger configuration using A0 layout (TriggerConfigReg)."""

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_a0_uses_trigger_config_reg(self, mock_write, engine_a0):
        cfg = PTraceTriggerCfg(
            trigger_src=10,
            cond0_inv=True,
            trigger_match_sel0=3,
            cond0_enable=0xABCD,
        )
        engine_a0.configure_trigger(PTraceDirection.INGRESS, cfg)

        base = 0xF00000 + 0x4000
        # First write should be to TRIGGER_CONFIG (0x020)
        first_call = mock_write.call_args_list[0]
        assert first_call[0][1] == base + LAYOUT_A0.TRIGGER_CONFIG

        # Verify TriggerConfigReg value
        trig_val = first_call[0][2]
        assert trig_val & 0x3F == 10  # trigger_src
        assert trig_val & (1 << 6)  # cond0_inv
        assert (trig_val >> 24) & 0x7 == 3  # trigger_match_sel0

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_a0_rearm_separate_register(self, mock_write, engine_a0):
        cfg = PTraceTriggerCfg(rearm_enable=True, rearm_time=1000)
        engine_a0.configure_trigger(PTraceDirection.INGRESS, cfg)

        base = 0xF00000 + 0x4000
        # Should write to REARM_TIME register (0x024)
        rearm_call = mock_write.call_args_list[1]
        assert rearm_call[0][1] == base + LAYOUT_A0.REARM_TIME
        assert rearm_call[0][2] == 1000

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_a0_cond_enable_offsets(self, mock_write, engine_a0):
        cfg = PTraceTriggerCfg(
            cond0_enable=0xDEAD,
            cond0_invert=0xBEEF,
            cond1_enable=0xCAFE,
            cond1_invert=0xF00D,
        )
        engine_a0.configure_trigger(PTraceDirection.INGRESS, cfg)

        base = 0xF00000 + 0x4000
        calls = mock_write.call_args_list
        # Cond0 enable at A0 offset 0x038
        cond0_en_call = [c for c in calls if c[0][1] == base + LAYOUT_A0.TRIG_COND0_ENABLE]
        assert len(cond0_en_call) == 1
        assert cond0_en_call[0][0][2] == 0xDEAD

        # Cond1 invert at A0 offset 0x044
        cond1_inv_call = [c for c in calls if c[0][1] == base + LAYOUT_A0.TRIG_COND1_INVERT]
        assert len(cond1_inv_call) == 1
        assert cond1_inv_call[0][0][2] == 0xF00D


class TestConfigureTriggerB0:
    """Trigger configuration using B0 layout (TriggerSrcSelReg)."""

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_b0_uses_trigger_src_sel_reg(self, mock_write, engine_b0):
        cfg = PTraceTriggerCfg(
            trigger_src=10,
            rearm_enable=True,
            rearm_time=500,
        )
        engine_b0.configure_trigger(PTraceDirection.INGRESS, cfg)

        base = 0xF00000 + 0x4000
        first_call = mock_write.call_args_list[0]
        assert first_call[0][1] == base + LAYOUT_B0.TRIGGER_CONFIG

        # TriggerSrcSelReg value: src=10, rearm=1, time=500
        val = first_call[0][2]
        assert val & 0x3F == 10
        assert val & (1 << 6)  # rearm enable
        assert (val >> 7) & 0x1FFFFFF == 500


class TestConfigurePostTrigger:
    """Post-trigger configuration register writes."""

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_post_trigger(self, mock_write, engine_a0):
        cfg = PTracePostTriggerCfg(
            clock_count=1000,
            cap_count=500,
            clock_cnt_mult=3,
            count_type=2,
        )
        engine_a0.configure_post_trigger(PTraceDirection.INGRESS, cfg)
        mock_write.assert_called_once()
        addr = mock_write.call_args[0][1]
        assert addr == 0xF00000 + 0x4000 + LAYOUT_A0.POST_TRIGGER_CFG
        call_val = mock_write.call_args[0][2]
        assert call_val & 0xFFFF == 1000
        assert (call_val >> 16) & 0x7FF == 500
        assert (call_val >> 27) & 0x7 == 3
        assert (call_val >> 30) & 0x3 == 2


class TestConfigureErrorTrigger:
    """Error trigger configuration register writes."""

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_error_mask_a0(self, mock_write, engine_a0):
        cfg = PTraceErrorTriggerCfg(error_mask=0x0ABCDEF0)
        engine_a0.configure_error_trigger(PTraceDirection.INGRESS, cfg)
        addr = 0xF00000 + 0x4000 + LAYOUT_A0.PORT_ERR_TRIG_EN
        mock_write.assert_called_once_with(engine_a0._device, addr, 0x0ABCDEF0)


class TestConfigureEventCounter:
    """Event counter configuration register writes."""

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_counter_0_a0(self, mock_write, engine_a0):
        cfg = PTraceEventCounterCfg(counter_id=0, event_source=10, threshold=500)
        engine_a0.configure_event_counter(PTraceDirection.INGRESS, cfg)
        addr = 0xF00000 + 0x4000 + LAYOUT_A0.EVT_CTR0_CFG
        mock_write.assert_called_once()
        assert mock_write.call_args[0][1] == addr

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_counter_1_a0(self, mock_write, engine_a0):
        cfg = PTraceEventCounterCfg(counter_id=1, event_source=20, threshold=1000)
        engine_a0.configure_event_counter(PTraceDirection.INGRESS, cfg)
        addr = 0xF00000 + 0x4000 + LAYOUT_A0.EVT_CTR1_CFG
        mock_write.assert_called_once()
        assert mock_write.call_args[0][1] == addr

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_counter_0_b0(self, mock_write, engine_b0):
        cfg = PTraceEventCounterCfg(counter_id=0, event_source=10, threshold=500)
        engine_b0.configure_event_counter(PTraceDirection.INGRESS, cfg)
        addr = 0xF00000 + 0x4000 + LAYOUT_B0.EVT_CTR0_CFG
        assert mock_write.call_args[0][1] == addr


class TestWriteFilter:
    """512-bit filter write operations (interleaved layout)."""

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_filter_0_writes_32_dwords(self, mock_write, engine_a0):
        match_hex = "AB" * 64
        mask_hex = "CD" * 64
        engine_a0.write_filter(PTraceDirection.INGRESS, 0, match_hex, mask_hex)
        assert mock_write.call_count == 32  # 16 match + 16 mask interleaved

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_filter_interleaved_pattern(self, mock_write, engine_a0):
        match_hex = "AA" * 64
        mask_hex = "BB" * 64
        engine_a0.write_filter(PTraceDirection.INGRESS, 0, match_hex, mask_hex)

        base = 0xF00000 + 0x4000 + LAYOUT_A0.FILTER0_BASE
        # First pair: match[0] at base+0, mask[0] at base+4
        assert mock_write.call_args_list[0][0][1] == base + 0
        assert mock_write.call_args_list[0][0][2] == 0xAAAAAAAA
        assert mock_write.call_args_list[1][0][1] == base + 4
        assert mock_write.call_args_list[1][0][2] == 0xBBBBBBBB
        # Second pair: match[1] at base+8, mask[1] at base+12
        assert mock_write.call_args_list[2][0][1] == base + 8
        assert mock_write.call_args_list[3][0][1] == base + 12

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_filter_1_address(self, mock_write, engine_a0):
        match_hex = "00" * 64
        mask_hex = "FF" * 64
        engine_a0.write_filter(PTraceDirection.INGRESS, 1, match_hex, mask_hex)
        first_call_addr = mock_write.call_args_list[0][0][1]
        expected_base = 0xF00000 + 0x4000 + LAYOUT_A0.FILTER1_BASE
        assert first_call_addr == expected_base

    def test_invalid_filter_idx(self, engine_a0):
        with pytest.raises(ValueError, match="filter_idx"):
            engine_a0.write_filter(PTraceDirection.INGRESS, 2, "0" * 128, "0" * 128)

    def test_invalid_hex_length(self, engine_a0):
        with pytest.raises(ValueError, match="128"):
            engine_a0.write_filter(PTraceDirection.INGRESS, 0, "0" * 64, "0" * 128)


class TestFilterControl:
    """Filter Control configuration (A0 only)."""

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_a0_writes_both_registers(self, mock_write, engine_a0):
        cfg = PTraceFilterControlCfg(
            dllp_type_enb=True,
            filter_src_sel=2,
            dllp_type_inv=True,
        )
        engine_a0.configure_filter_control(PTraceDirection.INGRESS, cfg)

        base = 0xF00000 + 0x4000
        assert mock_write.call_count == 2
        # FilterControl register
        assert mock_write.call_args_list[0][0][1] == base + LAYOUT_A0.FILTER_CONTROL
        # InvertFilterControl register
        assert mock_write.call_args_list[1][0][1] == base + LAYOUT_A0.FILTER_CONTROL_INV

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_b0_noop(self, mock_write, engine_b0):
        cfg = PTraceFilterControlCfg(dllp_type_enb=True)
        engine_b0.configure_filter_control(PTraceDirection.INGRESS, cfg)
        mock_write.assert_not_called()

    @patch("calypso.core.ptrace.read_mapped_register")
    def test_read_filter_control_a0(self, mock_read, engine_a0):
        mock_read.side_effect = [
            (1 << 9) | (2 << 20),  # FilterControl: dllp_type_enb + filter_src_sel=2
            (1 << 10),  # InvertFilterControl: os_type_inv
        ]
        result = engine_a0.read_filter_control(PTraceDirection.INGRESS)
        assert result.dllp_type_enb is True
        assert result.filter_src_sel == 2
        assert result.os_type_inv is True

    def test_read_filter_control_b0(self, engine_b0):
        result = engine_b0.read_filter_control(PTraceDirection.INGRESS)
        assert result.dllp_type_enb is False  # default


class TestConditionAttributes:
    """Condition attribute register writes."""

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_a0_writes_10_registers(self, mock_write, engine_a0):
        cfg = PTraceConditionAttrCfg(
            condition_id=0,
            link_speed=5,
            link_speed_mask=0xF,
        )
        engine_a0.configure_condition_attributes(PTraceDirection.INGRESS, cfg)
        # 5 attr registers x 2 (value + mask) = 10
        assert mock_write.call_count == 10

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_a0_cond0_attr2_offset(self, mock_write, engine_a0):
        cfg = PTraceConditionAttrCfg(condition_id=0, link_speed=7)
        engine_a0.configure_condition_attributes(PTraceDirection.INGRESS, cfg)

        base = 0xF00000 + 0x4000
        first_call = mock_write.call_args_list[0]
        assert first_call[0][1] == base + LAYOUT_A0.COND0_ATTR2

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_a0_cond1_attr2_offset(self, mock_write, engine_a0):
        cfg = PTraceConditionAttrCfg(condition_id=1, link_speed=7)
        engine_a0.configure_condition_attributes(PTraceDirection.INGRESS, cfg)

        base = 0xF00000 + 0x4000
        first_call = mock_write.call_args_list[0]
        assert first_call[0][1] == base + LAYOUT_A0.COND1_ATTR2

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_b0_noop(self, mock_write, engine_b0):
        cfg = PTraceConditionAttrCfg(condition_id=0, link_speed=5)
        engine_b0.configure_condition_attributes(PTraceDirection.INGRESS, cfg)
        mock_write.assert_not_called()


class TestConditionData:
    """512-bit condition data block writes."""

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_a0_writes_32_dwords(self, mock_write, engine_a0):
        cfg = PTraceConditionDataCfg(
            condition_id=0,
            match_hex="AB" * 64,
            mask_hex="CD" * 64,
        )
        engine_a0.write_condition_data(PTraceDirection.INGRESS, cfg)
        assert mock_write.call_count == 32

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_a0_cond0_base_address(self, mock_write, engine_a0):
        cfg = PTraceConditionDataCfg(condition_id=0, match_hex="0" * 128, mask_hex="0" * 128)
        engine_a0.write_condition_data(PTraceDirection.INGRESS, cfg)
        base = 0xF00000 + 0x4000 + LAYOUT_A0.COND0_DATA_BASE
        assert mock_write.call_args_list[0][0][1] == base

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_a0_cond1_base_address(self, mock_write, engine_a0):
        cfg = PTraceConditionDataCfg(condition_id=1, match_hex="0" * 128, mask_hex="0" * 128)
        engine_a0.write_condition_data(PTraceDirection.INGRESS, cfg)
        base = 0xF00000 + 0x4000 + LAYOUT_A0.COND1_DATA_BASE
        assert mock_write.call_args_list[0][0][1] == base

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_b0_noop(self, mock_write, engine_b0):
        cfg = PTraceConditionDataCfg(condition_id=0, match_hex="0" * 128, mask_hex="0" * 128)
        engine_b0.write_condition_data(PTraceDirection.INGRESS, cfg)
        mock_write.assert_not_called()


class TestFullConfigure:
    """Full configure: disable, clear, configure, re-enable."""

    @patch("calypso.core.ptrace.write_mapped_register")
    @patch("calypso.core.ptrace.read_mapped_register", return_value=0)
    def test_full_configure_sequence(self, mock_read, mock_write, engine_a0):
        capture = PTraceCaptureCfg()
        trigger = PTraceTriggerCfg()
        post_trigger = PTracePostTriggerCfg()
        engine_a0.full_configure(PTraceDirection.INGRESS, capture, trigger, post_trigger)

        assert mock_write.call_count >= 8
        ctrl_addr = 0xF00000 + 0x4000 + LAYOUT_A0.CAPTURE_CONTROL
        # First call: disable (value=0)
        assert mock_write.call_args_list[0] == call(engine_a0._device, ctrl_addr, 0)

    @patch("calypso.core.ptrace.write_mapped_register")
    @patch("calypso.core.ptrace.read_mapped_register", return_value=0)
    def test_full_configure_with_filter_control(self, mock_read, mock_write, engine_a0):
        capture = PTraceCaptureCfg()
        trigger = PTraceTriggerCfg()
        post_trigger = PTracePostTriggerCfg()
        fctl = PTraceFilterControlCfg(dllp_type_enb=True)
        engine_a0.full_configure(
            PTraceDirection.INGRESS, capture, trigger, post_trigger,
            filter_control=fctl,
        )

        base = 0xF00000 + 0x4000
        filter_ctl_calls = [
            c for c in mock_write.call_args_list
            if c[0][1] == base + LAYOUT_A0.FILTER_CONTROL
        ]
        assert len(filter_ctl_calls) == 1

    @patch("calypso.core.ptrace.write_mapped_register")
    @patch("calypso.core.ptrace.read_mapped_register", return_value=0)
    def test_full_configure_with_condition_attrs(self, mock_read, mock_write, engine_a0):
        capture = PTraceCaptureCfg()
        trigger = PTraceTriggerCfg()
        post_trigger = PTracePostTriggerCfg()
        attrs = [PTraceConditionAttrCfg(condition_id=0, link_speed=5)]
        engine_a0.full_configure(
            PTraceDirection.INGRESS, capture, trigger, post_trigger,
            condition_attrs=attrs,
        )

        base = 0xF00000 + 0x4000
        cond0_calls = [
            c for c in mock_write.call_args_list
            if c[0][1] == base + LAYOUT_A0.COND0_ATTR2
        ]
        assert len(cond0_calls) == 1


class TestReadStatus:
    """Status readback including timestamps — A0 offsets."""

    @patch("calypso.core.ptrace.read_mapped_register")
    def test_read_status_a0(self, mock_read, engine_a0):
        mock_read.side_effect = [
            0x80000301,  # status
            0x00001000,  # start_ts_low
            0x00000001,  # start_ts_high
            0x00003000,  # trig_ts_low
            0x00000003,  # trig_ts_high
            0x00004000,  # last_ts_low
            0x00000004,  # last_ts_high
            0x00005000,  # global_timer_low
            0x00000005,  # global_timer_high
            42,           # trigger_row_addr
            0x0000000F,  # port_err_status
        ]
        status = engine_a0.read_status(PTraceDirection.INGRESS)
        assert status.capture_in_progress
        assert status.triggered
        assert status.tbuf_wrapped
        assert status.ram_init_done
        assert status.start_ts == (1 << 32) | 0x1000
        assert status.trigger_ts == (3 << 32) | 0x3000
        assert status.last_ts == (4 << 32) | 0x4000
        assert status.global_timer == (5 << 32) | 0x5000
        assert status.trigger_row_addr == 42
        assert status.port_err_status == 0x0F

    @patch("calypso.core.ptrace.read_mapped_register")
    def test_read_status_uses_layout_offsets(self, mock_read, engine_a0):
        mock_read.return_value = 0
        engine_a0.read_status(PTraceDirection.INGRESS)

        base = 0xF00000 + 0x4000
        read_addrs = [c[0][1] for c in mock_read.call_args_list]
        assert base + LAYOUT_A0.CAPTURE_STATUS in read_addrs
        assert base + LAYOUT_A0.START_TS_LOW in read_addrs
        assert base + LAYOUT_A0.TRIGGER_TS_LOW in read_addrs
        assert base + LAYOUT_A0.LAST_TS_LOW in read_addrs
        assert base + LAYOUT_A0.GLOBAL_TIMER_LOW in read_addrs
        assert base + LAYOUT_A0.TRIGGER_ADDRESS in read_addrs
        assert base + LAYOUT_A0.PORT_ERR_STATUS in read_addrs


class TestReadBuffer:
    """Trace buffer read protocol."""

    @patch("calypso.core.ptrace.write_mapped_register")
    @patch("calypso.core.ptrace.read_mapped_register")
    def test_read_buffer_protocol(self, mock_read, mock_write, engine_a0):
        status_vals = [0] * 11
        row_vals = list(range(TBUF_ROW_DWORDS)) * 2
        mock_read.side_effect = status_vals + row_vals

        result = engine_a0.read_buffer(PTraceDirection.INGRESS, max_rows=2)

        assert len(result.rows) == 2
        assert result.rows[0].row_index == 0
        assert result.rows[1].row_index == 1
        assert len(result.rows[0].dwords) == TBUF_ROW_DWORDS
        assert result.total_rows_read == 2

    @patch("calypso.core.ptrace.write_mapped_register")
    @patch("calypso.core.ptrace.read_mapped_register")
    def test_buffer_access_released_on_success(self, mock_read, mock_write, engine_a0):
        mock_read.return_value = 0
        engine_a0.read_buffer(PTraceDirection.INGRESS, max_rows=1)

        last_write = mock_write.call_args_list[-1]
        tbuf_ctl_addr = 0xF00000 + 0x4000 + LAYOUT_A0.TBUF_ACCESS_CTL
        assert last_write == call(engine_a0._device, tbuf_ctl_addr, 0)

    @patch("calypso.core.ptrace.write_mapped_register")
    @patch("calypso.core.ptrace.read_mapped_register")
    def test_buffer_access_released_on_error(self, mock_read, mock_write, engine_a0):
        mock_read.side_effect = [0] * 11 + [Exception("HW error")]

        with pytest.raises(Exception, match="HW error"):
            engine_a0.read_buffer(PTraceDirection.INGRESS, max_rows=1)

        last_write = mock_write.call_args_list[-1]
        tbuf_ctl_addr = 0xF00000 + 0x4000 + LAYOUT_A0.TBUF_ACCESS_CTL
        assert last_write == call(engine_a0._device, tbuf_ctl_addr, 0)

    @patch("calypso.core.ptrace.write_mapped_register")
    @patch("calypso.core.ptrace.read_mapped_register")
    def test_hex_str_format(self, mock_read, mock_write, engine_a0):
        status_vals = [0] * 11
        row_vals = [0xDEADBEEF] + [0] * 18
        mock_read.side_effect = status_vals + row_vals

        result = engine_a0.read_buffer(PTraceDirection.INGRESS, max_rows=1)
        assert result.rows[0].hex_str.startswith("DEADBEEF")
