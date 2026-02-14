"""MCTP message types, header constants, and error codes.

References: DMTF DSP0236 (MCTP Base Specification)
"""

from __future__ import annotations

from enum import IntEnum


# MCTP header version (DSP0236 §8.1)
MCTP_HEADER_VERSION = 0x01

# I2C command code for MCTP (DSP0237 §8.1)
MCTP_I2C_COMMAND_CODE = 0x0F

# Maximum MCTP payload per packet (64 bytes per DSP0236 §8.3.1)
MCTP_MAX_PAYLOAD = 64

# Maximum MCTP over I2C frame = 4 (MCTP header) + 64 (payload) + overhead
MCTP_I2C_MAX_FRAME = 73

# Null EID for unassigned endpoints
MCTP_NULL_EID = 0x00

# Broadcast EID
MCTP_BROADCAST_EID = 0xFF


class MCTPMessageType(IntEnum):
    """MCTP message type codes (DSP0236 §11.1)."""

    CONTROL = 0x00
    PLDM = 0x01
    NCSI = 0x02
    ETHERNET = 0x03
    NVME_MI = 0x04
    SPDM = 0x05
    SECURED_MCTP = 0x06
    CXL_FM_API = 0x07
    CXL_CCI = 0x08
    VENDOR_PCI = 0x7E
    VENDOR_IANA = 0x7F


class MCTPControlCommand(IntEnum):
    """MCTP control message commands (DSP0236 §12.3)."""

    SET_ENDPOINT_ID = 0x01
    GET_ENDPOINT_ID = 0x02
    GET_ENDPOINT_UUID = 0x03
    GET_MCTP_VERSION = 0x04
    GET_MESSAGE_TYPE_SUPPORT = 0x05


class MCTPCompletionCode(IntEnum):
    """MCTP control message completion codes (DSP0236 §12.2)."""

    SUCCESS = 0x00
    ERROR = 0x01
    ERROR_INVALID_DATA = 0x02
    ERROR_INVALID_LENGTH = 0x03
    ERROR_NOT_READY = 0x04
    ERROR_UNSUPPORTED_CMD = 0x05
