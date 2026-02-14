"""Unit tests for MCTP transport over mock I2C/I3C buses."""

from __future__ import annotations

import pytest

from calypso.mctp.framing import build_i2c_mctp_frame, build_mctp_packet
from calypso.mctp.transport import MCTPOverI2C, MCTPOverI3C, MCTPTransportConfig
from calypso.mctp.types import MCTPMessageType


class MockBus:
    """Mock I2C/I3C bus that records writes and returns canned reads."""

    def __init__(self, bus_type: str = "i2c"):
        self.bus_type = bus_type
        self.connector = 0
        self.channel = "a"
        self.writes: list[tuple[int, list[int]]] = []
        self.read_response: list[int] = []

    def read(self, address: int, register: int, count: int) -> list[int]:
        return self.read_response[:count]

    def write(self, address: int, data: list[int]) -> bool:
        self.writes.append((address, data))
        return True

    def write_register(self, address: int, register: int, data: list[int]) -> bool:
        self.writes.append((address, [register] + data))
        return True


class TestMCTPOverI2C:
    """Test MCTP transport over mock I2C bus."""

    def test_send_request_writes_to_bus(self):
        bus = MockBus("i2c")
        config = MCTPTransportConfig(own_eid=0x08, own_slave_addr=0x21)
        transport = MCTPOverI2C(bus, config)

        tag = transport.send_request(
            dest_addr=0x6A,
            dest_eid=0x0A,
            message_type=MCTPMessageType.NVME_MI,
            payload=b"\x00\x01",
        )

        assert isinstance(tag, int)
        assert 0 <= tag <= 7
        assert len(bus.writes) == 1
        addr, data = bus.writes[0]
        assert addr == 0x6A

    def test_send_request_increments_tag(self):
        bus = MockBus("i2c")
        transport = MCTPOverI2C(bus)

        tag0 = transport.send_request(0x6A, 0x0A, MCTPMessageType.CONTROL, b"\x80")
        tag1 = transport.send_request(0x6A, 0x0A, MCTPMessageType.CONTROL, b"\x80")

        assert tag1 == (tag0 + 1) & 0x07

    def test_receive_response_parses_frame(self):
        bus = MockBus("i2c")
        config = MCTPTransportConfig(own_eid=0x08, own_slave_addr=0x21)
        transport = MCTPOverI2C(bus, config)

        # Build a response frame that will be returned by the bus read
        response_mctp = build_mctp_packet(
            dest_eid=0x08, source_eid=0x0A,
            message_type=MCTPMessageType.NVME_MI,
            payload=b"\x00\x00\x00\x01\x00",
            tag_owner=False, msg_tag=3,
        )
        response_frame = build_i2c_mctp_frame(
            dest_slave_addr=0x21,
            source_slave_addr=0x6A,
            mctp_packet=response_mctp,
        )
        bus.read_response = list(response_frame)

        packet = transport.receive_response(0x6A, expected_tag=3)

        assert packet.header.source_eid == 0x0A
        assert packet.message_type == MCTPMessageType.NVME_MI
        assert packet.header.msg_tag == 3

    def test_receive_response_tag_mismatch(self):
        bus = MockBus("i2c")
        config = MCTPTransportConfig(own_eid=0x08, own_slave_addr=0x21)
        transport = MCTPOverI2C(bus, config)

        response_mctp = build_mctp_packet(
            dest_eid=0x08, source_eid=0x0A,
            message_type=MCTPMessageType.NVME_MI,
            payload=b"\x00",
            tag_owner=False, msg_tag=5,
        )
        response_frame = build_i2c_mctp_frame(
            dest_slave_addr=0x21,
            source_slave_addr=0x6A,
            mctp_packet=response_mctp,
        )
        bus.read_response = list(response_frame)

        with pytest.raises(ValueError, match="Tag mismatch"):
            transport.receive_response(0x6A, expected_tag=2)

    def test_exchange_sends_and_receives(self):
        bus = MockBus("i2c")
        config = MCTPTransportConfig(own_eid=0x08, own_slave_addr=0x21)
        transport = MCTPOverI2C(bus, config)

        # Pre-load a response for tag 0
        response_mctp = build_mctp_packet(
            dest_eid=0x08, source_eid=0x0A,
            message_type=MCTPMessageType.NVME_MI,
            payload=b"\x00\x00\x00\x01\x00\x19\x01\x30",
            tag_owner=False, msg_tag=0,
        )
        response_frame = build_i2c_mctp_frame(
            dest_slave_addr=0x21,
            source_slave_addr=0x6A,
            mctp_packet=response_mctp,
        )
        bus.read_response = list(response_frame)

        packet = transport.exchange(
            dest_addr=0x6A,
            dest_eid=0x0A,
            message_type=MCTPMessageType.NVME_MI,
            payload=b"\x00\x00\x00\x01",
        )

        assert len(bus.writes) == 1
        assert packet.message_type == MCTPMessageType.NVME_MI

    def test_tag_wraps_at_boundary(self):
        bus = MockBus("i2c")
        transport = MCTPOverI2C(bus)
        tags = [
            transport.send_request(0x6A, 0x0A, MCTPMessageType.CONTROL, b"\x80")
            for _ in range(9)
        ]
        # Tags cycle 0..7, so the 9th request (index 8) wraps back to 0
        assert tags[7] == 7
        assert tags[8] == 0

    def test_receive_response_no_tag_check(self):
        bus = MockBus("i2c")
        config = MCTPTransportConfig(own_eid=0x08, own_slave_addr=0x21)
        transport = MCTPOverI2C(bus, config)

        response_mctp = build_mctp_packet(
            dest_eid=0x08, source_eid=0x0A,
            message_type=MCTPMessageType.CONTROL,
            payload=b"\x00",
            tag_owner=False, msg_tag=5,
        )
        response_frame = build_i2c_mctp_frame(
            dest_slave_addr=0x21,
            source_slave_addr=0x6A,
            mctp_packet=response_mctp,
        )
        bus.read_response = list(response_frame)

        # expected_tag=None should skip tag validation
        packet = transport.receive_response(0x6A, expected_tag=None)
        assert packet.header.msg_tag == 5

    def test_bus_property(self):
        bus = MockBus("i2c")
        transport = MCTPOverI2C(bus)
        assert transport.bus is bus

    def test_default_config(self):
        bus = MockBus("i2c")
        transport = MCTPOverI2C(bus)
        assert transport._config.own_eid == 0x08
        assert transport._config.own_slave_addr == 0x21


