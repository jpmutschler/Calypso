"""Pydantic models for MCU data, bridging serialcables-atlas3 dataclasses."""

from __future__ import annotations

from pydantic import BaseModel, Field


class McuVersionInfo(BaseModel):
    """Firmware and hardware version information from the MCU."""

    company: str = ""
    model: str = ""
    serial_number: str = ""
    mcu_version: str = ""
    mcu_build_time: str = ""
    sbr_version: str = ""


class McuThermalInfo(BaseModel):
    """Switch thermal readings."""

    switch_temperature_celsius: float = 0.0


class McuFanInfo(BaseModel):
    """Fan status."""

    switch_fan_rpm: int = 0


class McuVoltageInfo(BaseModel):
    """Voltage rail readings."""

    voltage_1v5: float = 0.0
    voltage_vdd: float = 0.0
    voltage_vdda: float = 0.0
    voltage_vdda12: float = 0.0


class McuPowerInfo(BaseModel):
    """Power consumption readings."""

    power_voltage: float = 0.0
    load_current: float = 0.0
    load_power: float = 0.0


class McuThermalStatus(BaseModel):
    """Combined thermal, fan, voltage, and power status."""

    thermal: McuThermalInfo = Field(default_factory=McuThermalInfo)
    fan: McuFanInfo = Field(default_factory=McuFanInfo)
    voltages: McuVoltageInfo = Field(default_factory=McuVoltageInfo)
    power: McuPowerInfo = Field(default_factory=McuPowerInfo)


class McuPortInfo(BaseModel):
    """Single port information from MCU."""

    station: int = 0
    connector: str = ""
    port_number: int = 0
    negotiated_speed: str = ""
    negotiated_width: int = 0
    max_speed: str = ""
    max_width: int = 0
    status: str = ""
    port_type: str = ""


class McuPortStatus(BaseModel):
    """Full port status from MCU."""

    chip_version: str = ""
    upstream_ports: list[McuPortInfo] = Field(default_factory=list)
    ext_mcio_ports: list[McuPortInfo] = Field(default_factory=list)
    int_mcio_ports: list[McuPortInfo] = Field(default_factory=list)
    straddle_ports: list[McuPortInfo] = Field(default_factory=list)

    @property
    def all_ports(self) -> list[McuPortInfo]:
        return (
            self.upstream_ports
            + self.ext_mcio_ports
            + self.int_mcio_ports
            + self.straddle_ports
        )


class McuErrorCounters(BaseModel):
    """Error counters for a single port."""

    port_number: int = 0
    port_rx: int = 0
    bad_tlp: int = 0
    bad_dllp: int = 0
    rec_diag: int = 0
    link_down: int = 0
    flit_error: int = 0

    @property
    def total_errors(self) -> int:
        return (
            self.port_rx
            + self.bad_tlp
            + self.bad_dllp
            + self.rec_diag
            + self.link_down
            + self.flit_error
        )


class McuErrorSnapshot(BaseModel):
    """Error counters across all ports."""

    counters: list[McuErrorCounters] = Field(default_factory=list)


class McuClockStatus(BaseModel):
    """Clock output status."""

    straddle_enabled: bool = False
    ext_mcio_enabled: bool = False
    int_mcio_enabled: bool = False


class McuSpreadStatus(BaseModel):
    """Spread spectrum status."""

    enabled: bool = False
    mode: str = ""


class McuFlitStatus(BaseModel):
    """FLIT mode status per station."""

    station2: bool = False
    station5: bool = False
    station7: bool = False
    station8: bool = False


class McuBistDevice(BaseModel):
    """Single device BIST result."""

    device_id: str = ""
    status: str = ""


class McuBistResult(BaseModel):
    """BIST results for all devices."""

    devices: list[McuBistDevice] = Field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(d.status.upper() == "PASS" for d in self.devices)


class McuDeviceInfo(BaseModel):
    """Combined MCU device information."""

    version: McuVersionInfo = Field(default_factory=McuVersionInfo)
    thermal_status: McuThermalStatus = Field(default_factory=McuThermalStatus)
    port_status: McuPortStatus = Field(default_factory=McuPortStatus)
    connected: bool = False
    port: str = ""
