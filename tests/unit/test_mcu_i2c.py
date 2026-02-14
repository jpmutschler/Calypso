"""Unit tests for MCU I2C/I3C read, write, scan, and bus abstraction."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from calypso.mcu.bus import I2cBus, I3cBus
from calypso.mcu.models import (
    I2cReadResponse,
    I2cScanResult,
    I3cDevice,
    I3cEntdaaResult,
    I3cReadResponse,
)


class TestI2cModels:
    """Test I2C/I3C Pydantic models."""

    def test_i2c_read_response_hex_dump(self):
        resp = I2cReadResponse(data=[0xDE, 0xAD, 0xBE, 0xEF])
        assert resp.hex_dump == "DE AD BE EF"

    def test_i2c_scan_result_properties(self):
        result = I2cScanResult(connector=0, channel="a", devices=[0x50, 0x51, 0x6A])
        assert result.device_count == 3
        assert result.devices_hex == ["0x50", "0x51", "0x6A"]

    def test_i2c_scan_result_empty(self):
        result = I2cScanResult(connector=0, channel="a", devices=[])
        assert result.device_count == 0

    def test_i3c_device_mctp_support(self):
        dev_mctp = I3cDevice(bcr=0x20, dynamic_address=0x08)
        assert dev_mctp.supports_mctp is True

        dev_no_mctp = I3cDevice(bcr=0x00, dynamic_address=0x09)
        assert dev_no_mctp.supports_mctp is False

    def test_i3c_device_pid_hex(self):
        dev = I3cDevice(provisional_id=[0x01, 0x02, 0x03, 0x04, 0x05, 0x06])
        assert dev.pid_hex == "010203040506"

    def test_i3c_entdaa_result_count(self):
        result = I3cEntdaaResult(
            connector=0,
            channel="a",
            devices=[I3cDevice(dynamic_address=0x08), I3cDevice(dynamic_address=0x09)],
        )
        assert result.device_count == 2

    def test_i3c_read_response_hex_dump(self):
        resp = I3cReadResponse(data=[0xCA, 0xFE])
        assert resp.hex_dump == "CA FE"

    def test_model_serialization_round_trip(self):
        result = I2cScanResult(connector=1, channel="b", devices=[0x50])
        data = result.model_dump()
        restored = I2cScanResult.model_validate(data)
        assert restored.connector == 1
        assert restored.channel == "b"
        assert restored.devices == [0x50]


class TestMcuClientI2cScan:
    """Test McuClient.i2c_scan() with mock Atlas3."""

    def _make_client(self, atlas3_mock):
        with patch("calypso.mcu.client.McuClient.connect"):
            from calypso.mcu.client import McuClient
            client = McuClient.__new__(McuClient)
            client._port = "COM3"
            client._baudrate = 115200
            client._timeout = 5.0
            client._atlas3 = atlas3_mock
        return client

    def test_i2c_scan_finds_devices(self):
        atlas3 = MagicMock()
        # Make addresses 0x50 and 0x51 respond, everything else raises
        def side_effect(addr, connector, channel, count, register):
            result = MagicMock()
            if addr in (0x50, 0x51):
                result.data = [0x00]
            else:
                raise OSError("NAK")
            return result

        atlas3.i2c_read.side_effect = side_effect
        atlas3.is_connected = True

        client = self._make_client(atlas3)
        result = client.i2c_scan(connector=0, channel="a")

        assert isinstance(result, I2cScanResult)
        assert 0x50 in result.devices
        assert 0x51 in result.devices

    def test_i2c_scan_empty_bus(self):
        atlas3 = MagicMock()
        atlas3.i2c_read.side_effect = OSError("NAK")
        atlas3.is_connected = True

        client = self._make_client(atlas3)
        result = client.i2c_scan(connector=0, channel="a")

        assert result.device_count == 0

    def test_i2c_scan_requires_connection(self):
        atlas3 = MagicMock()
        atlas3.is_connected = False

        client = self._make_client(atlas3)
        with pytest.raises(RuntimeError, match="not connected"):
            client.i2c_scan(connector=0, channel="a")


class TestI2cBus:
    """Test the I2cBus abstraction layer."""

    def test_bus_type(self):
        client = MagicMock()
        bus = I2cBus(client, connector=0, channel="a")
        assert bus.bus_type == "i2c"
        assert bus.connector == 0
        assert bus.channel == "a"

    def test_read_delegates_to_client(self):
        client = MagicMock()
        client.i2c_read.return_value = [0xAA, 0xBB]
        bus = I2cBus(client, connector=1, channel="b")

        data = bus.read(address=0x50, register=0x00, count=2)

        assert data == [0xAA, 0xBB]
        client.i2c_read.assert_called_once_with(
            address=0x50, connector=1, channel="b",
            read_bytes=2, register=0x00,
        )

    def test_write_delegates_to_client(self):
        client = MagicMock()
        client.i2c_write.return_value = True
        bus = I2cBus(client, connector=0, channel="a")

        result = bus.write(address=0x50, data=[0x01, 0x02])

        assert result is True
        client.i2c_write.assert_called_once_with(
            address=0x50, connector=0, channel="a",
            data=[0x01, 0x02],
        )

    def test_write_register_prepends_register_byte(self):
        client = MagicMock()
        client.i2c_write.return_value = True
        bus = I2cBus(client, connector=0, channel="a")

        bus.write_register(address=0x50, register=0x10, data=[0xAA])

        client.i2c_write.assert_called_once_with(
            address=0x50, connector=0, channel="a",
            data=[0x10, 0xAA],
        )


class TestI3cBus:
    """Test the I3cBus abstraction layer."""

    def test_bus_type(self):
        client = MagicMock()
        bus = I3cBus(client, connector=2, channel="a")
        assert bus.bus_type == "i3c"

    def test_read_returns_data_from_response(self):
        client = MagicMock()
        client.i3c_read.return_value = I3cReadResponse(data=[0x11, 0x22])
        bus = I3cBus(client, connector=0, channel="a")

        data = bus.read(address=0x08, register=0, count=2)
        assert data == [0x11, 0x22]

    def test_write_delegates_to_client(self):
        client = MagicMock()
        client.i3c_write.return_value = True
        bus = I3cBus(client, connector=0, channel="a")

        result = bus.write(address=0x08, data=[0x01])
        assert result is True
