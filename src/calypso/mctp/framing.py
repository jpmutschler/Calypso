"""MCTP packet build/parse and I2C frame wrapping.

References:
  - DMTF DSP0236 (MCTP Base Specification) — packet header format
  - DMTF DSP0237 (MCTP SMBus/I2C Transport Binding) — I2C frame format
"""

from __future__ import annotations

from dataclasses import dataclass

from calypso.mctp.types import (
    MCTP_HEADER_VERSION,
    MCTP_I2C_COMMAND_CODE,
    MCTP_MAX_PAYLOAD,
    MCTPMessageType,
)


@dataclass(frozen=True)
class MCTPHeader:
    """Parsed MCTP transport header (4 bytes, DSP0236 §8.1)."""

    version: int
    dest_eid: int
    source_eid: int
    som: bool  # Start of Message
    eom: bool  # End of Message
    pkt_seq: int  # Packet sequence (0-3)
    tag_owner: bool
    msg_tag: int  # Message tag (0-7)


@dataclass(frozen=True)
class MCTPPacket:
    """A parsed MCTP packet with header, message type, and payload."""

    header: MCTPHeader
    message_type: MCTPMessageType
    ic_bit: bool  # Integrity Check bit
    payload: bytes


def build_mctp_header(
    dest_eid: int,
    source_eid: int,
    *,
    som: bool = True,
    eom: bool = True,
    pkt_seq: int = 0,
    tag_owner: bool = True,
    msg_tag: int = 0,
) -> bytes:
    """Build a 4-byte MCTP transport header.

    Layout (DSP0236 §8.1):
        Byte 0: [7:4] header version (0x1), [3:0] reserved
        Byte 1: destination EID
        Byte 2: source EID
        Byte 3: [7] SOM, [6] EOM, [5:4] pkt_seq, [3] TO, [2:0] msg_tag
    """
    byte0 = (MCTP_HEADER_VERSION << 4) & 0xF0
    byte3 = (
        ((1 if som else 0) << 7)
        | ((1 if eom else 0) << 6)
        | ((pkt_seq & 0x03) << 4)
        | ((1 if tag_owner else 0) << 3)
        | (msg_tag & 0x07)
    )
    return bytes([byte0, dest_eid, source_eid, byte3])


def parse_mctp_header(data: bytes) -> MCTPHeader:
    """Parse a 4-byte MCTP transport header."""
    if len(data) < 4:
        raise ValueError(f"MCTP header requires 4 bytes, got {len(data)}")
    version = (data[0] >> 4) & 0x0F
    dest_eid = data[1]
    source_eid = data[2]
    som = bool(data[3] & 0x80)
    eom = bool(data[3] & 0x40)
    pkt_seq = (data[3] >> 4) & 0x03
    tag_owner = bool(data[3] & 0x08)
    msg_tag = data[3] & 0x07
    return MCTPHeader(
        version=version,
        dest_eid=dest_eid,
        source_eid=source_eid,
        som=som,
        eom=eom,
        pkt_seq=pkt_seq,
        tag_owner=tag_owner,
        msg_tag=msg_tag,
    )


def build_mctp_packet(
    dest_eid: int,
    source_eid: int,
    message_type: MCTPMessageType,
    payload: bytes,
    *,
    som: bool = True,
    eom: bool = True,
    pkt_seq: int = 0,
    tag_owner: bool = True,
    msg_tag: int = 0,
    ic_bit: bool = False,
) -> bytes:
    """Build a complete MCTP packet (header + message type byte + payload).

    The message type byte (DSP0236 §11.1):
        [7] IC (integrity check), [6:0] message type
    """
    if len(payload) > MCTP_MAX_PAYLOAD:
        raise ValueError(
            f"Payload {len(payload)} bytes exceeds MCTP max {MCTP_MAX_PAYLOAD}"
        )
    header = build_mctp_header(
        dest_eid, source_eid,
        som=som, eom=eom, pkt_seq=pkt_seq,
        tag_owner=tag_owner, msg_tag=msg_tag,
    )
    msg_type_byte = ((1 if ic_bit else 0) << 7) | (message_type & 0x7F)
    return header + bytes([msg_type_byte]) + payload


