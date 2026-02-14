"""Unit tests for MCTP transport over mock I2C/I3C buses."""

from __future__ import annotations

import pytest

from calypso.mctp.framing import build_i2c_mctp_frame, build_mctp_packet
from calypso.mctp.transport import MCTPOverI2C, MCTPOverI3C, MCTPTransportConfig
from calypso.mctp.types import MCTPMessageType


class MockI2cBus:
    """Mock I2C bus that records writes and returns canned reads."""

    def __init__(self):
        self.bus_type = "i2c"
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


class MockI3cBus:
    """Mock I3C bus for testing MCTPOverI3C."""

    def __init__(self):
        self.bus_type = "i3c"
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
        bus = MockI2cBus()
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
        bus = MockI2cBus()
        transport = MCTPOverI2C(bus)

        tag0 = transport.send_request(0x6A, 0x0A, MCTPMessageType.CONTROL, b"\x80")
        tag1 = transport.send_request(0x6A, 0x0A, MCTPMessageType.CONTROL, b"\x80")

        assert tag1 == (tag0 + 1) & 0x07

    def test_receive_response_parses_frame(self):
        bus = MockI2cBus()
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
        bus = MockI2cBus()
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
        bus = MockI2cBus()
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


class TestMCTPOverI3C:
    """Test MCTP transport over mock I3C bus."""

    def test_send_request_writes_raw_mctp(self):
        bus = MockI3cBus()
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
        bus = MockI3cBus()
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
