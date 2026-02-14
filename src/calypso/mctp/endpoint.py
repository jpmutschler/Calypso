"""MCTP endpoint discovery and management.

Provides EID discovery by sending MCTP control messages
(Get Endpoint ID) to targets on the bus.
"""

from __future__ import annotations

from dataclasses import dataclass

from calypso.mctp.transport import MCTPOverI2C, MCTPOverI3C  # noqa: F401 — used in type hint
from calypso.mctp.types import (
    MCTP_NULL_EID,
    MCTPCompletionCode,
    MCTPControlCommand,
    MCTPMessageType,
)
from calypso.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class MCTPEndpoint:
    """Discovered MCTP endpoint."""

    eid: int
    slave_addr: int
    endpoint_type: str  # "simple" or "bus_owner"
    medium_specific: int  # medium-specific info from response
    message_types: list[MCTPMessageType]

    @property
    def supports_nvme_mi(self) -> bool:
        return MCTPMessageType.NVME_MI in self.message_types


def _build_get_eid_request() -> bytes:
    """Build MCTP Control Get Endpoint ID request payload (DSP0236 §12.3)."""
    # Control message header: [IC=0, msg_type=0x00 (control)]
    # Request byte: [7] Rq=1, [6] D=0, [5:0] command code
    rq_byte = 0x80 | (MCTPControlCommand.GET_ENDPOINT_ID & 0x3F)
    return bytes([rq_byte])


def _parse_get_eid_response(payload: bytes) -> tuple[int, str, int]:
    """Parse Get Endpoint ID response payload.

    Returns (eid, endpoint_type_str, medium_specific).
    """
    if len(payload) < 4:
        raise ValueError(f"Get EID response too short: {len(payload)} bytes")

    completion_code = payload[0]
    if completion_code != MCTPCompletionCode.SUCCESS:
        raise ValueError(f"Get EID failed: completion code 0x{completion_code:02X}")

    eid = payload[1]
    eid_type = (payload[2] >> 4) & 0x03
    medium_specific = payload[3]

    type_str = "bus_owner" if eid_type == 0x01 else "simple"
    return eid, type_str, medium_specific


def discover_endpoint(
    transport: MCTPOverI2C | MCTPOverI3C,
    slave_addr: int,
) -> MCTPEndpoint | None:
    """Discover an MCTP endpoint at the given slave address.

    Sends Get Endpoint ID and returns an MCTPEndpoint if the
    device responds, or None if no response / error.
    """
    try:
        request_payload = _build_get_eid_request()
        response = transport.exchange(
            dest_addr=slave_addr,
            dest_eid=MCTP_NULL_EID,
            message_type=MCTPMessageType.CONTROL,
            payload=request_payload,
        )

        eid, endpoint_type, medium_specific = _parse_get_eid_response(
            response.payload
        )

        logger.info(
            "mctp_endpoint_found",
            addr=f"0x{slave_addr:02X}",
            eid=eid,
            type=endpoint_type,
        )

        return MCTPEndpoint(
            eid=eid,
            slave_addr=slave_addr,
            endpoint_type=endpoint_type,
            medium_specific=medium_specific,
            message_types=[MCTPMessageType.CONTROL],
        )

    except Exception as exc:
        logger.debug(
            "mctp_endpoint_not_found",
            addr=f"0x{slave_addr:02X}",
            error=str(exc),
        )
        return None