class TestMCTPOverI3C:
    """Test MCTP transport over mock I3C bus."""

    def test_send_request_writes_raw_mctp(self):
        bus = MockBus("i3c")
        transport = MCTPOverI3C(bus)

        tag = transport.send_request(
            dest_addr=0x08,
            dest_eid=0x0A,
            message_type=MCTPMessageType.NVME_MI,
            payload=b"\x00\x01",
        )

        assert isinstance(tag, int)
        assert len(bus.writes) == 1
        addr, data = bus.writes[0]
        assert addr == 0x08

    def test_receive_response_parses_raw_mctp(self):
        bus = MockBus("i3c")
        transport = MCTPOverI3C(bus)

        response = build_mctp_packet(
            dest_eid=0x08, source_eid=0x0A,
            message_type=MCTPMessageType.NVME_MI,
            payload=b"\x00\x00\x00\x01\x00",
            tag_owner=False, msg_tag=0,
        )
        bus.read_response = list(response)

        packet = transport.receive_response(0x08, expected_tag=0)
        assert packet.message_type == MCTPMessageType.NVME_MI

    def test_exchange_sends_and_receives(self):
        bus = MockBus("i3c")
        transport = MCTPOverI3C(bus)

        response = build_mctp_packet(
            dest_eid=0x08, source_eid=0x0A,
            message_type=MCTPMessageType.NVME_MI,
            payload=b"\x00\x01\x02",
            tag_owner=False, msg_tag=0,
        )
        bus.read_response = list(response)

        packet = transport.exchange(
            dest_addr=0x08,
            dest_eid=0x0A,
            message_type=MCTPMessageType.NVME_MI,
            payload=b"\x00\x01",
        )

        assert len(bus.writes) == 1
        assert packet.message_type == MCTPMessageType.NVME_MI
        assert packet.payload == b"\x00\x01\x02"

    def test_tag_mismatch_raises(self):
        bus = MockBus("i3c")
        transport = MCTPOverI3C(bus)

        response = build_mctp_packet(
            dest_eid=0x08, source_eid=0x0A,
            message_type=MCTPMessageType.NVME_MI,
            payload=b"\x00",
            tag_owner=False, msg_tag=5,
        )
        bus.read_response = list(response)

        with pytest.raises(ValueError, match="Tag mismatch"):
            transport.receive_response(0x08, expected_tag=2)

    def test_tag_wraps_at_boundary(self):
        bus = MockBus("i3c")
        transport = MCTPOverI3C(bus)
        tags = [
            transport.send_request(0x08, 0x0A, MCTPMessageType.CONTROL, b"\x80")
            for _ in range(9)
        ]
        assert tags[7] == 7
        assert tags[8] == 0

    def test_bus_property(self):
        bus = MockBus("i3c")
        transport = MCTPOverI3C(bus)
        assert transport.bus is bus

    def test_i3c_no_framing(self):
        bus = MockBus("i3c")
        transport = MCTPOverI3C(bus)

        transport.send_request(
            dest_addr=0x08,
            dest_eid=0x0A,
            message_type=MCTPMessageType.NVME_MI,
            payload=b"\x00\x01",
        )

        _addr, data = bus.writes[0]
        # I3C writes raw MCTP — no 0x0F command code prefix
        assert data[0] != 0x0F
        # First byte should be MCTP header byte 0 (version 1 in upper nibble)
        assert data[0] == 0x10
