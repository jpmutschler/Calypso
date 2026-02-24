"""Unit tests for PCIe Packet Exerciser register definitions."""

from __future__ import annotations

import pytest

from calypso.hardware.pktexer_regs import (
    DP_BIST_CTRL,
    DP_BIST_COUNT,
    EXER_CPL_DATA,
    EXER_CPL_STATUS,
    EXER_DW_FIFO,
    EXER_GEN_CPL_CTRL,
    EXER_GLOBAL_CTRL,
    EXER_THREAD0_CTRL,
    EXER_THREAD1_CTRL,
    EXER_THREAD2_CTRL,
    EXER_THREAD3_CTRL,
    DpBistCountReg,
    DpBistCtrlReg,
    ExerCplStatusReg,
    ExerGenCplCtrlReg,
    ExerGlobalCtrlReg,
    ExerThreadCtrlReg,
    TlpType,
    build_tlp_header,
    thread_ctrl_offset,
)


# ---------------------------------------------------------------------------
# Register offset constants
# ---------------------------------------------------------------------------


class TestRegisterOffsets:
    def test_exerciser_offsets_are_in_expected_range(self):
        assert 0x3500 <= EXER_DW_FIFO <= 0x3600
        assert 0x3500 <= EXER_GEN_CPL_CTRL <= 0x3600
        assert 0x3500 <= EXER_GLOBAL_CTRL <= 0x3600
        assert 0x3500 <= EXER_THREAD0_CTRL <= 0x3600

    def test_thread_offsets_are_consecutive(self):
        assert EXER_THREAD1_CTRL == EXER_THREAD0_CTRL + 4
        assert EXER_THREAD2_CTRL == EXER_THREAD0_CTRL + 8
        assert EXER_THREAD3_CTRL == EXER_THREAD0_CTRL + 12

    def test_completion_offsets(self):
        assert EXER_CPL_STATUS == 0x3780
        assert EXER_CPL_DATA == 0x3784

    def test_dp_bist_offsets(self):
        assert DP_BIST_CTRL == 0x3768
        assert DP_BIST_COUNT == 0x376C


# ---------------------------------------------------------------------------
# thread_ctrl_offset
# ---------------------------------------------------------------------------


class TestThreadCtrlOffset:
    def test_valid_thread_ids(self):
        assert thread_ctrl_offset(0) == EXER_THREAD0_CTRL
        assert thread_ctrl_offset(1) == EXER_THREAD1_CTRL
        assert thread_ctrl_offset(2) == EXER_THREAD2_CTRL
        assert thread_ctrl_offset(3) == EXER_THREAD3_CTRL

    def test_invalid_thread_id_raises(self):
        with pytest.raises(ValueError, match="thread_id must be 0-3"):
            thread_ctrl_offset(4)
        with pytest.raises(ValueError, match="thread_id must be 0-3"):
            thread_ctrl_offset(-1)


# ---------------------------------------------------------------------------
# ExerGlobalCtrlReg
# ---------------------------------------------------------------------------


class TestExerGlobalCtrlReg:
    def test_defaults(self):
        reg = ExerGlobalCtrlReg()
        val = reg.to_register()
        assert val & 0xFF == 8  # max_outstanding_np default
        assert (val >> 8) & 0xFF == 8  # max_outstanding_uio_p default
        assert (val >> 16) & 0xFF == 8  # max_outstanding_uio_np default
        assert val & (1 << 29) == 0  # reset not set
        assert val & (1 << 30) == 0  # enable not set

    def test_roundtrip(self):
        reg = ExerGlobalCtrlReg(
            max_outstanding_np=16,
            max_outstanding_uio_p=32,
            max_outstanding_uio_np=64,
            reset=True,
            enable=True,
        )
        val = reg.to_register()
        decoded = ExerGlobalCtrlReg.from_register(val)
        assert decoded.max_outstanding_np == 16
        assert decoded.max_outstanding_uio_p == 32
        assert decoded.max_outstanding_uio_np == 64
        assert decoded.reset is True
        assert decoded.enable is True

    def test_from_register_ro_bits(self):
        val = (1 << 24) | (1 << 25) | (1 << 26)
        decoded = ExerGlobalCtrlReg.from_register(val)
        assert decoded.np_pending is True
        assert decoded.uio_p_pending is True
        assert decoded.uio_np_pending is True

    def test_enable_only(self):
        reg = ExerGlobalCtrlReg(
            max_outstanding_np=0,
            max_outstanding_uio_p=0,
            max_outstanding_uio_np=0,
            enable=True,
        )
        val = reg.to_register()
        assert val == (1 << 30)


