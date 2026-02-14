"""Pydantic models for NVMe-MI drive discovery and health data."""

from __future__ import annotations

from pydantic import BaseModel, Field


class NVMeHealthStatus(BaseModel):
    """NVMe drive health from Subsystem Health Status Poll."""

    composite_temperature_celsius: int = 0
    available_spare_percent: int = 100
    available_spare_threshold_percent: int = 10
    percentage_used: int = 0
    critical_warning: int = 0
    power_on_hours: int = 0

    @property
    def spare_below_threshold(self) -> bool:
        return bool(self.critical_warning & 0x01)

    @property
    def temperature_exceeded(self) -> bool:
        return bool(self.critical_warning & 0x02)

    @property
    def reliability_degraded(self) -> bool:
        return bool(self.critical_warning & 0x04)

    @property
    def read_only_mode(self) -> bool:
        return bool(self.critical_warning & 0x08)

    @property
    def volatile_backup_failed(self) -> bool:
        return bool(self.critical_warning & 0x10)

    @property
    def has_critical_warning(self) -> bool:
        return self.critical_warning != 0

    @property
    def drive_life_remaining_percent(self) -> int:
        return max(0, 100 - self.percentage_used)

    @property
    def temperature_status(self) -> str:
        if self.composite_temperature_celsius < 50:
            return "normal"
        if self.composite_temperature_celsius < 70:
            return "warm"
        return "critical"


class NVMeControllerHealth(BaseModel):
    """Per-controller health from Controller Health Status Poll."""

    controller_id: int = 0
    composite_temperature_celsius: int = 0
    available_spare_percent: int = 100
    percentage_used: int = 0
    critical_warning: int = 0


class NVMeSubsystemInfo(BaseModel):
    """NVMe subsystem identification from Read MI Data Structure."""

    nqn: str = ""
    number_of_ports: int = 0
    major_version: int = 0
    minor_version: int = 0


class NVMeDriveInfo(BaseModel):
    """Combined NVMe drive discovery and health info."""

    connector: int = 0
    channel: str = ""
    slave_addr: int = 0x6A
    eid: int = 0
    subsystem: NVMeSubsystemInfo = Field(default_factory=NVMeSubsystemInfo)
    health: NVMeHealthStatus = Field(default_factory=NVMeHealthStatus)
    reachable: bool = True

    @property
    def display_name(self) -> str:
        if self.subsystem.nqn:
            return self.subsystem.nqn.split(":")[-1][:32]
        return f"NVMe @ CN{self.connector}/{self.channel} (0x{self.slave_addr:02X})"


class NVMeDiscoveryResult(BaseModel):
    """Result of scanning all connectors for NVMe-MI endpoints."""

    drives: list[NVMeDriveInfo] = Field(default_factory=list)
    scan_errors: list[str] = Field(default_factory=list)

    @property
    def drive_count(self) -> int:
        return len(self.drives)

    @property
    def healthy_count(self) -> int:
        return sum(1 for d in self.drives if not d.health.has_critical_warning)
