"""Switch topology mapping models."""

from __future__ import annotations

from pydantic import BaseModel, Field

from calypso.models.port import PortRole, PortStatus


class TopologyPort(BaseModel):
    """A port in the topology with connection info."""
    model_config = {"frozen": False}

    port_number: int
    role: PortRole = PortRole.UNKNOWN
    status: PortStatus | None = None
    connected_to_device: str | None = Field(default=None, description="Connected device BDF")
    station: int = 0


class TopologyStation(BaseModel):
    """A station within the switch fabric."""
    model_config = {"frozen": False}

    station_index: int
    ports: list[TopologyPort] = Field(default_factory=list)
    connector_name: str | None = None
    label: str | None = None
    lane_range: tuple[int, int] | None = None


class TopologyMap(BaseModel):
    """Complete switch fabric topology."""
    model_config = {"frozen": False}

    chip_id: int = 0
    chip_family: str = "unknown"
    station_count: int = 0
    total_ports: int = 0
    stations: list[TopologyStation] = Field(default_factory=list)
    upstream_ports: list[int] = Field(default_factory=list)
    downstream_ports: list[int] = Field(default_factory=list)