# ---------------------------------------------------------------------------
# ExerThreadCtrlReg
# ---------------------------------------------------------------------------


class TestExerThreadCtrlReg:
    def test_defaults(self):
        reg = ExerThreadCtrlReg()
        assert reg.to_register() == 0

    def test_roundtrip(self):
        reg = ExerThreadCtrlReg(
            ram_address=0x10,
            ram_select=2,
            ram_write_enable=True,
            infinite_loop=True,
            max_header_address=0x05,
            run=True,
        )
        val = reg.to_register()
        decoded = ExerThreadCtrlReg.from_register(val)
        assert decoded.ram_address == 0x10
        assert decoded.ram_select == 2
        assert decoded.ram_write_enable is True
        assert decoded.infinite_loop is True
        assert decoded.max_header_address == 0x05
        assert decoded.run is True

    def test_from_register_done_bit(self):
        val = 1 << 28
        decoded = ExerThreadCtrlReg.from_register(val)
        assert decoded.done is True
        assert decoded.run is False

    def test_run_bit(self):
        reg = ExerThreadCtrlReg(run=True)
        val = reg.to_register()
        assert val == (1 << 31)


# ---------------------------------------------------------------------------
# ExerGenCplCtrlReg
# ---------------------------------------------------------------------------


class TestExerGenCplCtrlReg:
    def test_defaults(self):
        reg = ExerGenCplCtrlReg()
        assert reg.to_register() == 0

    def test_roundtrip(self):
        reg = ExerGenCplCtrlReg(completer_bus=0x05, completer_devfn=0xA0, td_bit=True)
        val = reg.to_register()
        decoded = ExerGenCplCtrlReg.from_register(val)
        assert decoded.completer_bus == 0x05
        assert decoded.completer_devfn == 0xA0
        assert decoded.td_bit is True

    def test_td_bit_position(self):
        reg = ExerGenCplCtrlReg(td_bit=True)
        assert reg.to_register() == (1 << 31)


# ---------------------------------------------------------------------------
# ExerCplStatusReg
# ---------------------------------------------------------------------------


class TestExerCplStatusReg:
    def test_defaults(self):
        reg = ExerCplStatusReg()
        assert reg.to_register() == 0

    def test_roundtrip(self):
        reg = ExerCplStatusReg(received=True, ep=True, ecrc_error=True, status=0x5)
        val = reg.to_register()
        decoded = ExerCplStatusReg.from_register(val)
        assert decoded.received is True
        assert decoded.ep is True
        assert decoded.ecrc_error is True
        assert decoded.status == 0x5

    def test_from_register_status_field(self):
        # Status at bits [6:4], value 3 = 0b011 << 4 = 0x30
        val = 0x30
        decoded = ExerCplStatusReg.from_register(val)
        assert decoded.status == 3


# ---------------------------------------------------------------------------
# DpBistCtrlReg
# ---------------------------------------------------------------------------


class TestDpBistCtrlReg:
    def test_defaults(self):
        reg = DpBistCtrlReg()
        # extra_mode_bits default is 0x90
        val = reg.to_register()
        assert (val >> 20) & 0xFF == 0x90

    def test_roundtrip(self):
        reg = DpBistCtrlReg(
            ecrc_enable=True,
            delay_count=0x1234,
            extra_mode_bits=0xAB,
            tlp_bus0_only=True,
            perf_mon_enable=True,
            infinite_loop=True,
        )
        val = reg.to_register()
        decoded = DpBistCtrlReg.from_register(val)
        assert decoded.ecrc_enable is True
        assert decoded.delay_count == 0x1234
        assert decoded.extra_mode_bits == 0xAB
        assert decoded.tlp_bus0_only is True
        assert decoded.perf_mon_enable is True
        assert decoded.infinite_loop is True

    def test_from_register_ro_bits(self):
        val = (1 << 2) | (1 << 3) | (1 << 31)
        decoded = DpBistCtrlReg.from_register(val)
        assert decoded.tx_done is True
        assert decoded.rx_done is True
        assert decoded.pass_fail is True


# ---------------------------------------------------------------------------
# DpBistCountReg
# ---------------------------------------------------------------------------


