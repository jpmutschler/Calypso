"""Switch configuration models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class VirtualSwitchConfig(BaseModel):
    """Configuration for a single virtual switch."""
    model_config = {"frozen": False}

    vs_index: int = Field(description="Virtual switch index (0-7)")
    enabled: bool = False
    upstream_port: int = Field(default=0, description="Upstream port number")
    downstream_port_mask: int = Field(default=0, description="Bitmask of downstream ports")


class MultiHostConfig(BaseModel):
    """Multi-host switch configuration."""
    model_config = {"frozen": False}

    switch_mode: int = 0
    vs_enabled_mask: int = 0
    virtual_switches: list[VirtualSwitchConfig] = Field(default_factory=list)
    is_management_port: bool = False
    mgmt_port_active_enabled: bool = False
    mgmt_port_active: int = 0
    mgmt_port_redundant_enabled: bool = False
    mgmt_port_redundant: int = 0


class NtLutEntry(BaseModel):
    """Non-Transparent LUT entry."""
    model_config = {"frozen": False}

    index: int
    req_id: int = 0
    flags: int = 0
    enabled: bool = False


class SwitchConfig(BaseModel):
    """Overall switch configuration."""
    model_config = {"frozen": False}

    chip_mode: str = "unknown"
    multi_host: MultiHostConfig | None = None
    nt_lut_entries: list[NtLutEntry] = Field(default_factory=list)
