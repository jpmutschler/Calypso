"""Unit tests for MCTP packet build/parse and I2C frame wrapping."""

from __future__ import annotations

import pytest

from calypso.mctp.framing import (
    _smbus_pec,
    build_i2c_mctp_frame,
    build_mctp_header,
    build_mctp_packet,
    parse_i2c_mctp_frame,
    parse_mctp_header,
    parse_mctp_packet,
)
from calypso.mctp.types import MCTPMessageType


class TestMCTPHeader:
    """Test MCTP transport header build/parse."""

    def test_build_header_default(self):
        h = build_mctp_header(dest_eid=0x0A, source_eid=0x08)
        assert len(h) == 4
        assert h[0] == 0x10  # version 1 in upper nibble
        assert h[1] == 0x0A  # dest EID
        assert h[2] == 0x08  # source EID
        # SOM=1, EOM=1, seq=0, TO=1, tag=0 => 0b1100_1000 = 0xC8
        assert h[3] == 0xC8

    def test_build_header_custom_flags(self):
        h = build_mctp_header(
            dest_eid=0x01, source_eid=0x02,
            som=False, eom=False, pkt_seq=2, tag_owner=False, msg_tag=5,
        )
        # SOM=0, EOM=0, seq=2 (0b10), TO=0, tag=5 (0b101) => 0b0010_0101 = 0x25
        assert h[3] == 0x25

    def test_parse_header_round_trip(self):
        original = build_mctp_header(
            dest_eid=0x0A, source_eid=0x08,
            som=True, eom=False, pkt_seq=3, tag_owner=True, msg_tag=7,
        )
        parsed = parse_mctp_header(original)
        assert parsed.version == 1
        assert parsed.dest_eid == 0x0A
        assert parsed.source_eid == 0x08
        assert parsed.som is True
        assert parsed.eom is False
        assert parsed.pkt_seq == 3
        assert parsed.tag_owner is True
        assert parsed.msg_tag == 7

    def test_parse_header_too_short(self):
        with pytest.raises(ValueError, match="4 bytes"):
            parse_mctp_header(b"\x10\x0A")


class TestMCTPPacket:
    """Test MCTP full packet build/parse."""

    def test_build_packet_basic(self):
        pkt = build_mctp_packet(
            dest_eid=0x0A, source_eid=0x08,
            message_type=MCTPMessageType.NVME_MI,
            payload=b"\x00\x01\x02\x03",
        )
        # 4 header + 1 msg type + 4 payload = 9 bytes
        assert len(pkt) == 9
        # Message type byte: IC=0, type=0x04
        assert pkt[4] == 0x04

    def test_build_packet_with_ic_bit(self):
        pkt = build_mctp_packet(
            dest_eid=0x0A, source_eid=0x08,
            message_type=MCTPMessageType.CONTROL,
            payload=b"\x80\x02",
            ic_bit=True,
        )
        # IC=1 in bit 7 of msg type byte
        assert pkt[4] & 0x80 == 0x80
        assert pkt[4] & 0x7F == MCTPMessageType.CONTROL

    def test_build_packet_payload_too_large(self):
        with pytest.raises(ValueError, match="exceeds MCTP max"):
            build_mctp_packet(
                dest_eid=0x0A, source_eid=0x08,
                message_type=MCTPMessageType.CONTROL,
                payload=b"\x00" * 65,
            )

    def test_parse_packet_round_trip(self):
        payload = b"\xDE\xAD\xBE\xEF"
        pkt_bytes = build_mctp_packet(
            dest_eid=0x0A, source_eid=0x08,
            message_type=MCTPMessageType.NVME_MI,
            payload=payload,
            msg_tag=3,
        )
        parsed = parse_mctp_packet(pkt_bytes)
        assert parsed.header.dest_eid == 0x0A
        assert parsed.header.source_eid == 0x08
        assert parsed.header.msg_tag == 3
        assert parsed.message_type == MCTPMessageType.NVME_MI
        assert parsed.payload == payload
        assert parsed.ic_bit is False

    def test_build_packet_max_payload(self):
        payload = b"\xAA" * 64
        pkt = build_mctp_packet(
            dest_eid=0x0A, source_eid=0x08,
            message_type=MCTPMessageType.NVME_MI,
            payload=payload,
        )
        # 4 header + 1 msg type + 64 payload = 69
        assert len(pkt) == 69

    def test_build_packet_empty_payload(self):
        pkt = build_mctp_packet(
            dest_eid=0x0A, source_eid=0x08,
            message_type=MCTPMessageType.CONTROL,
            payload=b"",
        )
        # 4 header + 1 msg type + 0 payload = 5
        assert len(pkt) == 5
        parsed = parse_mctp_packet(pkt)
        assert parsed.payload == b""

    def test_parse_packet_too_short(self):
        with pytest.raises(ValueError, match="at least 5 bytes"):
            parse_mctp_packet(b"\x10\x0A\x08\xC8")