class TestDpBistCountReg:
    def test_defaults(self):
        reg = DpBistCountReg()
        val = reg.to_register()
        assert val & 0xFFFF == 1  # loop_count default
        assert (val >> 16) & 0x7FFF == 1  # inner_loop_count default

    def test_roundtrip(self):
        reg = DpBistCountReg(loop_count=100, inner_loop_count=50, start=True)
        val = reg.to_register()
        decoded = DpBistCountReg.from_register(val)
        assert decoded.loop_count == 100
        assert decoded.inner_loop_count == 50
        assert decoded.start is True

    def test_start_bit(self):
        reg = DpBistCountReg(loop_count=0, inner_loop_count=0, start=True)
        assert reg.to_register() == (1 << 31)


# ---------------------------------------------------------------------------
# TlpType enum
# ---------------------------------------------------------------------------


class TestTlpType:
    def test_all_15_types(self):
        assert len(TlpType) == 15

    def test_memory_types(self):
        assert TlpType.MR32.value == "mr32"
        assert TlpType.MW32.value == "mw32"
        assert TlpType.MR64.value == "mr64"
        assert TlpType.MW64.value == "mw64"

    def test_config_types(self):
        assert TlpType.CFRD0.value == "cfrd0"
        assert TlpType.CFWR0.value == "cfwr0"
        assert TlpType.CFRD1.value == "cfrd1"
        assert TlpType.CFWR1.value == "cfwr1"

    def test_message_types(self):
        assert TlpType.PM_NAK.value == "PMNak"
        assert TlpType.PME.value == "PME"
        assert TlpType.PME_OFF.value == "PMEOff"
        assert TlpType.PME_ACK.value == "PMEAck"
        assert TlpType.ERR_COR.value == "ERRCor"
        assert TlpType.ERR_NF.value == "ERRNF"
        assert TlpType.ERR_FATAL.value == "ERRF"

    def test_string_enum(self):
        assert isinstance(TlpType.MR32, str)
        assert TlpType("mr32") == TlpType.MR32


# ---------------------------------------------------------------------------
# build_tlp_header
# ---------------------------------------------------------------------------


