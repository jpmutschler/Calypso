"""NVMe-MI command builders and response parsers.

Builds MCTP payload bytes for NVMe-MI commands and parses
the responses into structured data.
"""

from __future__ import annotations

import struct

from calypso.nvme_mi.models import (
    NVMeControllerHealth,
    NVMeHealthStatus,
    NVMeSubsystemInfo,
)
from calypso.nvme_mi.types import NVMeMIOpcode, NVMeMIStatus


def build_mi_header(opcode: NVMeMIOpcode, *, is_request: bool = True) -> bytes:
    """Build a 4-byte NVMe-MI message header.

    Layout:
        Byte 0: Reserved (NVMe-MI over MCTP, type is in MCTP header)
        Byte 1: [7] ROR (0=request, 1=response), [6:4] reserved, [3:0] reserved
        Byte 2: Reserved
        Byte 3: Opcode
    """
    ror = 0x00 if is_request else 0x80
    return bytes([0x00, ror, 0x00, opcode & 0xFF])


def build_subsystem_health_poll() -> bytes:
    """Build Subsystem Health Status Poll request (opcode 0x01)."""
    return build_mi_header(NVMeMIOpcode.SUBSYSTEM_HEALTH_STATUS_POLL)


def parse_subsystem_health_poll(data: bytes) -> NVMeHealthStatus:
    """Parse Subsystem Health Status Poll response.

    Response layout after 4-byte MI header:
        Byte 4: Status
        Byte 5: Critical Warning
        Byte 6-7: Composite Temperature (Kelvin, LE16)
        Byte 8: Available Spare (%)
        Byte 9: Available Spare Threshold (%)
        Byte 10: Percentage Used
        Byte 11-14: Reserved
        Byte 15-18: Power On Hours (LE32, units of 100 hours)
    """
    if len(data) < 8:
        raise ValueError(f"Health response too short: {len(data)} bytes")

    status = data[4]
    if status != NVMeMIStatus.SUCCESS:
        raise ValueError(f"Health poll failed: status 0x{status:02X}")

    critical_warning = data[5] if len(data) > 5 else 0
    temp_kelvin = struct.unpack_from("<H", data, 6)[0] if len(data) > 7 else 0
    temp_celsius = temp_kelvin - 273 if temp_kelvin > 0 else 0
    available_spare = data[8] if len(data) > 8 else 100
    spare_threshold = data[9] if len(data) > 9 else 10
    percentage_used = data[10] if len(data) > 10 else 0

    power_on_hours = 0
    if len(data) >= 19:
        power_on_hours = struct.unpack_from("<I", data, 15)[0] * 100

    return NVMeHealthStatus(
        composite_temperature_celsius=temp_celsius,
        available_spare_percent=available_spare,
        available_spare_threshold_percent=spare_threshold,
        percentage_used=percentage_used,
        critical_warning=critical_warning,
        power_on_hours=power_on_hours,
    )


def build_controller_health_poll(controller_id: int) -> bytes:
    """Build Controller Health Status Poll request (opcode 0x02).

    Adds a 2-byte controller ID after the MI header.
    """
    header = build_mi_header(NVMeMIOpcode.CONTROLLER_HEALTH_STATUS_POLL)
    return header + struct.pack("<H", controller_id)


def parse_controller_health_poll(data: bytes, controller_id: int) -> NVMeControllerHealth:
    """Parse Controller Health Status Poll response."""
    if len(data) < 8:
        raise ValueError(f"Controller health response too short: {len(data)} bytes")

    status = data[4]
    if status != NVMeMIStatus.SUCCESS:
        raise ValueError(f"Controller health poll failed: status 0x{status:02X}")

    critical_warning = data[5] if len(data) > 5 else 0
    temp_kelvin = struct.unpack_from("<H", data, 6)[0] if len(data) > 7 else 0
    temp_celsius = temp_kelvin - 273 if temp_kelvin > 0 else 0
    available_spare = data[8] if len(data) > 8 else 100
    percentage_used = data[9] if len(data) > 9 else 0

    return NVMeControllerHealth(
        controller_id=controller_id,
        composite_temperature_celsius=temp_celsius,
        available_spare_percent=available_spare,
        percentage_used=percentage_used,
        critical_warning=critical_warning,
    )


def build_read_mi_data_structure() -> bytes:
    """Build Read MI Data Structure request (opcode 0x00).

    Reads the NVM Subsystem Information data structure.
    """
    header = build_mi_header(NVMeMIOpcode.READ_MI_DATA_STRUCTURE)
    # Data structure type 0 = NVM Subsystem Info, offset 0, count=max
    return header + bytes([0x00, 0x00, 0x00, 0x00])


def parse_read_mi_data_structure(data: bytes) -> NVMeSubsystemInfo:
    """Parse Read MI Data Structure response (NVM Subsystem Information).

    Response layout after 4-byte MI header + 1 status byte:
        Byte 5: Number of Ports
        Byte 6: Major Version
        Byte 7: Minor Version
        Byte 8-263: NQN (256 bytes, UTF-8, null-terminated)
    """
    if len(data) < 6:
        raise ValueError(f"MI data structure response too short: {len(data)} bytes")

    status = data[4]
    if status != NVMeMIStatus.SUCCESS:
        raise ValueError(f"Read MI data failed: status 0x{status:02X}")

    num_ports = data[5] if len(data) > 5 else 0
    major_ver = data[6] if len(data) > 6 else 0
    minor_ver = data[7] if len(data) > 7 else 0

    nqn = ""
    if len(data) > 8:
        nqn_bytes = data[8:264]
        nqn = nqn_bytes.split(b"\x00")[0].decode("utf-8", errors="replace")

    return NVMeSubsystemInfo(
        nqn=nqn,
        number_of_ports=num_ports,
        major_version=major_ver,
        minor_version=minor_ver,
    )
