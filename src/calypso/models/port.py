"""Port status and properties models."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class PortRole(StrEnum):
    """High-level port role classification."""
    UNKNOWN = "unknown"
    UPSTREAM = "upstream"
    DOWNSTREAM = "downstream"
    NT_VIRTUAL = "nt_virtual"
    NT_LINK = "nt_link"
    FABRIC = "fabric"
    HOST = "host"
    ENDPOINT = "endpoint"
    DMA = "dma"
    MANAGEMENT = "management"


class LinkSpeed(StrEnum):
    """PCIe link speed."""
    UNKNOWN = "unknown"
    GEN1_2_5G = "2.5_GT/s"
    GEN2_5G = "5.0_GT/s"
    GEN3_8G = "8.0_GT/s"
    GEN4_16G = "16.0_GT/s"
    GEN5_32G = "32.0_GT/s"
    GEN6_64G = "64.0_GT/s"


LINK_SPEED_VALUE_MAP: dict[int, LinkSpeed] = {
    0: LinkSpeed.UNKNOWN,
    1: LinkSpeed.GEN1_2_5G,
    2: LinkSpeed.GEN2_5G,
    3: LinkSpeed.GEN3_8G,
    4: LinkSpeed.GEN4_16G,
    5: LinkSpeed.GEN5_32G,
    6: LinkSpeed.GEN6_64G,
}


class PortProperties(BaseModel):
    """Static port properties from the switch."""
    model_config = {"frozen": False}

    port_number: int = Field(description="Internal port number")
    port_type: int = Field(default=0xFF, description="PCIe port type code")
    role: PortRole = Field(default=PortRole.UNKNOWN, description="High-level role")
    max_link_width: int = Field(default=0, description="Maximum supported link width")
    max_link_speed: LinkSpeed = Field(default=LinkSpeed.UNKNOWN)
    max_read_req_size: int = Field(default=0, description="Max read request size bytes")
    max_payload_supported: int = Field(default=0, description="Max payload size supported")
    is_pcie: bool = Field(default=True, description="Whether this is a PCIe device")


class PortStatus(BaseModel):
    """Current port link status."""
    model_config = {"frozen": False}

    port_number: int
    is_link_up: bool = False
    link_width: int = Field(default=0, description="Current negotiated link width")
    link_speed: LinkSpeed = Field(default=LinkSpeed.UNKNOWN, description="Current link speed")
    max_payload_size: int = Field(default=0, description="Current max payload size")
    role: PortRole = Field(default=PortRole.UNKNOWN)
    properties: PortProperties | None = None