class TestBuildTlpHeader:
    def test_mr32_basic(self):
        """MR32: 3DW header, Fmt=00, Type=00000."""
        header = build_tlp_header(TlpType.MR32, address=0x1000, length_dw=1)
        assert len(header) == 3
        # DW0: Fmt[31:29]=00, Type[28:24]=00000, Length[9:0]=1
        dw0 = header[0]
        assert (dw0 >> 29) & 0x7 == 0b00  # Fmt
        assert (dw0 >> 24) & 0x1F == 0b00000  # Type
        assert dw0 & 0x3FF == 1  # Length
        # DW2: Address with bits [1:0] cleared
        assert header[2] == 0x1000

    def test_mw32_with_data(self):
        """MW32: 3DW header + payload, Fmt=10."""
        header = build_tlp_header(
            TlpType.MW32, address=0x2000, length_dw=1, data=0xDEADBEEF
        )
        assert len(header) == 4  # 3DW header + 1 data DW
        dw0 = header[0]
        assert (dw0 >> 29) & 0x7 == 0b10  # Fmt = with data
        assert header[3] == 0xDEADBEEF

    def test_mw32_without_data(self):
        """MW32 without data: only 3DW header."""
        header = build_tlp_header(TlpType.MW32, address=0x2000, length_dw=1)
        assert len(header) == 3

    def test_mr64_4dw_header(self):
        """MR64: 4DW header, Fmt=01."""
        header = build_tlp_header(
            TlpType.MR64, address=0x100000000, length_dw=4
        )
        assert len(header) == 4
        dw0 = header[0]
        assert (dw0 >> 29) & 0x7 == 0b01  # Fmt = 4DW, no data
        assert dw0 & 0x3FF == 4  # Length
        # DW2: upper 32 bits of address
        assert header[2] == 1
        # DW3: lower 32 bits (DWORD aligned)
        assert header[3] == 0

    def test_mw64_with_data(self):
        """MW64: 4DW header + payload."""
        header = build_tlp_header(
            TlpType.MW64, address=0x200000004, length_dw=1, data=0xCAFEBABE
        )
        assert len(header) == 5  # 4DW header + 1 data DW
        dw0 = header[0]
        assert (dw0 >> 29) & 0x7 == 0b11  # Fmt = 4DW, with data
        assert header[4] == 0xCAFEBABE

    def test_cfrd0(self):
        """CfgRd0: 3DW, Fmt=00, Type=00100."""
        header = build_tlp_header(
            TlpType.CFRD0,
            target_id=0x0108,
            address=0x40,
            requester_id=0x0200,
        )
        assert len(header) == 3
        dw0 = header[0]
        assert (dw0 >> 24) & 0x1F == 0b00100
        # DW1 has requester ID
        assert (header[1] >> 16) & 0xFFFF == 0x0200
        # DW2: target bus=01, devfn=08, reg_num = 0x40>>2 = 0x10
        dw2 = header[2]
        assert (dw2 >> 24) & 0xFF == 0x01  # target bus
        assert (dw2 >> 16) & 0xFF == 0x08  # target devfn
        reg_num = (dw2 >> 2) & 0x3F
        assert reg_num == 0x10

    def test_cfwr0_with_data(self):
        """CfgWr0: 3DW + payload."""
        header = build_tlp_header(
            TlpType.CFWR0, target_id=0x0100, address=0x04, data=0x12345678
        )
        assert len(header) == 4  # 3DW header + 1 data
        dw0 = header[0]
        assert (dw0 >> 29) & 0x7 == 0b10  # Fmt = with data

    def test_cfrd1(self):
        """CfgRd1: Type=00101."""
        header = build_tlp_header(TlpType.CFRD1, target_id=0x0200)
        dw0 = header[0]
        assert (dw0 >> 24) & 0x1F == 0b00101

    def test_message_tlp_err_cor(self):
        """ERR_COR: 4DW message, msg_code=0x30."""
        header = build_tlp_header(TlpType.ERR_COR, requester_id=0x0300)
        assert len(header) == 4
        dw0 = header[0]
        assert (dw0 >> 29) & 0x7 == 0b01  # Fmt = 4DW, no data
        # DW1 lower 8 bits = message code
        msg_code = header[1] & 0xFF
        assert msg_code == 0x30
        # Requester ID in DW1
        assert (header[1] >> 16) & 0xFFFF == 0x0300

    def test_message_tlp_pme(self):
        header = build_tlp_header(TlpType.PME)
        assert len(header) == 4
        assert header[1] & 0xFF == 0x18

    def test_message_tlp_err_fatal(self):
        header = build_tlp_header(TlpType.ERR_FATAL)
        assert header[1] & 0xFF == 0x33

    def test_message_tlp_pm_nak(self):
        header = build_tlp_header(TlpType.PM_NAK)
        assert header[1] & 0xFF == 0x14

    def test_message_tlp_pme_off(self):
        header = build_tlp_header(TlpType.PME_OFF)
        assert header[1] & 0xFF == 0x19

    def test_message_tlp_pme_ack(self):
        header = build_tlp_header(TlpType.PME_ACK)
        assert header[1] & 0xFF == 0x1B

    def test_message_tlp_err_nf(self):
        header = build_tlp_header(TlpType.ERR_NF)
        assert header[1] & 0xFF == 0x31

    def test_requester_id_and_tag(self):
        """Requester ID and tag are packed into DW1."""
        header = build_tlp_header(
            TlpType.MR32, requester_id=0xABCD, tag=0x42
        )
        dw1 = header[1]
        assert (dw1 >> 16) & 0xFFFF == 0xABCD
        assert (dw1 >> 8) & 0xFF == 0x42

    def test_byte_enables(self):
        header = build_tlp_header(
            TlpType.MR32, first_be=0xC, last_be=0x3
        )
        dw1 = header[1]
        assert (dw1 >> 4) & 0xF == 0xC  # first_be
        assert dw1 & 0xF == 0x3  # last_be

    def test_relaxed_ordering(self):
        header = build_tlp_header(TlpType.MR32, relaxed_ordering=True)
        dw0 = header[0]
        # Attr[0] at bit 12
        assert (dw0 >> 12) & 0x1 == 1

    def test_poisoned_ep_bit(self):
        header = build_tlp_header(TlpType.MW32, poisoned=True)
        dw0 = header[0]
        # EP at bit 14
        assert (dw0 >> 14) & 0x1 == 1

    def test_all_15_tlp_types_produce_valid_headers(self):
        """Every TLP type should produce a header without error."""
        for tlp_type in TlpType:
            header = build_tlp_header(tlp_type)
            assert len(header) >= 3
            assert all(isinstance(dw, int) for dw in header)

    def test_address_alignment(self):
        """Memory addresses should have bits [1:0] cleared."""
        header = build_tlp_header(TlpType.MR32, address=0x1003)
        assert header[2] == 0x1000  # bits [1:0] cleared

    def test_length_field_max(self):
        header = build_tlp_header(TlpType.MR32, length_dw=1024)
        # 1024 mod 1024 = 0 in PCIe spec (10-bit field), but 1024 & 0x3FF = 0
        assert header[0] & 0x3FF == 0

    def test_length_field_wraps(self):
        header = build_tlp_header(TlpType.MR32, length_dw=5)
        assert header[0] & 0x3FF == 5
