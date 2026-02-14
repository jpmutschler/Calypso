"""MCTP transport bindings over I2C and I3C buses.

Provides MCTPOverI2C and MCTPOverI3C classes that send/receive MCTP
packets through the bus abstraction layer.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from calypso.mctp.framing import (
    MCTPPacket,
    build_i2c_mctp_frame,
    build_mctp_packet,
    parse_i2c_mctp_frame,
    parse_mctp_packet,
)
from calypso.mctp.types import MCTP_I2C_COMMAND_CODE, MCTP_I2C_MAX_FRAME, MCTPMessageType
from calypso.mcu.bus import Bus
from calypso.utils.logging import get_logger

logger = get_logger(__name__)


# Default MCTP slave addresses (DSP0237 §5.1)
MCTP_I2C_DEFAULT_SLAVE = 0x6A  # NVMe-MI default
MCTP_I2C_OWN_ADDR = 0x21  # Our address as MCTP controller


@dataclass
class MCTPTransportConfig:
    """Configuration for an MCTP transport instance."""

    own_eid: int = 0x08
    own_slave_addr: int = MCTP_I2C_OWN_ADDR
    response_timeout_ms: int = 100
    max_retries: int = 2


class MCTPOverI2C:
    """MCTP transport over I2C (DMTF DSP0237).

    Sends MCTP packets as I2C block writes with SMBus PEC.
    Reads responses as I2C block reads from the target address.
    """

    def __init__(self, bus: Bus, config: MCTPTransportConfig | None = None) -> None:
        self._bus = bus
        self._config = config or MCTPTransportConfig()
        self._msg_tag = 0
        self._lock = threading.Lock()

    @property
    def bus(self) -> Bus:
        return self._bus

    def _next_tag(self) -> int:
        tag = self._msg_tag
        self._msg_tag = (self._msg_tag + 1) & 0x07
        return tag

    def send_request(
        self,
        dest_addr: int,
        dest_eid: int,
        message_type: MCTPMessageType,
        payload: bytes,
    ) -> int:
        """Send an MCTP request packet over I2C.

        Returns the message tag used (for matching the response).
        """
        with self._lock:
            tag = self._next_tag()

        mctp_pkt = build_mctp_packet(
            dest_eid=dest_eid,
            source_eid=self._config.own_eid,
            message_type=message_type,
            payload=payload,
            tag_owner=True,
            msg_tag=tag,
        )

        i2c_frame = build_i2c_mctp_frame(
            dest_slave_addr=dest_addr,
            source_slave_addr=self._config.own_slave_addr,
            mctp_packet=mctp_pkt,
        )

        # Send via I2C write — the frame bytes go as the data payload
        self._bus.write(dest_addr, list(i2c_frame))
        logger.debug(
            "mctp_sent",
            dest=f"0x{dest_addr:02X}",
            eid=dest_eid,
            tag=tag,
            msg_type=message_type.name,
            size=len(payload),
        )
        return tag

    def receive_response(
        self,
        dest_addr: int,
        expected_tag: int | None = None,
    ) -> MCTPPacket:
        """Read an MCTP response from an I2C target.

        Does a block read from the target address and parses the
        I2C MCTP frame.
        """
        # Read enough bytes for a max-size MCTP frame
        raw = self._bus.read(
            address=dest_addr,
            register=MCTP_I2C_COMMAND_CODE,
            count=MCTP_I2C_MAX_FRAME,
        )

        packet = parse_i2c_mctp_frame(
            bytes(raw), dest_slave_addr=self._config.own_slave_addr
        )

        if expected_tag is not None and packet.header.msg_tag != expected_tag:
            raise ValueError(
                f"Tag mismatch: expected {expected_tag}, "
                f"got {packet.header.msg_tag}"
            )

        logger.debug(
            "mctp_received",
            src_eid=packet.header.source_eid,
            tag=packet.header.msg_tag,
            msg_type=packet.message_type.name,
            size=len(packet.payload),
        )
        return packet

    def exchange(
        self,
        dest_addr: int,
        dest_eid: int,
        message_type: MCTPMessageType,
        payload: bytes,
    ) -> MCTPPacket:
        """Send an MCTP request and wait for the response."""
        tag = self.send_request(dest_addr, dest_eid, message_type, payload)
        return self.receive_response(dest_addr, expected_tag=tag)


class MCTPOverI3C:
    """MCTP transport over I3C.

    I3C private transfers don't need the SMBus framing layer.
    MCTP packets are sent directly as I3C private write/read.
    """

    def __init__(self, bus: Bus, config: MCTPTransportConfig | None = None) -> None:
        self._bus = bus
        self._config = config or MCTPTransportConfig()
        self._msg_tag = 0
        self._lock = threading.Lock()

    @property
    def bus(self) -> Bus:
        return self._bus

    def _next_tag(self) -> int:
        tag = self._msg_tag
        self._msg_tag = (self._msg_tag + 1) & 0x07
        return tag

    def send_request(
        self,
        dest_addr: int,
        dest_eid: int,
        message_type: MCTPMessageType,
        payload: bytes,
    ) -> int:
        """Send an MCTP request packet over I3C private write."""
        with self._lock:
            tag = self._next_tag()

        mctp_pkt = build_mctp_packet(
            dest_eid=dest_eid,
            source_eid=self._config.own_eid,
            message_type=message_type,
            payload=payload,
            tag_owner=True,
            msg_tag=tag,
        )

        self._bus.write(dest_addr, list(mctp_pkt))
        logger.debug(
            "mctp_i3c_sent",
            dest=f"0x{dest_addr:02X}",
            eid=dest_eid,
            tag=tag,
            size=len(payload),
        )
        return tag

    def receive_response(
        self,
        dest_addr: int,
        expected_tag: int | None = None,
    ) -> MCTPPacket:
        """Read an MCTP response via I3C private read."""
        raw = self._bus.read(address=dest_addr, register=0, count=69)
        packet = parse_mctp_packet(bytes(raw))

        if expected_tag is not None and packet.header.msg_tag != expected_tag:
            raise ValueError(
                f"Tag mismatch: expected {expected_tag}, "
                f"got {packet.header.msg_tag}"
            )
        return packet

    def exchange(
        self,
        dest_addr: int,
        dest_eid: int,
        message_type: MCTPMessageType,
        payload: bytes,
    ) -> MCTPPacket:
        """Send an MCTP request and wait for the response."""
        tag = self.send_request(dest_addr, dest_eid, message_type, payload)
        return self.receive_response(dest_addr, expected_tag=tag)
