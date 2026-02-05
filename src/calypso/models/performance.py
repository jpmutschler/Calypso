"""Performance counter and statistics models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PerfCounters(BaseModel):
    """Raw performance counter values for a single port."""
    model_config = {"frozen": False}

    port_number: int
    link_width: int = 0
    link_speed: int = 0
    station: int = 0
    station_port: int = 0

    # Ingress counters
    ingress_posted_header: int = 0
    ingress_posted_dw: int = 0
    ingress_nonposted_header: int = 0
    ingress_nonposted_dw: int = 0
    ingress_cpl_header: int = 0
    ingress_cpl_dw: int = 0
    ingress_dllp: int = 0

    # Egress counters
    egress_posted_header: int = 0
    egress_posted_dw: int = 0
    egress_nonposted_header: int = 0
    egress_nonposted_dw: int = 0
    egress_cpl_header: int = 0
    egress_cpl_dw: int = 0
    egress_dllp: int = 0


class PerfStats(BaseModel):
    """Calculated performance statistics for a single port."""
    model_config = {"frozen": False}

    port_number: int

    # Ingress statistics
    ingress_total_bytes: int = 0
    ingress_total_byte_rate: float = 0.0
    ingress_payload_read_bytes: int = 0
    ingress_payload_write_bytes: int = 0
    ingress_payload_total_bytes: int = 0
    ingress_payload_avg_per_tlp: float = 0.0
    ingress_payload_byte_rate: float = 0.0
    ingress_link_utilization: float = Field(default=0.0, description="0.0 to 1.0")

    # Egress statistics
    egress_total_bytes: int = 0
    egress_total_byte_rate: float = 0.0
    egress_payload_read_bytes: int = 0
    egress_payload_write_bytes: int = 0
    egress_payload_total_bytes: int = 0
    egress_payload_avg_per_tlp: float = 0.0
    egress_payload_byte_rate: float = 0.0
    egress_link_utilization: float = Field(default=0.0, description="0.0 to 1.0")

    @property
    def ingress_bandwidth_mbps(self) -> float:
        return self.ingress_payload_byte_rate / 1_000_000

    @property
    def egress_bandwidth_mbps(self) -> float:
        return self.egress_payload_byte_rate / 1_000_000


class PerfSnapshot(BaseModel):
    """A point-in-time snapshot of all port performance data."""
    model_config = {"frozen": False}

    timestamp_ms: int = 0
    elapsed_ms: int = 0
    port_stats: list[PerfStats] = Field(default_factory=list)
