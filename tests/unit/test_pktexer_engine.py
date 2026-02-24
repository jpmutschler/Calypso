"""Tests for PacketExerciserEngine domain logic.

Uses mocked SDK register I/O to verify control flow, register addresses,
and TLP loading protocol without real hardware.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from calypso.core.packet_exerciser import PacketExerciserEngine
from calypso.hardware.pktexer_regs import (
    DP_BIST_CTRL,
    DP_BIST_COUNT,
    EXER_CPL_DATA,
    EXER_CPL_STATUS,
    EXER_DW_FIFO,
    EXER_GEN_CPL_CTRL,
    EXER_GLOBAL_CTRL,
    EXER_THREAD0_CTRL,
    ExerGlobalCtrlReg,
    ExerThreadCtrlReg,
    TlpType,
)
from calypso.models.packet_exerciser import TlpConfig

STATION_BASE = 0xF00000


@pytest.fixture
def mock_device():
    return MagicMock()


@pytest.fixture
def mock_key():
    key = MagicMock()
    key.ChipID = 0x0144
    return key


@pytest.fixture
def engine(mock_device, mock_key):
    with patch(
        "calypso.core.packet_exerciser.station_register_base",
        return_value=STATION_BASE,
    ):
        return PacketExerciserEngine(mock_device, mock_key, port_number=0)


@pytest.fixture
def mock_write(engine):
    with patch(
        "calypso.core.packet_exerciser.write_mapped_register"
    ) as mock:
        yield mock


@pytest.fixture
def mock_read(engine):
    with patch(
        "calypso.core.packet_exerciser.read_mapped_register",
        return_value=0,
    ) as mock:
        yield mock


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


class TestInit:
    def test_station_base(self, engine):
        assert engine._station_base == STATION_BASE

    def test_port_number(self, engine):
        assert engine._port_number == 0

    def test_invalid_port_negative(self, mock_device, mock_key):
        with pytest.raises(ValueError, match="out of range"):
            PacketExerciserEngine(mock_device, mock_key, port_number=-1)

    def test_invalid_port_too_high(self, mock_device, mock_key):
        with pytest.raises(ValueError, match="out of range"):
            PacketExerciserEngine(mock_device, mock_key, port_number=144)


# ---------------------------------------------------------------------------
# Global control
# ---------------------------------------------------------------------------


class TestGlobalControl:
    def test_reset(self, engine, mock_read, mock_write):
        mock_read.return_value = 0
        engine.reset()
        # Should read-modify-write EXER_GLOBAL_CTRL with bit 29
        mock_read.assert_called_with(engine._device, STATION_BASE + EXER_GLOBAL_CTRL)
        written_val = mock_write.call_args[0][2]
        assert written_val & (1 << 29) != 0

    def test_enable(self, engine, mock_write):
        engine.enable(max_outstanding_np=16)
        addr = STATION_BASE + EXER_GLOBAL_CTRL
        mock_write.assert_called_once()
        call_args = mock_write.call_args
        assert call_args[0][1] == addr
        val = call_args[0][2]
        decoded = ExerGlobalCtrlReg.from_register(val)
        assert decoded.enable is True
        assert decoded.max_outstanding_np == 16

    def test_disable(self, engine, mock_write):
        engine.disable()
        mock_write.assert_called_once_with(
            engine._device, STATION_BASE + EXER_GLOBAL_CTRL, 0
        )


# ---------------------------------------------------------------------------
# DW FIFO and RAM
# ---------------------------------------------------------------------------


class TestFifoAndRam:
    def test_write_fifo(self, engine, mock_write):
        engine._write_fifo([0xAABBCCDD, 0x11223344, 0x55667788])
        assert mock_write.call_count == 3
        fifo_addr = STATION_BASE + EXER_DW_FIFO
        calls = mock_write.call_args_list
        assert calls[0] == call(engine._device, fifo_addr, 0xAABBCCDD)
        assert calls[1] == call(engine._device, fifo_addr, 0x11223344)
        assert calls[2] == call(engine._device, fifo_addr, 0x55667788)

    def test_commit_ram(self, engine, mock_write):
        engine._commit_ram(thread_id=0, ram_addr=5)
        addr = STATION_BASE + EXER_THREAD0_CTRL
        mock_write.assert_called_once()
        val = mock_write.call_args[0][2]
        decoded = ExerThreadCtrlReg.from_register(val)
        assert decoded.ram_address == 5
        assert decoded.ram_write_enable is True

    def test_load_tlp_writes_fifo_then_commits(self, engine, mock_write):
        header = [0x00000001, 0x00000002, 0x00000003]
        engine.load_tlp(thread_id=0, ram_addr=0, header_dwords=header)
        # 3 FIFO writes + 1 commit
        assert mock_write.call_count == 4
        fifo_addr = STATION_BASE + EXER_DW_FIFO
        assert mock_write.call_args_list[0][0][1] == fifo_addr
        assert mock_write.call_args_list[1][0][1] == fifo_addr
        assert mock_write.call_args_list[2][0][1] == fifo_addr
        assert mock_write.call_args_list[3][0][1] == STATION_BASE + EXER_THREAD0_CTRL


# ---------------------------------------------------------------------------
# Thread control
# ---------------------------------------------------------------------------


class TestThreadControl:
    def test_configure_thread(self, engine, mock_write):
        engine.configure_thread(thread_id=2, max_addr=3, infinite_loop=True)
        addr = STATION_BASE + EXER_THREAD0_CTRL + (2 * 4)
        mock_write.assert_called_once()
        val = mock_write.call_args[0][2]
        decoded = ExerThreadCtrlReg.from_register(val)
        assert decoded.max_header_address == 3
        assert decoded.infinite_loop is True

    def test_run_thread(self, engine, mock_read, mock_write):
        mock_read.return_value = 0
        engine.run_thread(1)
        addr = STATION_BASE + EXER_THREAD0_CTRL + 4
        mock_read.assert_called_with(engine._device, addr)
        val = mock_write.call_args[0][2]
        assert val & (1 << 31) != 0

    def test_stop_thread(self, engine, mock_read, mock_write):
        mock_read.return_value = 1 << 31  # currently running
        engine.stop_thread(0)
        val = mock_write.call_args[0][2]
        assert val & (1 << 31) == 0


# ---------------------------------------------------------------------------
# Completion
# ---------------------------------------------------------------------------


class TestCompletion:
    def test_configure_completion(self, engine, mock_write):
        engine.configure_completion(bus=5, devfn=0xA0, td=True)
        addr = STATION_BASE + EXER_GEN_CPL_CTRL
        mock_write.assert_called_once()
        assert mock_write.call_args[0][1] == addr

    def test_read_completion(self, engine, mock_read):
        # Status register = received + status=2, Data = 0xDEAD
        mock_read.side_effect = [
            (1 << 0) | (2 << 4),  # CPL_STATUS
            0xDEAD,  # CPL_DATA
        ]
        cpl_status, cpl_data = engine.read_completion()
        assert cpl_status.received is True
        assert cpl_status.status == 2
        assert cpl_data == 0xDEAD


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


class TestReadStatus:
    def test_read_status_all_zero(self, engine, mock_read):
        mock_read.return_value = 0
        status = engine.read_status()
        assert status.enabled is False
        assert status.np_pending is False
        assert len(status.threads) == 4
        for t in status.threads:
            assert t.running is False
            assert t.done is False

    def test_read_status_enabled_with_running_thread(self, engine, mock_read):
        # Calls: global_ctrl, cpl_status, cpl_data, thread0..3
        mock_read.side_effect = [
            (1 << 30) | (1 << 24),  # global: enable + np_pending
            1,  # cpl_status: received
            0xBEEF,  # cpl_data
            1 << 31,  # thread 0: running
            1 << 28,  # thread 1: done
            0,  # thread 2
            0,  # thread 3
        ]
        status = engine.read_status()
        assert status.enabled is True
        assert status.np_pending is True
        assert status.completion_received is True
        assert status.completion_data == 0xBEEF
        assert status.threads[0].running is True
        assert status.threads[1].done is True


# ---------------------------------------------------------------------------
# High-level send_tlps
# ---------------------------------------------------------------------------


class TestSendTlps:
    @patch("calypso.core.packet_exerciser.time.sleep")
    def test_send_single_mr32(self, mock_sleep, engine, mock_read, mock_write):
        mock_read.return_value = 0
        tlps = [TlpConfig(tlp_type=TlpType.MR32, address=0x1000)]
        engine.send_tlps(tlps)

        # Verify reset was called (reads global_ctrl, writes with bit 29)
        assert mock_write.call_count > 0
        first_write_addr = mock_write.call_args_list[0][0][1]
        assert first_write_addr == STATION_BASE + EXER_GLOBAL_CTRL

    @patch("calypso.core.packet_exerciser.time.sleep")
    def test_send_multiple_tlps(self, mock_sleep, engine, mock_read, mock_write):
        mock_read.return_value = 0
        tlps = [
            TlpConfig(tlp_type=TlpType.MR32, address=0x1000),
            TlpConfig(tlp_type=TlpType.MW32, address=0x2000, data="DEADBEEF"),
        ]
        engine.send_tlps(tlps, infinite_loop=True)

        # Verify writes happened (reset + fifo writes + commits + configure + enable + run)
        assert mock_write.call_count > 5

    @patch("calypso.core.packet_exerciser.time.sleep")
    def test_send_with_tag(self, mock_sleep, engine, mock_read, mock_write):
        mock_read.return_value = 0
        tlps = [TlpConfig(tlp_type=TlpType.MR32, tag=42)]
        engine.send_tlps(tlps)
        # Should complete without error
        assert mock_write.call_count > 0


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------


class TestStop:
    def test_stop_all(self, engine, mock_read, mock_write):
        mock_read.return_value = 1 << 31  # all running
        engine.stop()
        # Should stop 4 threads + disable
        # 4 reads + 4 writes (stop threads) + 1 write (disable)
        assert mock_write.call_count == 5
        # Last write should be disable (write 0 to global ctrl)
        last_call = mock_write.call_args_list[-1]
        assert last_call[0][1] == STATION_BASE + EXER_GLOBAL_CTRL
        assert last_call[0][2] == 0


# ---------------------------------------------------------------------------
# DP BIST
# ---------------------------------------------------------------------------


class TestDpBist:
    def test_start_dp_bist(self, engine, mock_write):
        engine.start_dp_bist(loop_count=10, inner_loop_count=5, delay=100)
        assert mock_write.call_count == 2
        # First write: DP_BIST_CTRL
        assert mock_write.call_args_list[0][0][1] == STATION_BASE + DP_BIST_CTRL
        # Second write: DP_BIST_COUNT with start bit
        addr = mock_write.call_args_list[1][0][1]
        val = mock_write.call_args_list[1][0][2]
        assert addr == STATION_BASE + DP_BIST_COUNT
        assert val & (1 << 31) != 0  # start bit

    def test_stop_dp_bist(self, engine, mock_write):
        engine.stop_dp_bist()
        assert mock_write.call_count == 2

    def test_read_dp_bist_status(self, engine, mock_read):
        # tx_done=1, rx_done=1, pass_fail=0 (pass)
        mock_read.return_value = (1 << 2) | (1 << 3)
        status = engine.read_dp_bist_status()
        assert status.tx_done is True
        assert status.rx_done is True
        assert status.passed is True

    def test_read_dp_bist_status_fail(self, engine, mock_read):
        mock_read.return_value = (1 << 31)  # pass_fail=1 means FAIL
        status = engine.read_dp_bist_status()
        assert status.passed is False
