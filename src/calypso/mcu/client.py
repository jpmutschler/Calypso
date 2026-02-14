"""MCU client wrapping the serialcables-atlas3 package.

Provides a clean interface to MCU-level features (thermal monitoring,
port status, error counters, firmware, BIST, etc.) that complements
the PLX SDK register-level access.
"""

from __future__ import annotations

from typing import Callable

from calypso.mcu.models import (
    I2cScanResult,
    I3cDevice,
    I3cEntdaaResult,
    I3cReadResponse,
    McuBistDevice,
    McuBistResult,
    McuClockStatus,
    McuDeviceInfo,
    McuErrorCounters,
    McuErrorSnapshot,
    McuFanInfo,
    McuFlitStatus,
    McuPortInfo,
    McuPortStatus,
    McuPowerInfo,
    McuSpreadStatus,
    McuThermalInfo,
    McuThermalStatus,
    McuVersionInfo,
    McuVoltageInfo,
)
from calypso.utils.logging import get_logger

logger = get_logger(__name__)


def _port_info_from_atlas3(port) -> McuPortInfo:
    """Convert a serialcables_atlas3 PortInfo to our model."""
    return McuPortInfo(
        station=getattr(port, "station", 0),
        connector=getattr(port, "connector", ""),
        port_number=getattr(port, "port_number", 0),
        negotiated_speed=getattr(port, "negotiated_speed", ""),
        negotiated_width=getattr(port, "negotiated_width", 0),
        max_speed=getattr(port, "max_speed", ""),
        max_width=getattr(port, "max_width", 0),
        status=getattr(port, "status", ""),
        port_type=str(getattr(port, "port_type", "")),
    )


