"""Device and chip information models."""

from __future__ import annotations

from enum import IntEnum, StrEnum

from pydantic import BaseModel, Field


class TransportMode(StrEnum):
    """Transport mode for device communication."""
    UART_MCU = "uart_mcu"
    SDB_USB = "sdb_usb"
    PCIE_BUS = "pcie_bus"


class DeviceInfo(BaseModel):
    """Information about a discovered PCIe switch device."""
    model_config = {"frozen": False}

    device_id: int = Field(description="PCI device ID")
    vendor_id: int = Field(description="PCI vendor ID")
    sub_vendor_id: int = Field(default=0, description="PCI subsystem vendor ID")
    sub_device_id: int = Field(default=0, description="PCI subsystem device ID")
    revision: int = Field(default=0, description="PCI revision")
    domain: int = Field(default=0, description="PCI domain")
    bus: int = Field(default=0, description="PCI bus number")
    slot: int = Field(default=0, description="PCI slot number")
    function: int = Field(default=0, description="PCI function number")
    chip_type: int = Field(default=0, description="PLX chip type identifier")
    chip_id: int = Field(default=0, description="Chip-reported ID")
    chip_revision: int = Field(default=0, description="PLX chip revision")
    chip_family: str = Field(default="unknown", description="PLX chip family name")
    port_number: int = Field(default=0, description="PLX port number")
    port_type: str = Field(default="unknown", description="PLX-specific port type")


class TransportInfo(BaseModel):
    """Transport connection details."""
    model_config = {"frozen": False}

    mode: TransportMode
    port_name: str = Field(default="", description="Serial port name or PCI address")
    baud_rate: int = Field(default=115200, description="Baud rate for serial transports")
    is_connected: bool = Field(default=False)


class DriverInfo(BaseModel):
    """PLX driver properties."""
    model_config = {"frozen": False}

    version_major: int = 0
    version_minor: int = 0
    version_revision: int = 0
    name: str = ""
    full_name: str = ""
    is_service_driver: bool = False


class VersionInfo(BaseModel):
    """SDK/firmware version information."""
    model_config = {"frozen": False}

    api_library: int = 0
    software: int = 0
    firmware: int = 0
    hardware: int = 0
    features: int = 0


class ChipFeatures(BaseModel):
    """Chip feature information."""
    model_config = {"frozen": False}

    station_count: int = 0
    ports_per_station: int = 0
    station_mask: int = 0
    port_mask: list[int] = Field(default_factory=list)
