"""Unit tests for MCTP endpoint discovery and management."""

from __future__ import annotations

import dataclasses

import pytest

from calypso.mctp.endpoint import (
    MCTPEndpoint,
    _build_get_eid_request,
    _parse_get_eid_response,
    discover_endpoint,
)
from calypso.mctp.framing import MCTPPacket, build_mctp_packet, parse_mctp_packet
from calypso.mctp.types import MCTP_NULL_EID, MCTPCompletionCode, MCTPMessageType


class MockTransport:
    """Mock MCTP transport that records exchange() calls and returns canned responses."""

    def __init__(self, response_packet: MCTPPacket | None = None, error: Exception | None = None):
        self._response = response_packet
        self._error = error
        self.exchanges: list[dict] = []

    def exchange(
        self,
        dest_addr: int,
        dest_eid: int,
        message_type: MCTPMessageType,
        payload: bytes,
    ) -> MCTPPacket:
        self.exchanges.append({
            "dest_addr": dest_addr,
            "dest_eid": dest_eid,
            "message_type": message_type,
            "payload": payload,
        })
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


def _make_eid_response_packet(
    completion_code: int = 0x00,
    eid: int = 0x0A,
    eid_type: int = 0x00,
    medium_specific: int = 0x00,
) -> MCTPPacket:
    """Build an MCTPPacket carrying a Get Endpoint ID response payload."""
    response_payload = bytes([completion_code, eid, (eid_type << 4), medium_specific])
    raw = build_mctp_packet(
        dest_eid=0x08,
        source_eid=eid,
        message_type=MCTPMessageType.CONTROL,
        payload=response_payload,
        tag_owner=False,
        msg_tag=0,
    )
    return parse_mctp_packet(raw)


class TestMCTPEndpoint:
    """Test MCTPEndpoint dataclass and properties."""

    def test_supports_nvme_mi_true(self):
        ep = MCTPEndpoint(
            eid=0x0A,
            slave_addr=0x6A,
            endpoint_type="simple",
            medium_specific=0x00,
            message_types=[MCTPMessageType.CONTROL, MCTPMessageType.NVME_MI],
        )
        assert ep.supports_nvme_mi is True

    def test_supports_nvme_mi_false(self):
        ep = MCTPEndpoint(
            eid=0x0A,
            slave_addr=0x6A,
            endpoint_type="simple",
            medium_specific=0x00,
            message_types=[MCTPMessageType.CONTROL],
        )
        assert ep.supports_nvme_mi is False

    def test_supports_nvme_mi_empty(self):
        ep = MCTPEndpoint(
            eid=0x0A,
            slave_addr=0x6A,
            endpoint_type="simple",
            medium_specific=0x00,
            message_types=[],
        )
        assert ep.supports_nvme_mi is False

    def test_frozen(self):
        ep = MCTPEndpoint(
            eid=0x0A,
            slave_addr=0x6A,
            endpoint_type="simple",
            medium_specific=0x00,
            message_types=[MCTPMessageType.CONTROL],
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            ep.eid = 0x0B  # type: ignore[misc]


class TestBuildGetEidRequest:
    """Test _build_get_eid_request()."""

    def test_request_format(self):
        req = _build_get_eid_request()
        assert len(req) == 1
        # Bit 7 = Rq=1, bits [5:0] = GET_ENDPOINT_ID (0x02) → 0x82
        assert req[0] & 0x80 == 0x80  # Rq bit set
        assert req[0] & 0x3F == 0x02  # command code


class TestParseGetEidResponse:
    """Test _parse_get_eid_response()."""

    def test_parse_simple_endpoint(self):
        payload = bytes([MCTPCompletionCode.SUCCESS, 0x0A, 0x00, 0x00])
        eid, endpoint_type, medium_specific = _parse_get_eid_response(payload)
        assert eid == 0x0A
        assert endpoint_type == "simple"
        assert medium_specific == 0x00

    def test_parse_bus_owner(self):
        # eid_type field at bits [7:4] of byte[2] = 0x01
        payload = bytes([MCTPCompletionCode.SUCCESS, 0x0B, 0x10, 0x00])
        eid, endpoint_type, _ms = _parse_get_eid_response(payload)
        assert eid == 0x0B
        assert endpoint_type == "bus_owner"

    def test_parse_too_short(self):
        with pytest.raises(ValueError, match="too short"):
            _parse_get_eid_response(b"\x00\x0A\x00")

    def test_parse_failure_code(self):
        payload = bytes([MCTPCompletionCode.ERROR, 0x0A, 0x00, 0x00])
        with pytest.raises(ValueError, match="completion code"):
            _parse_get_eid_response(payload)

    def test_medium_specific_passed_through(self):
        payload = bytes([MCTPCompletionCode.SUCCESS, 0x0A, 0x00, 0x42])
        _eid, _type, medium_specific = _parse_get_eid_response(payload)
        assert medium_specific == 0x42


class TestDiscoverEndpoint:
    """Test discover_endpoint() with mock transport."""

    def test_discover_success(self):
        response = _make_eid_response_packet(eid=0x0A, eid_type=0x00, medium_specific=0x05)
        transport = MockTransport(response_packet=response)

        ep = discover_endpoint(transport, slave_addr=0x6A)

        assert ep is not None
        assert ep.eid == 0x0A
        assert ep.slave_addr == 0x6A
        assert ep.endpoint_type == "simple"
        assert ep.medium_specific == 0x05
        assert MCTPMessageType.CONTROL in ep.message_types

    def test_discover_no_response(self):
        transport = MockTransport(error=TimeoutError("no response"))

        ep = discover_endpoint(transport, slave_addr=0x6A)
        assert ep is None

    def test_discover_sends_control_to_null_eid(self):
        response = _make_eid_response_packet()
        transport = MockTransport(response_packet=response)

        discover_endpoint(transport, slave_addr=0x6A)

        assert len(transport.exchanges) == 1
        call = transport.exchanges[0]
        assert call["dest_eid"] == MCTP_NULL_EID
        assert call["message_type"] == MCTPMessageType.CONTROL
        assert call["dest_addr"] == 0x6A

    def test_discover_returns_none_on_parse_error(self):
        # Build a response with a failure completion code so _parse_get_eid_response raises
        response = _make_eid_response_packet(completion_code=MCTPCompletionCode.ERROR)
        transport = MockTransport(response_packet=response)

        ep = discover_endpoint(transport, slave_addr=0x6A)
        assert ep is None