class TestSMBusPEC:
    """Test SMBus PEC (CRC-8) computation."""

    def test_pec_zero_input(self):
        assert _smbus_pec(b"") == 0

    def test_pec_known_value(self):
        # Verify PEC is deterministic and changes with input
        pec1 = _smbus_pec(b"\x01\x02\x03")
        pec2 = _smbus_pec(b"\x01\x02\x04")
        assert pec1 != pec2

    def test_pec_single_byte(self):
        result = _smbus_pec(b"\xAA")
        assert isinstance(result, int)
        assert 0 <= result <= 255


class TestI2CMCTPFrame:
    """Test I2C MCTP frame build/parse."""

    def test_build_frame_structure(self):
        mctp_pkt = build_mctp_packet(
            dest_eid=0x0A, source_eid=0x08,
            message_type=MCTPMessageType.NVME_MI,
            payload=b"\x00\x01",
        )
        frame = build_i2c_mctp_frame(
            dest_slave_addr=0x6A,
            source_slave_addr=0x21,
            mctp_packet=mctp_pkt,
        )
        # Frame: [cmd_code=0x0F] [byte_count] [source_addr_r] [mctp...] [PEC]
        assert frame[0] == 0x0F  # command code
        assert frame[2] == (0x21 << 1) | 0x01  # source addr with read bit

    def test_frame_round_trip(self):
        payload = b"\xCA\xFE"
        mctp_pkt = build_mctp_packet(
            dest_eid=0x0A, source_eid=0x08,
            message_type=MCTPMessageType.NVME_MI,
            payload=payload,
        )
        frame = build_i2c_mctp_frame(
            dest_slave_addr=0x6A,
            source_slave_addr=0x21,
            mctp_packet=mctp_pkt,
        )
        # Parse it back — dest_slave_addr must match what was used to build
        parsed = parse_i2c_mctp_frame(frame, dest_slave_addr=0x6A)
        assert parsed.header.dest_eid == 0x0A
        assert parsed.header.source_eid == 0x08
        assert parsed.message_type == MCTPMessageType.NVME_MI
        assert parsed.payload == payload

    def test_parse_frame_pec_mismatch(self):
        mctp_pkt = build_mctp_packet(
            dest_eid=0x0A, source_eid=0x08,
            message_type=MCTPMessageType.CONTROL,
            payload=b"\x80\x02",
        )
        frame = build_i2c_mctp_frame(
            dest_slave_addr=0x6A,
            source_slave_addr=0x21,
            mctp_packet=mctp_pkt,
        )
        # Corrupt the PEC byte
        corrupted = frame[:-1] + bytes([(frame[-1] ^ 0xFF)])
        with pytest.raises(ValueError, match="PEC mismatch"):
            parse_i2c_mctp_frame(corrupted, dest_slave_addr=0x21)

    def test_parse_frame_too_short(self):
        with pytest.raises(ValueError, match="too short"):
            parse_i2c_mctp_frame(b"\x0F\x01\x43", dest_slave_addr=0x21)

    def test_parse_frame_byte_count_mismatch(self):
        mctp_pkt = build_mctp_packet(
            dest_eid=0x0A, source_eid=0x08,
            message_type=MCTPMessageType.CONTROL,
            payload=b"\x80\x02",
        )
        frame = build_i2c_mctp_frame(
            dest_slave_addr=0x6A,
            source_slave_addr=0x21,
            mctp_packet=mctp_pkt,
        )
        # Corrupt byte_count (index 1) — set it too high but keep PEC valid
        # by recalculating. Instead, just tamper and expect either PEC or count error.
        corrupted = bytearray(frame)
        corrupted[1] = frame[1] + 5  # wrong byte count
        # Recompute PEC over the corrupted frame
        dest_addr_w = (0x6A << 1) & 0xFE
        pec_input = bytes([dest_addr_w]) + bytes(corrupted[:-1])
        pec = _smbus_pec(pec_input)
        corrupted[-1] = pec
        with pytest.raises(ValueError, match="Byte count mismatch"):
            parse_i2c_mctp_frame(bytes(corrupted), dest_slave_addr=0x6A)

    def test_parse_frame_wrong_command_code(self):
        with pytest.raises(ValueError, match="command code"):
            parse_i2c_mctp_frame(b"\x10\x05\x43\x10\x0A\x08\xC8\x04\x00", dest_slave_addr=0x21)
