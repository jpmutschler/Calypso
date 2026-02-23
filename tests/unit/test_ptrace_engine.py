"""Tests for PTraceEngine domain logic.

Uses mocked SDK register I/O to verify control flow, register addresses,
and buffer read protocol without real hardware.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from calypso.core.ptrace import PTraceEngine
from calypso.hardware.ptrace_regs import (
    TBUF_ROW_DWORDS,
    PTraceDir,
    PTraceReg,
)
from calypso.models.ptrace import (
    PTraceCaptureCfg,
    PTraceDirection,
    PTraceErrorTriggerCfg,
    PTraceEventCounterCfg,
    PTracePostTriggerCfg,
    PTraceTriggerCfg,
    TracePointSel,
)


@pytest.fixture
def mock_device():
    return MagicMock()


@pytest.fixture
def mock_key():
    return MagicMock()


@pytest.fixture
def engine(mock_device, mock_key):
    with patch("calypso.core.ptrace.station_register_base", return_value=0xF00000):
        return PTraceEngine(mock_device, mock_key, port_number=5)


class TestInit:
    """Engine initialization and port calculations."""

    def test_port_select(self, engine):
        assert engine._port_select == 5

    def test_station_base(self, engine):
        assert engine._station_base == 0xF00000

    def test_port_number(self, engine):
        assert engine._port_number == 5

    def test_invalid_port_negative(self, mock_device, mock_key):
        with pytest.raises(ValueError, match="out of range"):
            PTraceEngine(mock_device, mock_key, port_number=-1)

    def test_invalid_port_too_high(self, mock_device, mock_key):
        with pytest.raises(ValueError, match="out of range"):
            PTraceEngine(mock_device, mock_key, port_number=144)

    def test_port_select_station_boundary(self, mock_device, mock_key):
        with patch("calypso.core.ptrace.station_register_base", return_value=0xF10000):
            eng = PTraceEngine(mock_device, mock_key, port_number=16)
            assert eng._port_select == 0

    def test_port_select_last_in_station(self, mock_device, mock_key):
        with patch("calypso.core.ptrace.station_register_base", return_value=0xF00000):
            eng = PTraceEngine(mock_device, mock_key, port_number=15)
            assert eng._port_select == 15


class TestControl:
    """Control methods: enable, disable, start, stop, clear, trigger."""

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_enable_ingress(self, mock_write, engine):
        engine.enable(PTraceDirection.INGRESS)
        addr = 0xF00000 + 0x4000 + 0x000
        mock_write.assert_called_once_with(engine._device, addr, 0x1)

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_enable_egress(self, mock_write, engine):
        engine.enable(PTraceDirection.EGRESS)
        addr = 0xF00000 + 0x5000 + 0x000
        mock_write.assert_called_once_with(engine._device, addr, 0x1)

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_disable(self, mock_write, engine):
        engine.disable(PTraceDirection.INGRESS)
        addr = 0xF00000 + 0x4000 + 0x000
        mock_write.assert_called_once_with(engine._device, addr, 0)

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_start_capture(self, mock_write, engine):
        engine.start_capture(PTraceDirection.INGRESS)
        addr = 0xF00000 + 0x4000 + 0x000
        expected_val = 0x101  # PTraceEnable=1, CaptureStart=1
        mock_write.assert_called_once_with(engine._device, addr, expected_val)

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_stop_capture(self, mock_write, engine):
        engine.stop_capture(PTraceDirection.INGRESS)
        addr = 0xF00000 + 0x4000 + 0x000
        expected_val = 0x201  # PTraceEnable=1, ManCaptureStop=1
        mock_write.assert_called_once_with(engine._device, addr, expected_val)

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_clear_triggered(self, mock_write, engine):
        engine.clear_triggered(PTraceDirection.INGRESS)
        addr = 0xF00000 + 0x4000 + 0x000
        expected_val = 0x10001  # PTraceEnable=1, ClearTriggered=1
        mock_write.assert_called_once_with(engine._device, addr, expected_val)

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_manual_trigger(self, mock_write, engine):
        engine.manual_trigger(PTraceDirection.INGRESS)
        addr = 0xF00000 + 0x4000 + int(PTraceReg.MANUAL_TRIGGER)
        mock_write.assert_called_once_with(engine._device, addr, 1)


class TestConfigureCapture:
    """Capture configuration register writes."""

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_basic_config(self, mock_write, engine):
        cfg = PTraceCaptureCfg(
            direction=PTraceDirection.INGRESS,
            port_number=5,
            lane=3,
            trace_point=TracePointSel.DESKEW_SCRAM,
        )
        engine.configure_capture(PTraceDirection.INGRESS, cfg)

        addr = 0xF00000 + 0x4000 + int(PTraceReg.CAPTURE_CONFIG)
        mock_write.assert_called_once()
        call_addr, call_val = mock_write.call_args[0][1], mock_write.call_args[0][2]
        assert call_addr == addr
        # port_select=5 at bits [11:8], trace_point=2 at [13:12], lane=3 at [19:16]
        assert (call_val >> 8) & 0xF == 5
        assert (call_val >> 12) & 0x3 == 2
        assert (call_val >> 16) & 0xF == 3

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_filter_flags(self, mock_write, engine):
        cfg = PTraceCaptureCfg(
            filter_en=True,
            compress_en=True,
            nop_filt=True,
            idle_filt=True,
        )
        engine.configure_capture(PTraceDirection.INGRESS, cfg)
        call_val = mock_write.call_args[0][2]
        assert call_val & (1 << 1)  # FilterEn
        assert call_val & (1 << 2)  # CompressEn
        assert call_val & (1 << 3)  # NopFilt
        assert call_val & (1 << 4)  # IdleFilt


class TestConfigureTrigger:
    """Trigger configuration register writes."""

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_writes_all_registers(self, mock_write, engine):
        cfg = PTraceTriggerCfg(
            trigger_src=10,
            rearm_enable=True,
            cond0_enable=0xABCD,
            cond0_invert=0x1234,
            cond1_enable=0x5678,
            cond1_invert=0x9ABC,
        )
        engine.configure_trigger(PTraceDirection.INGRESS, cfg)
        assert mock_write.call_count == 5  # src + 4 cond registers

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_cond_values(self, mock_write, engine):
        cfg = PTraceTriggerCfg(
            cond0_enable=0xDEAD,
            cond0_invert=0xBEEF,
            cond1_enable=0xCAFE,
            cond1_invert=0xF00D,
        )
        engine.configure_trigger(PTraceDirection.INGRESS, cfg)
        calls = mock_write.call_args_list
        base = 0xF00000 + 0x4000
        # Check cond0 enable
        assert calls[1] == call(
            engine._device, base + int(PTraceReg.TRIG_COND0_ENABLE), 0xDEAD
        )
        # Check cond1 invert
        assert calls[4] == call(
            engine._device, base + int(PTraceReg.TRIG_COND1_INVERT), 0xF00D
        )


class TestConfigurePostTrigger:
    """Post-trigger configuration register writes."""

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_post_trigger(self, mock_write, engine):
        cfg = PTracePostTriggerCfg(
            clock_count=1000,
            cap_count=500,
            clock_cnt_mult=3,
            count_type=2,
        )
        engine.configure_post_trigger(PTraceDirection.INGRESS, cfg)
        mock_write.assert_called_once()
        call_val = mock_write.call_args[0][2]
        assert call_val & 0xFFFF == 1000
        assert (call_val >> 16) & 0x7FF == 500
        assert (call_val >> 27) & 0x7 == 3
        assert (call_val >> 30) & 0x3 == 2


class TestConfigureErrorTrigger:
    """Error trigger configuration register writes."""

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_error_mask(self, mock_write, engine):
        cfg = PTraceErrorTriggerCfg(error_mask=0x0ABCDEF0)
        engine.configure_error_trigger(PTraceDirection.INGRESS, cfg)
        addr = 0xF00000 + 0x4000 + int(PTraceReg.PORT_ERR_TRIG_EN)
        mock_write.assert_called_once_with(engine._device, addr, 0x0ABCDEF0)


class TestConfigureEventCounter:
    """Event counter configuration register writes."""

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_counter_0(self, mock_write, engine):
        cfg = PTraceEventCounterCfg(counter_id=0, event_source=10, threshold=500)
        engine.configure_event_counter(PTraceDirection.INGRESS, cfg)
        addr = 0xF00000 + 0x4000 + int(PTraceReg.EVT_CTR0_CFG)
        mock_write.assert_called_once()
        assert mock_write.call_args[0][1] == addr

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_counter_1(self, mock_write, engine):
        cfg = PTraceEventCounterCfg(counter_id=1, event_source=20, threshold=1000)
        engine.configure_event_counter(PTraceDirection.INGRESS, cfg)
        addr = 0xF00000 + 0x4000 + int(PTraceReg.EVT_CTR1_CFG)
        mock_write.assert_called_once()
        assert mock_write.call_args[0][1] == addr


class TestWriteFilter:
    """512-bit filter write operations."""

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_filter_0_writes_32_dwords(self, mock_write, engine):
        match_hex = "AB" * 64  # 128 hex chars = 512 bits
        mask_hex = "CD" * 64
        engine.write_filter(PTraceDirection.INGRESS, 0, match_hex, mask_hex)
        assert mock_write.call_count == 32  # 16 match + 16 mask DWORDs

    @patch("calypso.core.ptrace.write_mapped_register")
    def test_filter_1_address(self, mock_write, engine):
        match_hex = "00" * 64
        mask_hex = "FF" * 64
        engine.write_filter(PTraceDirection.INGRESS, 1, match_hex, mask_hex)
        first_call_addr = mock_write.call_args_list[0][0][1]
        expected_base = 0xF00000 + 0x4000 + int(PTraceReg.FILTER1_MATCH_BASE)
        assert first_call_addr == expected_base

    def test_invalid_filter_idx(self, engine):
        with pytest.raises(ValueError, match="filter_idx"):
            engine.write_filter(PTraceDirection.INGRESS, 2, "0" * 128, "0" * 128)

    def test_invalid_hex_length(self, engine):
        with pytest.raises(ValueError, match="128"):
            engine.write_filter(PTraceDirection.INGRESS, 0, "0" * 64, "0" * 128)


class TestFullConfigure:
    """Full configure: disable, clear, configure, re-enable."""

    @patch("calypso.core.ptrace.write_mapped_register")
    @patch("calypso.core.ptrace.read_mapped_register", return_value=0)
    def test_full_configure_sequence(self, mock_read, mock_write, engine):
        capture = PTraceCaptureCfg()
        trigger = PTraceTriggerCfg()
        post_trigger = PTracePostTriggerCfg()
        engine.full_configure(PTraceDirection.INGRESS, capture, trigger, post_trigger)

        # Should have called write multiple times
        assert mock_write.call_count >= 8  # disable, clear, capture, 5 trigger, post_trigger, enable
        ctrl_addr = 0xF00000 + 0x4000 + 0x000
        # First call: disable (value=0)
        assert mock_write.call_args_list[0] == call(engine._device, ctrl_addr, 0)


class TestReadStatus:
    """Status readback including timestamps."""

    @patch("calypso.core.ptrace.read_mapped_register")
    def test_read_status(self, mock_read, engine):
        # Return different values for each register read
        mock_read.side_effect = [
            0x80000301,  # status: capture=1, triggered=1, wrapped=1, compress=3, ram_init=1
            0x00001000,  # first_ts_low
            0x00000001,  # first_ts_high
            0x00002000,  # last_cap_ts_low
            0x00000002,  # last_cap_ts_high
            0x00003000,  # trig_ts_low
            0x00000003,  # trig_ts_high
            0x00004000,  # last_ts_low
            0x00000004,  # last_ts_high
            42,           # trigger_row_addr
            0x0000000F,  # port_err_status
        ]
        status = engine.read_status(PTraceDirection.INGRESS)
        assert status.capture_in_progress
        assert status.triggered
        assert status.tbuf_wrapped
        assert status.ram_init_done
        assert status.first_capture_ts == (1 << 32) | 0x1000
        assert status.trigger_row_addr == 42
        assert status.port_err_status == 0x0F


class TestReadBuffer:
    """Trace buffer read protocol."""

    @patch("calypso.core.ptrace.write_mapped_register")
    @patch("calypso.core.ptrace.read_mapped_register")
    def test_read_buffer_protocol(self, mock_read, mock_write, engine):
        # Status reads (11), then 19 DWORDs per row x 2 rows
        status_vals = [0] * 11
        row_vals = list(range(TBUF_ROW_DWORDS)) * 2  # 2 rows
        mock_read.side_effect = status_vals + row_vals

        result = engine.read_buffer(PTraceDirection.INGRESS, max_rows=2)

        assert len(result.rows) == 2
        assert result.rows[0].row_index == 0
        assert result.rows[1].row_index == 1
        assert len(result.rows[0].dwords) == TBUF_ROW_DWORDS
        assert result.total_rows_read == 2

    @patch("calypso.core.ptrace.write_mapped_register")
    @patch("calypso.core.ptrace.read_mapped_register")
    def test_buffer_access_released_on_success(self, mock_read, mock_write, engine):
        mock_read.return_value = 0
        engine.read_buffer(PTraceDirection.INGRESS, max_rows=1)

        # Last write should be releasing TBuf access (value=0)
        last_write = mock_write.call_args_list[-1]
        tbuf_ctl_addr = 0xF00000 + 0x4000 + int(PTraceReg.TBUF_ACCESS_CTL)
        assert last_write == call(engine._device, tbuf_ctl_addr, 0)

    @patch("calypso.core.ptrace.write_mapped_register")
    @patch("calypso.core.ptrace.read_mapped_register")
    def test_buffer_access_released_on_error(self, mock_read, mock_write, engine):
        # Status reads succeed, then row read fails
        mock_read.side_effect = [0] * 11 + [Exception("HW error")]

        with pytest.raises(Exception, match="HW error"):
            engine.read_buffer(PTraceDirection.INGRESS, max_rows=1)

        # Should still release TBuf access in finally
        last_write = mock_write.call_args_list[-1]
        tbuf_ctl_addr = 0xF00000 + 0x4000 + int(PTraceReg.TBUF_ACCESS_CTL)
        assert last_write == call(engine._device, tbuf_ctl_addr, 0)

    @patch("calypso.core.ptrace.write_mapped_register")
    @patch("calypso.core.ptrace.read_mapped_register")
    def test_hex_str_format(self, mock_read, mock_write, engine):
        # All zeros for status, then specific values for one row
        status_vals = [0] * 11
        row_vals = [0xDEADBEEF] + [0] * 18
        mock_read.side_effect = status_vals + row_vals

        result = engine.read_buffer(PTraceDirection.INGRESS, max_rows=1)
        assert result.rows[0].hex_str.startswith("DEADBEEF")