def parse_mctp_packet(data: bytes) -> MCTPPacket:
    """Parse a raw MCTP packet (header + message type + payload)."""
    if len(data) < 5:
        raise ValueError(f"MCTP packet requires at least 5 bytes, got {len(data)}")
    header = parse_mctp_header(data[:4])
    msg_type_byte = data[4]
    ic_bit = bool(msg_type_byte & 0x80)
    message_type = MCTPMessageType(msg_type_byte & 0x7F)
    payload = data[5:]
    return MCTPPacket(
        header=header,
        message_type=message_type,
        ic_bit=ic_bit,
        payload=bytes(payload),
    )


def _smbus_pec(data: bytes) -> int:
    """Compute SMBus PEC (CRC-8) over a byte sequence (DSP0237 §6.3)."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x07) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def build_i2c_mctp_frame(
    dest_slave_addr: int,
    source_slave_addr: int,
    mctp_packet: bytes,
) -> bytes:
    """Wrap an MCTP packet in an I2C/SMBus frame (DSP0237 §6.1).

    Frame layout:
        [dest_addr_w] [0x0F] [byte_count] [source_addr_r] [mctp_packet...] [PEC]

    The frame is what gets sent via I2C_WRITE to dest_slave_addr.
    We return the bytes starting from the command code (the dest address
    is implicit in the I2C transaction target).
    """
    byte_count = len(mctp_packet) + 1  # +1 for source_addr_r byte
    source_addr_r = (source_slave_addr << 1) | 0x01

    # PEC is computed over: dest_addr_w, cmd_code, byte_count, source_addr_r, mctp_packet
    dest_addr_w = (dest_slave_addr << 1) & 0xFE
    pec_data = bytes([dest_addr_w, MCTP_I2C_COMMAND_CODE, byte_count, source_addr_r]) + mctp_packet
    pec = _smbus_pec(pec_data)

    # The I2C write payload (target address is handled by the bus layer)
    return bytes([MCTP_I2C_COMMAND_CODE, byte_count, source_addr_r]) + mctp_packet + bytes([pec])


def parse_i2c_mctp_frame(
    raw: bytes,
    dest_slave_addr: int,
) -> MCTPPacket:
    """Parse an I2C MCTP frame (DSP0237 §6.1) and extract the MCTP packet.

    Args:
        raw: The received I2C payload (cmd_code, byte_count, source, mctp..., PEC).
        dest_slave_addr: Our own slave address (for PEC verification).
    """
    if len(raw) < 8:
        raise ValueError(f"I2C MCTP frame too short: {len(raw)} bytes")

    cmd_code = raw[0]
    if cmd_code != MCTP_I2C_COMMAND_CODE:
        raise ValueError(f"Expected MCTP command code 0x0F, got 0x{cmd_code:02X}")

    byte_count = raw[1]
    _source_addr_r = raw[2]
    pec_received = raw[-1]

    mctp_data = raw[3:-1]

    # Verify PEC
    dest_addr_w = (dest_slave_addr << 1) & 0xFE
    pec_input = bytes([dest_addr_w]) + raw[:-1]
    pec_computed = _smbus_pec(pec_input)
    if pec_received != pec_computed:
        raise ValueError(
            f"PEC mismatch: received 0x{pec_received:02X}, "
            f"computed 0x{pec_computed:02X}"
        )

    if len(mctp_data) != byte_count - 1:
        raise ValueError(
            f"Byte count mismatch: header says {byte_count - 1}, "
            f"got {len(mctp_data)}"
        )

    return parse_mctp_packet(mctp_data)
