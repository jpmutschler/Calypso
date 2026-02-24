"""Unit tests for PCIe Packet Exerciser Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from calypso.hardware.pktexer_regs import TlpType
from calypso.models.packet_exerciser import (
    CaptureAndSendRequest,
    DpBistRequest,
    DpBistStatus,
    ExerciserSendRequest,
    ExerciserStatus,
    ThreadStatus,
    TlpConfig,
)


# ---------------------------------------------------------------------------
# TlpConfig
# ---------------------------------------------------------------------------


class TestTlpConfig:
    def test_basic_mr32(self):
        cfg = TlpConfig(tlp_type=TlpType.MR32)
        assert cfg.tlp_type == TlpType.MR32
        assert cfg.address == 0
        assert cfg.length_dw == 1
        assert cfg.data is None
        assert cfg.tag is None

    def test_with_all_fields(self):
        cfg = TlpConfig(
            tlp_type=TlpType.MW64,
            address=0x100000000,
            length_dw=4,
            requester_id=0x0100,
            target_id=0x0200,
            data="DEADBEEF",
            relaxed_ordering=True,
            poisoned=False,
            tag=42,
        )
        assert cfg.address == 0x100000000
        assert cfg.length_dw == 4
        assert cfg.data == "DEADBEEF"
        assert cfg.tag == 42

    def test_length_dw_min(self):
        cfg = TlpConfig(tlp_type=TlpType.MR32, length_dw=1)
        assert cfg.length_dw == 1

    def test_length_dw_max(self):
        cfg = TlpConfig(tlp_type=TlpType.MR32, length_dw=1024)
        assert cfg.length_dw == 1024

    def test_length_dw_too_small(self):
        with pytest.raises(ValidationError):
            TlpConfig(tlp_type=TlpType.MR32, length_dw=0)

    def test_length_dw_too_large(self):
        with pytest.raises(ValidationError):
            TlpConfig(tlp_type=TlpType.MR32, length_dw=1025)

    def test_requester_id_max(self):
        cfg = TlpConfig(tlp_type=TlpType.MR32, requester_id=0xFFFF)
        assert cfg.requester_id == 0xFFFF

    def test_requester_id_too_large(self):
        with pytest.raises(ValidationError):
            TlpConfig(tlp_type=TlpType.MR32, requester_id=0x10000)

    def test_negative_address_rejected(self):
        with pytest.raises(ValidationError):
            TlpConfig(tlp_type=TlpType.MR32, address=-1)

    def test_serialization_roundtrip(self):
        cfg = TlpConfig(tlp_type=TlpType.CFRD0, target_id=0x0108)
        data = cfg.model_dump()
        restored = TlpConfig(**data)
        assert restored.tlp_type == TlpType.CFRD0
        assert restored.target_id == 0x0108


# ---------------------------------------------------------------------------
# ExerciserSendRequest
# ---------------------------------------------------------------------------


class TestExerciserSendRequest:
    def test_minimal(self):
        req = ExerciserSendRequest(
            tlps=[TlpConfig(tlp_type=TlpType.MR32)]
        )
        assert req.port_number == 0
        assert len(req.tlps) == 1
        assert req.infinite_loop is False
        assert req.max_outstanding_np == 8

    def test_empty_tlps_rejected(self):
        with pytest.raises(ValidationError):
            ExerciserSendRequest(tlps=[])

    def test_port_number_range(self):
        req = ExerciserSendRequest(
            port_number=143, tlps=[TlpConfig(tlp_type=TlpType.MR32)]
        )
        assert req.port_number == 143

    def test_port_number_too_large(self):
        with pytest.raises(ValidationError):
            ExerciserSendRequest(
                port_number=144, tlps=[TlpConfig(tlp_type=TlpType.MR32)]
            )

    def test_multiple_tlps(self):
        req = ExerciserSendRequest(
            tlps=[
                TlpConfig(tlp_type=TlpType.MR32),
                TlpConfig(tlp_type=TlpType.MW32, data="AABBCCDD"),
                TlpConfig(tlp_type=TlpType.ERR_COR),
            ]
        )
        assert len(req.tlps) == 3


# ---------------------------------------------------------------------------
# ThreadStatus / ExerciserStatus
# ---------------------------------------------------------------------------


class TestExerciserStatus:
    def test_defaults(self):
        status = ExerciserStatus()
        assert status.enabled is False
        assert status.np_pending is False
        assert status.completion_received is False
        assert status.completion_status == 0
        assert status.threads == []

    def test_with_threads(self):
        status = ExerciserStatus(
            enabled=True,
            np_pending=True,
            completion_received=True,
            completion_status=1,
            completion_data=0xDEAD,
            threads=[
                ThreadStatus(thread_id=0, running=True),
                ThreadStatus(thread_id=1, done=True),
            ],
        )
        assert status.threads[0].running is True
        assert status.threads[1].done is True

    def test_serialization(self):
        status = ExerciserStatus(
            enabled=True,
            threads=[ThreadStatus(thread_id=0, running=True)],
        )
        data = status.model_dump()
        assert data["enabled"] is True
        assert data["threads"][0]["thread_id"] == 0
        assert data["threads"][0]["running"] is True


# ---------------------------------------------------------------------------
# DpBistRequest / DpBistStatus
# ---------------------------------------------------------------------------


class TestDpBistRequest:
    def test_defaults(self):
        req = DpBistRequest()
        assert req.loop_count == 1
        assert req.inner_loop_count == 1
        assert req.delay_count == 0
        assert req.infinite is False

    def test_loop_count_range(self):
        req = DpBistRequest(loop_count=0xFFFF, inner_loop_count=0x7FFF)
        assert req.loop_count == 0xFFFF

    def test_loop_count_too_small(self):
        with pytest.raises(ValidationError):
            DpBistRequest(loop_count=0)

    def test_delay_count_max(self):
        req = DpBistRequest(delay_count=0xFFFF)
        assert req.delay_count == 0xFFFF


class TestDpBistStatus:
    def test_defaults(self):
        status = DpBistStatus()
        assert status.tx_done is False
        assert status.rx_done is False
        assert status.passed is True
        assert status.infinite_loop is False


# ---------------------------------------------------------------------------
# CaptureAndSendRequest
# ---------------------------------------------------------------------------


class TestCaptureAndSendRequest:
    def test_basic(self):
        req = CaptureAndSendRequest(
            port_number=128,
            exerciser=ExerciserSendRequest(
                port_number=128,
                tlps=[TlpConfig(tlp_type=TlpType.MR32)],
            ),
        )
        assert req.port_number == 128
        assert req.ptrace_direction == "egress"
        assert req.read_buffer is True
        assert req.post_trigger_wait_ms == 100

    def test_wait_ms_range(self):
        with pytest.raises(ValidationError):
            CaptureAndSendRequest(
                exerciser=ExerciserSendRequest(
                    tlps=[TlpConfig(tlp_type=TlpType.MR32)],
                ),
                post_trigger_wait_ms=5,  # min is 10
            )
