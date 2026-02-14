"""MCTP (Management Component Transport Protocol) implementation.

Implements DMTF DSP0236 (MCTP Base) and DSP0237 (MCTP over I2C)
for out-of-band management traffic over I2C/I3C buses.
"""

from calypso.mctp.endpoint import MCTPEndpoint
from calypso.mctp.framing import build_mctp_packet, parse_mctp_packet
from calypso.mctp.transport import MCTPOverI2C, MCTPOverI3C
from calypso.mctp.types import MCTPMessageType

__all__ = [
    "MCTPEndpoint",
    "MCTPMessageType",
    "MCTPOverI2C",
    "MCTPOverI3C",
    "build_mctp_packet",
    "parse_mctp_packet",
]