class McuClient:
    """Client for MCU-level Atlas3 features via serialcables-atlas3.

    Wraps the serialcables_atlas3.Atlas3 class to provide Pydantic
    models and structured logging consistent with the rest of Calypso.

    Usage:
        with McuClient("/dev/ttyUSB0") as mcu:
            info = mcu.get_version()
            thermal = mcu.get_thermal_status()
            ports = mcu.get_port_status()
    """

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        timeout: float = 5.0,
        auto_connect: bool = True,
    ) -> None:
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._atlas3 = None

        if auto_connect:
            self.connect()

    @property
    def is_connected(self) -> bool:
        return self._atlas3 is not None and getattr(self._atlas3, "is_connected", False)

    @property
    def port(self) -> str:
        return self._port

    def connect(self) -> None:
        """Connect to the Atlas3 MCU."""
        if self.is_connected:
            return

        from serialcables_atlas3 import Atlas3

        logger.info("mcu_connecting", port=self._port)
        self._atlas3 = Atlas3(
            port=self._port,
            baudrate=self._baudrate,
            timeout=self._timeout,
            auto_connect=True,
        )
        logger.info("mcu_connected", port=self._port)

    def disconnect(self) -> None:
        """Disconnect from the Atlas3 MCU."""
        if self._atlas3 is not None:
            logger.info("mcu_disconnecting", port=self._port)
            self._atlas3.disconnect()
            self._atlas3 = None
            logger.info("mcu_disconnected", port=self._port)

    def __enter__(self) -> McuClient:
        if not self.is_connected:
            self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.disconnect()

    def _require_connection(self) -> None:
        if not self.is_connected:
            raise RuntimeError("MCU not connected. Call connect() first.")

    # --- Device Information ---

    def get_version(self) -> McuVersionInfo:
        """Get firmware and hardware version info."""
        self._require_connection()
        v = self._atlas3.get_version()
        return McuVersionInfo(
            company=getattr(v, "company", ""),
            model=getattr(v, "model", ""),
            serial_number=getattr(v, "serial_number", ""),
            mcu_version=getattr(v, "mcu_version", ""),
            mcu_build_time=getattr(v, "mcu_build_time", ""),
            sbr_version=getattr(v, "sbr_version", ""),
        )

    def get_device_info(self) -> McuDeviceInfo:
        """Get combined device information snapshot."""
        self._require_connection()
        return McuDeviceInfo(
            version=self.get_version(),
            thermal_status=self.get_thermal_status(),
            port_status=self.get_port_status(),
            connected=True,
            port=self._port,
        )

    def get_system_info(self) -> str:
        """Get raw system info string."""
        self._require_connection()
        return self._atlas3.get_system_info()

    # --- Thermal / Power / Fan ---

    def get_thermal_status(self) -> McuThermalStatus:
        """Get combined thermal, fan, voltage, and power readings."""
        self._require_connection()
        info = self._atlas3.get_host_card_info()
        return McuThermalStatus(
            thermal=McuThermalInfo(
                switch_temperature_celsius=getattr(
                    info.thermal, "switch_temperature_celsius", 0.0
                ),
            ),
            fan=McuFanInfo(
                switch_fan_rpm=getattr(info.fan, "switch_fan_rpm", 0),
            ),
            voltages=McuVoltageInfo(
                voltage_1v5=getattr(info.voltages, "voltage_1v5", 0.0),
                voltage_vdd=getattr(info.voltages, "voltage_vdd", 0.0),
                voltage_vdda=getattr(info.voltages, "voltage_vdda", 0.0),
                voltage_vdda12=getattr(info.voltages, "voltage_vdda12", 0.0),
            ),
            power=McuPowerInfo(
                power_voltage=getattr(info.power, "power_voltage", 0.0),
                load_current=getattr(info.power, "load_current", 0.0),
                load_power=getattr(info.power, "load_power", 0.0),
            ),
        )

    # --- Port Status ---

    def get_port_status(self) -> McuPortStatus:
        """Get port status for all stations."""
        self._require_connection()
        ps = self._atlas3.get_port_status()
        return McuPortStatus(
            chip_version=getattr(ps, "chip_version", ""),
            upstream_ports=[_port_info_from_atlas3(p) for p in getattr(ps, "upstream_ports", [])],
            ext_mcio_ports=[_port_info_from_atlas3(p) for p in getattr(ps, "ext_mcio_ports", [])],
            int_mcio_ports=[_port_info_from_atlas3(p) for p in getattr(ps, "int_mcio_ports", [])],
            straddle_ports=[_port_info_from_atlas3(p) for p in getattr(ps, "straddle_ports", [])],
        )

    # --- Error Counters ---

    def get_error_counters(self) -> McuErrorSnapshot:
        """Get error counters for all ports."""
        self._require_connection()
        all_errors = self._atlas3.get_error_counters()
        return McuErrorSnapshot(
            counters=[
                McuErrorCounters(
                    port_number=getattr(c, "port_number", 0),
                    port_rx=getattr(c, "port_rx", 0),
                    bad_tlp=getattr(c, "bad_tlp", 0),
                    bad_dllp=getattr(c, "bad_dllp", 0),
                    rec_diag=getattr(c, "rec_diag", 0),
                    link_down=getattr(c, "link_down", 0),
                    flit_error=getattr(c, "flit_error", 0),
                )
                for c in getattr(all_errors, "counters", [])
            ]
        )

    def clear_error_counters(self) -> bool:
        """Clear all error counters."""
        self._require_connection()
        return self._atlas3.clear_error_counters()

    # --- Configuration ---

    def get_mode(self) -> str:
        """Get current operation mode."""
        self._require_connection()
        mode = self._atlas3.get_mode()
        return str(mode.value) if hasattr(mode, "value") else str(mode)

    def set_mode(self, mode: int | str) -> bool:
        """Set operation mode (1-4)."""
        self._require_connection()
        return self._atlas3.set_mode(mode)

    def get_clock_status(self) -> McuClockStatus:
        """Get clock output status."""
        self._require_connection()
        cs = self._atlas3.get_clock_status()
        return McuClockStatus(
            straddle_enabled=getattr(cs, "straddle_enabled", False),
            ext_mcio_enabled=getattr(cs, "ext_mcio_enabled", False),
            int_mcio_enabled=getattr(cs, "int_mcio_enabled", False),
        )

    def set_clock_output(self, enable: bool) -> bool:
        """Enable or disable clock output."""
        self._require_connection()
        return self._atlas3.set_clock_output(enable)

    def get_spread_status(self) -> McuSpreadStatus:
        """Get spread spectrum status."""
        self._require_connection()
        ss = self._atlas3.get_spread_status()
        return McuSpreadStatus(
            enabled=getattr(ss, "enabled", False),
            mode=getattr(ss, "mode", ""),
        )

    def set_spread(self, mode: str) -> bool:
        """Set spread spectrum mode (off, down_2500ppm, down_5000ppm)."""
        self._require_connection()
        return self._atlas3.set_spread(mode)

    def get_flit_status(self) -> McuFlitStatus:
        """Get FLIT mode status per station."""
        self._require_connection()
        fs = self._atlas3.get_flit_status()
        return McuFlitStatus(
            station2=getattr(fs, "station2", False),
            station5=getattr(fs, "station5", False),
            station7=getattr(fs, "station7", False),
            station8=getattr(fs, "station8", False),
        )

    def set_flit_mode(self, station: int | str, disable: bool) -> bool:
        """Set FLIT mode for a station."""
        self._require_connection()
        return self._atlas3.set_flit_mode(station, disable)

    # --- SDB Target ---

    def get_sdb_target(self) -> str:
        """Get current SDB target (usb or mcu)."""
        self._require_connection()
        return self._atlas3.get_sdb_target()

    def set_sdb_target(self, target: str) -> bool:
        """Set SDB target (usb or mcu)."""
        self._require_connection()
        return self._atlas3.set_sdb_target(target)

    # --- Diagnostics ---

    def run_bist(self) -> McuBistResult:
        """Run Built-In Self Test."""
        self._require_connection()
        result = self._atlas3.run_bist()
        return McuBistResult(
            devices=[
                McuBistDevice(
                    device_id=getattr(d, "device_id", ""),
                    status=getattr(d, "status", ""),
                )
                for d in getattr(result, "devices", [])
            ]
        )

    # --- Register / Flash Access ---

    def read_register(self, address: int, count: int = 16) -> dict[int, int]:
        """Read registers starting at address.

        Returns dict mapping address -> value.
        """
        self._require_connection()
        dump = self._atlas3.read_register(address, count)
        start = getattr(dump, "start_address", address)
        values = getattr(dump, "values", [])
        return {start + (i * 4): v for i, v in enumerate(values)}

    def write_register(self, address: int, data: int) -> bool:
        """Write a value to a register address."""
        self._require_connection()
        return self._atlas3.write_register(address, data)

    def read_flash(self, address: int, count: int = 16) -> dict[int, int]:
        """Read flash memory starting at address.

        Returns dict mapping address -> value.
        """
        self._require_connection()
        dump = self._atlas3.read_flash(address, count)
        start = getattr(dump, "start_address", address)
        values = getattr(dump, "values", [])
        return {start + (i * 4): v for i, v in enumerate(values)}

    def read_port_registers(self, port_number: int) -> dict[int, int]:
        """Read registers for a specific port.

        Returns dict mapping address -> value.
        """
        self._require_connection()
        dump = self._atlas3.read_port_registers(port_number)
        start = getattr(dump, "start_address", 0)
        values = getattr(dump, "values", [])
        return {start + (i * 4): v for i, v in enumerate(values)}

    # --- I2C ---

    def i2c_read(
        self,
        address: int,
        connector: int,
        channel: str,
        read_bytes: int,
        register: int = 0,
    ) -> list[int]:
        """Read bytes from an I2C device.

        Returns list of byte values.
        """
        self._require_connection()
        result = self._atlas3.i2c_read(address, connector, channel, read_bytes, register)
        return getattr(result, "data", [])

    def i2c_write(
        self,
        address: int,
        connector: int,
        channel: str,
        data: list[int],
    ) -> bool:
        """Write bytes to an I2C device."""
        self._require_connection()
        result = self._atlas3.i2c_write(address, connector, channel, data)
        return result is not None

    def i2c_scan(
        self,
        connector: int,
        channel: str,
        start_addr: int = 0x03,
        end_addr: int = 0x77,
    ) -> I2cScanResult:
        """Scan an I2C bus for responding devices.

        Probes each 7-bit address in [start_addr, end_addr] by attempting
        a 1-byte read.  Returns addresses that ACK.
        """
        self._require_connection()
        found: list[int] = []
        for addr in range(start_addr, end_addr + 1):
            try:
                result = self._atlas3.i2c_read(addr, connector, channel, 1, 0)
                if getattr(result, "data", None) is not None:
                    found.append(addr)
            except Exception:
                continue
        logger.info(
            "i2c_scan_complete",
            connector=connector,
            channel=channel,
            found=len(found),
        )
        return I2cScanResult(connector=connector, channel=channel, devices=found)

    # --- I3C ---

    def i3c_read(
        self,
        address: int,
        connector: int,
        channel: str,
        read_bytes: int,
        register: int = 0,
    ) -> I3cReadResponse:
        """Read bytes from an I3C target device."""
        self._require_connection()
        result = self._atlas3.i3c_read(address, connector, channel, read_bytes, register)
        data = getattr(result, "data", [])
        return I3cReadResponse(
            connector=connector,
            channel=channel,
            address=address,
            reg_offset=register,
            data=data,
        )

    def i3c_write(
        self,
        address: int,
        connector: int,
        channel: str,
        data: list[int],
        register: int = 0,
    ) -> bool:
        """Write bytes to an I3C target device."""
        self._require_connection()
        result = self._atlas3.i3c_write(address, connector, channel, data, register)
        return result is not None

    def i3c_entdaa(
        self,
        connector: int,
        channel: str,
    ) -> I3cEntdaaResult:
        """Run I3C ENTDAA to discover and assign dynamic addresses."""
        self._require_connection()
        result = self._atlas3.i3c_entdaa(connector, channel)
        devices = []
        for dev in getattr(result, "devices", []):
            devices.append(
                I3cDevice(
                    provisional_id=getattr(dev, "provisional_id", b"\x00" * 6),
                    bcr=getattr(dev, "bcr", 0),
                    dcr=getattr(dev, "dcr", 0),
                    dynamic_address=getattr(dev, "dynamic_address", 0),
                )
            )
        logger.info(
            "i3c_entdaa_complete",
            connector=connector,
            channel=channel,
            found=len(devices),
        )
        return I3cEntdaaResult(
            connector=connector, channel=channel, devices=devices
        )

    # --- Firmware ---

    def prepare_firmware_update(self, firmware_type: str) -> str:
        """Prepare for firmware update. Returns preparation status message."""
        self._require_connection()
        return self._atlas3.prepare_firmware_update(firmware_type)

    def update_firmware(
        self,
        firmware_type: str,
        file_path: str,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> bool:
        """Update firmware from file."""
        self._require_connection()
        return self._atlas3.update_firmware(firmware_type, file_path, progress_callback)

    # --- Reset ---

    def reset_connector(self, connector: int | str) -> bool:
        """Reset a connector."""
        self._require_connection()
        return self._atlas3.reset_connector(connector)

    def reset_mcu(self) -> bool:
        """Reset the MCU."""
        self._require_connection()
        return self._atlas3.reset_mcu()

    # --- Device Discovery ---

    @staticmethod
    def find_devices() -> list[str]:
        """Find available Atlas3 devices on serial ports."""
        from serialcables_atlas3 import Atlas3

        return Atlas3.find_devices()
