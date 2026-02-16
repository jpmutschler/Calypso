"""Pydantic models for MCU data, bridging serialcables-atlas3 dataclasses."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


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
    negotiated_speed: str | None = None
    negotiated_width: int | None = None
    max_speed: str | None = None
    max_width: int | None = None
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


# --- I2C Transfer Models ---


class I2cReadRequest(BaseModel):
    """Request parameters for an I2C read operation."""

    connector: int = Field(..., ge=0, le=5, description="Connector index (0-5)")
    channel: str = Field(..., pattern=r"^[ab]$", description="Channel identifier ('a' or 'b')")
    address: int = Field(..., ge=0x03, le=0x77, description="7-bit I2C slave address")
    reg_offset: int = Field(0, ge=0, le=0xFF, description="Register offset to read from")
    count: int = Field(1, ge=1, le=256, description="Number of bytes to read")


class I2cWriteRequest(BaseModel):
    """Request parameters for an I2C write operation."""

    connector: int = Field(..., ge=0, le=5, description="Connector index (0-5)")
    channel: str = Field(..., pattern=r"^[ab]$", description="Channel identifier ('a' or 'b')")
    address: int = Field(..., ge=0x03, le=0x77, description="7-bit I2C slave address")
    data: list[int] = Field(..., min_length=1, max_length=256, description="Bytes to write (0-255 each)")

    @field_validator("data")
    @classmethod
    def validate_byte_range(cls, v: list[int]) -> list[int]:
        for i, val in enumerate(v):
            if not 0 <= val <= 255:
                raise ValueError(f"data[{i}] = {val} is not a valid byte (0-255)")
        return v


class I2cReadResponse(BaseModel):
    """Response from an I2C read operation."""

    connector: int = 0
    channel: str = ""
    address: int = 0
    reg_offset: int = 0
    data: list[int] = Field(default_factory=list)

    @property
    def hex_dump(self) -> str:
        """Format data as hex dump string."""
        return " ".join(f"{b:02X}" for b in self.data)


class I2cScanResult(BaseModel):
    """Result of scanning an I2C bus for devices."""

    connector: int = 0
    channel: str = ""
    devices: list[int] = Field(default_factory=list, description="Addresses that responded")

    @property
    def device_count(self) -> int:
        return len(self.devices)

    @property
    def devices_hex(self) -> list[str]:
        return [f"0x{addr:02X}" for addr in self.devices]


# --- I3C Transfer Models ---


class I3cReadRequest(BaseModel):
    """Request parameters for an I3C read operation."""

    connector: int = Field(..., ge=0, le=5, description="Connector index (0-5)")
    channel: str = Field(..., pattern=r"^[ab]$", description="Channel identifier ('a' or 'b')")
    address: int = Field(..., ge=0x08, le=0x7E, description="I3C target address")
    reg_offset: int = Field(0, ge=0, le=0xFFFF, description="16-bit register offset")
    count: int = Field(1, ge=1, le=256, description="Number of bytes to read")


class I3cWriteRequest(BaseModel):
    """Request parameters for an I3C write operation."""

    connector: int = Field(..., ge=0, le=5, description="Connector index (0-5)")
    channel: str = Field(..., pattern=r"^[ab]$", description="Channel identifier ('a' or 'b')")
    address: int = Field(..., ge=0x08, le=0x7E, description="I3C target address")
    reg_offset: int = Field(0, ge=0, le=0xFFFF, description="16-bit register offset")
    data: list[int] = Field(..., min_length=1, max_length=256, description="Bytes to write (0-255 each)")

    @field_validator("data")
    @classmethod
    def validate_byte_range(cls, v: list[int]) -> list[int]:
        for i, val in enumerate(v):
            if not 0 <= val <= 255:
                raise ValueError(f"data[{i}] = {val} is not a valid byte (0-255)")
        return v


class I3cReadResponse(BaseModel):
    """Response from an I3C read operation."""

    connector: int = 0
    channel: str = ""
    address: int = 0
    reg_offset: int = 0
    data: list[int] = Field(default_factory=list)

    @property
    def hex_dump(self) -> str:
        return " ".join(f"{b:02X}" for b in self.data)


class I3cDevice(BaseModel):
    """An I3C device discovered via ENTDAA."""

    provisional_id: list[int] = Field(
        default_factory=lambda: [0] * 6,
        min_length=6,
        max_length=6,
        description="48-bit Provisioned ID (6 bytes)",
    )
    bcr: int = Field(0, description="Bus Characteristics Register")
    dcr: int = Field(0, description="Device Characteristics Register")
    dynamic_address: int = Field(0, description="Assigned dynamic address")

    @property
    def supports_mctp(self) -> bool:
        """BCR bit 5 indicates MCTP support."""
        return bool(self.bcr & 0x20)

    @property
    def pid_hex(self) -> str:
        return "".join(f"{b:02X}" for b in self.provisional_id)


class I3cEntdaaResult(BaseModel):
    """Result of I3C ENTDAA (dynamic address assignment)."""

    connector: int = 0
    channel: str = ""
    devices: list[I3cDevice] = Field(default_factory=list)

    @property
    def device_count(self) -> int:
        return len(self.devices)
