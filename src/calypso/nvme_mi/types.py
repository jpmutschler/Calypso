"""NVMe-MI opcodes, status codes, and constants.

References: NVMe Management Interface Specification 1.2
"""

from __future__ import annotations

from enum import IntEnum


class NVMeMIOpcode(IntEnum):
    """NVMe-MI command opcodes (NVMe-MI §5)."""

    READ_MI_DATA_STRUCTURE = 0x00
    SUBSYSTEM_HEALTH_STATUS_POLL = 0x01
    CONTROLLER_HEALTH_STATUS_POLL = 0x02
    CONFIGURATION_SET = 0x03
    CONFIGURATION_GET = 0x04


class NVMeMIStatus(IntEnum):
    """NVMe-MI response status codes (NVMe-MI §5.2)."""

    SUCCESS = 0x00
    MORE_PROCESSING_REQUIRED = 0x01
    INTERNAL_ERROR = 0x02
    INVALID_PARAMETER = 0x03
    INVALID_COMMAND_SIZE = 0x04
    INVALID_COMMAND_OPCODE = 0x05
    INVALID_TRANSFER_FLAG = 0x06
    PCIe_INACCESSIBLE = 0x07


class NVMeMICriticalWarning(IntEnum):
    """Critical warning bit flags from health status."""

    SPARE_BELOW_THRESHOLD = 0x01
    TEMPERATURE_EXCEEDED = 0x02
    RELIABILITY_DEGRADED = 0x04
    READ_ONLY_MODE = 0x08
    VOLATILE_BACKUP_FAILED = 0x10


# Default I2C address for NVMe-MI endpoints (NVMe-MI §3.2)
NVME_MI_DEFAULT_I2C_ADDR = 0x6A

# NVMe-MI message header NMIMT field value
NVME_MI_MESSAGE_TYPE = 0x04

# NVMe-MI request/response header sizes
NVME_MI_HEADER_SIZE = 4  # NMIMT(1) + ROR/flags(1) + reserved(1) + opcode(1)
