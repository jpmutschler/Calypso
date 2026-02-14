"""Unit tests for NVMe-MI command builders and response parsers."""

from __future__ import annotations

import struct

import pytest

from calypso.nvme_mi.commands import (
    build_controller_health_poll,
    build_mi_header,
    build_read_mi_data_structure,
    build_subsystem_health_poll,
    parse_controller_health_poll,
    parse_read_mi_data_structure,
    parse_subsystem_health_poll,
)
from calypso.nvme_mi.types import NVMeMIOpcode, NVMeMIStatus


class TestBuildMIHeader:
    """Test NVMe-MI message header construction."""

    def test_request_header(self):
        h = build_mi_header(NVMeMIOpcode.SUBSYSTEM_HEALTH_STATUS_POLL)
        assert len(h) == 4
        assert h[1] == 0x00  # ROR=0 (request)
        assert h[3] == 0x01  # opcode

    def test_response_header(self):
        h = build_mi_header(NVMeMIOpcode.READ_MI_DATA_STRUCTURE, is_request=False)
        assert h[1] == 0x80  # ROR=1 (response)
        assert h[3] == 0x00  # opcode


class TestSubsystemHealthPoll:
    """Test Subsystem Health Status Poll command build/parse."""

    def test_build_request(self):
        req = build_subsystem_health_poll()
        assert len(req) == 4
        assert req[3] == NVMeMIOpcode.SUBSYSTEM_HEALTH_STATUS_POLL

    def test_parse_healthy_response(self):
        # Build a response: 4-byte header + status + fields
        data = bytearray(19)
        data[0:4] = build_mi_header(NVMeMIOpcode.SUBSYSTEM_HEALTH_STATUS_POLL, is_request=False)
        data[4] = NVMeMIStatus.SUCCESS
        data[5] = 0x00  # no critical warning
        struct.pack_into("<H", data, 6, 273 + 42)  # 42°C in Kelvin
        data[8] = 95  # available spare
        data[9] = 10  # spare threshold
        data[10] = 5  # percentage used
        struct.pack_into("<I", data, 15, 100)  # 10,000 hours (100 * 100)

        health = parse_subsystem_health_poll(bytes(data))
        assert health.composite_temperature_celsius == 42
        assert health.available_spare_percent == 95
        assert health.available_spare_threshold_percent == 10
        assert health.percentage_used == 5
        assert health.power_on_hours == 10000
        assert health.has_critical_warning is False

    def test_parse_critical_warning_response(self):
        data = bytearray(19)
        data[0:4] = build_mi_header(NVMeMIOpcode.SUBSYSTEM_HEALTH_STATUS_POLL, is_request=False)
        data[4] = NVMeMIStatus.SUCCESS
        data[5] = 0x03  # spare below threshold + temperature exceeded
        struct.pack_into("<H", data, 6, 273 + 85)  # 85°C
        data[8] = 5  # low spare
        data[9] = 10
        data[10] = 90  # heavily used

        health = parse_subsystem_health_poll(bytes(data))
        assert health.has_critical_warning is True
        assert health.spare_below_threshold is True
        assert health.temperature_exceeded is True
        assert health.reliability_degraded is False
        assert health.composite_temperature_celsius == 85
        assert health.drive_life_remaining_percent == 10

    def test_parse_error_status(self):
        data = bytearray(8)
        data[0:4] = build_mi_header(NVMeMIOpcode.SUBSYSTEM_HEALTH_STATUS_POLL, is_request=False)
        data[4] = NVMeMIStatus.INTERNAL_ERROR

        with pytest.raises(ValueError, match="status 0x02"):
            parse_subsystem_health_poll(bytes(data))

    def test_parse_too_short(self):
        with pytest.raises(ValueError, match="too short"):
            parse_subsystem_health_poll(b"\x00\x80\x00\x01\x00")


class TestControllerHealthPoll:
    """Test Controller Health Status Poll command build/parse."""

    def test_build_request_includes_controller_id(self):
        req = build_controller_health_poll(controller_id=1)
        assert len(req) == 6  # 4 header + 2 controller ID
        assert req[3] == NVMeMIOpcode.CONTROLLER_HEALTH_STATUS_POLL
        assert struct.unpack_from("<H", req, 4)[0] == 1

    def test_parse_response(self):
        data = bytearray(10)
        data[0:4] = build_mi_header(NVMeMIOpcode.CONTROLLER_HEALTH_STATUS_POLL, is_request=False)
        data[4] = NVMeMIStatus.SUCCESS
        data[5] = 0x00  # no warning
        struct.pack_into("<H", data, 6, 273 + 35)  # 35°C
        data[8] = 100  # full spare
        data[9] = 2  # 2% used

        health = parse_controller_health_poll(bytes(data), controller_id=1)
        assert health.controller_id == 1
        assert health.composite_temperature_celsius == 35
        assert health.available_spare_percent == 100


class TestReadMIDataStructure:
    """Test Read MI Data Structure command build/parse."""

    def test_build_request(self):
        req = build_read_mi_data_structure()
        assert len(req) == 8  # 4 header + 4 params
        assert req[3] == NVMeMIOpcode.READ_MI_DATA_STRUCTURE

    def test_parse_with_nqn(self):
        nqn_str = "nqn.2024-01.com.example:nvme:sn123"
        nqn_bytes = nqn_str.encode("utf-8") + b"\x00"

        data = bytearray(8 + len(nqn_bytes))
        data[0:4] = build_mi_header(NVMeMIOpcode.READ_MI_DATA_STRUCTURE, is_request=False)
        data[4] = NVMeMIStatus.SUCCESS
        data[5] = 2  # 2 ports
        data[6] = 1  # major version
        data[7] = 2  # minor version
        data[8:8 + len(nqn_bytes)] = nqn_bytes

        info = parse_read_mi_data_structure(bytes(data))
        assert info.nqn == nqn_str
        assert info.number_of_ports == 2
        assert info.major_version == 1
        assert info.minor_version == 2

    def test_parse_minimal_response(self):
        data = bytearray(8)
        data[0:4] = build_mi_header(NVMeMIOpcode.READ_MI_DATA_STRUCTURE, is_request=False)
        data[4] = NVMeMIStatus.SUCCESS
        data[5] = 1

        info = parse_read_mi_data_structure(bytes(data))
        assert info.number_of_ports == 1
        assert info.nqn == ""
