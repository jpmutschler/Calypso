"""Unit tests for NVMeMIClient with mock MCTP transport."""

from __future__ import annotations

import struct
from unittest.mock import MagicMock


from calypso.mctp.framing import MCTPHeader, MCTPPacket
from calypso.mctp.types import MCTPMessageType
from calypso.nvme_mi.client import NVMeMIClient
from calypso.nvme_mi.commands import build_mi_header
from calypso.nvme_mi.models import NVMeHealthStatus
from calypso.nvme_mi.types import NVMeMIOpcode, NVMeMIStatus


def _make_health_response(
    temp_celsius: int = 42,
    spare: int = 95,
    threshold: int = 10,
    used: int = 5,
    warning: int = 0,
    poh: int = 100,
) -> MCTPPacket:
    """Build a mock MCTP packet containing a health poll response."""
    data = bytearray(19)
    data[0:4] = build_mi_header(NVMeMIOpcode.SUBSYSTEM_HEALTH_STATUS_POLL, is_request=False)
    data[4] = NVMeMIStatus.SUCCESS
    data[5] = warning
    struct.pack_into("<H", data, 6, 273 + temp_celsius)
    data[8] = spare
    data[9] = threshold
    data[10] = used
    struct.pack_into("<I", data, 15, poh)

    return MCTPPacket(
        header=MCTPHeader(
            version=1, dest_eid=0x08, source_eid=0x0A,
            som=True, eom=True, pkt_seq=0, tag_owner=False, msg_tag=0,
        ),
        message_type=MCTPMessageType.NVME_MI,
        ic_bit=False,
        payload=bytes(data),
    )


def _make_identify_response(nqn: str = "", ports: int = 1) -> MCTPPacket:
    """Build a mock MCTP packet containing an identify response."""
    nqn_bytes = nqn.encode("utf-8") + b"\x00" if nqn else b""
    data = bytearray(8 + len(nqn_bytes))
    data[0:4] = build_mi_header(NVMeMIOpcode.READ_MI_DATA_STRUCTURE, is_request=False)
    data[4] = NVMeMIStatus.SUCCESS
    data[5] = ports
    data[6] = 1  # major
    data[7] = 0  # minor
    if nqn_bytes:
        data[8:8 + len(nqn_bytes)] = nqn_bytes

    return MCTPPacket(
        header=MCTPHeader(
            version=1, dest_eid=0x08, source_eid=0x0A,
            som=True, eom=True, pkt_seq=0, tag_owner=False, msg_tag=0,
        ),
        message_type=MCTPMessageType.NVME_MI,
        ic_bit=False,
        payload=bytes(data),
    )


class TestNVMeMIClient:
    """Test NVMeMIClient with mock transport."""

    def _make_client(self, exchange_response: MCTPPacket) -> NVMeMIClient:
        transport = MagicMock()
        transport.exchange.return_value = exchange_response
        return NVMeMIClient(transport, default_eid=0x0A)

    def test_health_poll_parses_response(self):
        client = self._make_client(_make_health_response(temp_celsius=55, spare=80))
        health = client.health_poll(slave_addr=0x6A)

        assert health.composite_temperature_celsius == 55
        assert health.available_spare_percent == 80
        assert health.has_critical_warning is False

    def test_health_poll_with_warning(self):
        client = self._make_client(
            _make_health_response(temp_celsius=90, spare=3, warning=0x03)
        )
        health = client.health_poll(slave_addr=0x6A)

        assert health.has_critical_warning is True
        assert health.spare_below_threshold is True
        assert health.temperature_exceeded is True

    def test_identify_parses_nqn(self):
        nqn = "nqn.2024-01.com.example:ssd"
        client = self._make_client(_make_identify_response(nqn=nqn, ports=2))
        info = client.identify(slave_addr=0x6A)

        assert info.nqn == nqn
        assert info.number_of_ports == 2

    def test_get_drive_info_combines_health_and_identity(self):
        transport = MagicMock()
        # First call is identify, second is health_poll
        transport.exchange.side_effect = [
            _make_identify_response(nqn="nqn.test:drive1"),
            _make_health_response(temp_celsius=40),
        ]
        client = NVMeMIClient(transport, default_eid=0x0A)

        drive = client.get_drive_info(connector=0, channel="a")
        assert drive.subsystem.nqn == "nqn.test:drive1"
        assert drive.health.composite_temperature_celsius == 40
        assert drive.reachable is True

    def test_get_drive_info_graceful_on_identify_failure(self):
        transport = MagicMock()
        transport.exchange.side_effect = [
            Exception("identify failed"),
            _make_health_response(temp_celsius=35),
        ]
        client = NVMeMIClient(transport, default_eid=0x0A)

        drive = client.get_drive_info(connector=0, channel="a")
        assert drive.subsystem.nqn == ""
        assert drive.health.composite_temperature_celsius == 35

    def test_get_drive_info_graceful_on_health_failure(self):
        transport = MagicMock()
        transport.exchange.side_effect = [
            _make_identify_response(nqn="nqn.test:drive2"),
            Exception("health failed"),
        ]
        client = NVMeMIClient(transport, default_eid=0x0A)

        drive = client.get_drive_info(connector=1, channel="b")
        assert drive.subsystem.nqn == "nqn.test:drive2"
        assert drive.health.composite_temperature_celsius == 0  # default

    def test_default_eid_used_when_zero(self):
        transport = MagicMock()
        transport.exchange.return_value = _make_health_response()
        client = NVMeMIClient(transport, default_eid=0x0A)

        client.health_poll(slave_addr=0x6A, eid=0)

        call_args = transport.exchange.call_args
        assert call_args.kwargs.get("dest_eid") == 0x0A or call_args[1].get("dest_eid") == 0x0A


class TestNVMeHealthModel:
    """Test NVMeHealthStatus model properties."""

    def test_drive_life_remaining(self):
        h = NVMeHealthStatus(percentage_used=75)
        assert h.drive_life_remaining_percent == 25

    def test_drive_life_remaining_clamps_at_zero(self):
        h = NVMeHealthStatus(percentage_used=150)
        assert h.drive_life_remaining_percent == 0

    def test_temperature_status_normal(self):
        assert NVMeHealthStatus(composite_temperature_celsius=30).temperature_status == "normal"

    def test_temperature_status_warm(self):
        assert NVMeHealthStatus(composite_temperature_celsius=60).temperature_status == "warm"

    def test_temperature_status_critical(self):
        assert NVMeHealthStatus(composite_temperature_celsius=80).temperature_status == "critical"

    def test_all_warning_flags(self):
        h = NVMeHealthStatus(critical_warning=0x1F)
        assert h.spare_below_threshold is True
        assert h.temperature_exceeded is True
        assert h.reliability_degraded is True
        assert h.read_only_mode is True
        assert h.volatile_backup_failed is True
