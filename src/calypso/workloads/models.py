"""Pydantic models for NVMe workload generation."""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field, field_validator

_BDF_RE = re.compile(r"^[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]$")
_CORE_MASK_RE = re.compile(r"^0[xX][0-9a-fA-F]+$")


class WorkloadType(str, Enum):
    """NVMe I/O workload pattern."""
    RANDREAD = "randread"
    RANDWRITE = "randwrite"
    READ = "read"
    WRITE = "write"
    RANDRW = "randrw"
    RW = "rw"


class BackendType(str, Enum):
    """Workload generation backend."""
    SPDK = "spdk"
    PYNVME = "pynvme"


class WorkloadState(str, Enum):
    """Lifecycle state of a workload."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class WorkloadConfig(BaseModel):
    """Configuration for a workload run."""
    backend: BackendType
    target_bdf: str = Field(description="PCIe BDF address, e.g. 0000:01:00.0")
    workload_type: WorkloadType = WorkloadType.RANDREAD
    io_size_bytes: int = Field(default=4096, gt=0)
    queue_depth: int = Field(default=128, gt=0)
    duration_seconds: int = Field(default=30, gt=0)
    read_percentage: int = Field(default=100, ge=0, le=100)
    core_mask: str | None = Field(default=None, description="CPU core mask for SPDK, e.g. 0xFF")
    num_workers: int = Field(default=1, gt=0)
    lba_random: bool = True
    region_start: int | None = None
    region_end: int | None = None

    @field_validator("target_bdf")
    @classmethod
    def validate_bdf(cls, v: str) -> str:
        if not _BDF_RE.fullmatch(v):
            raise ValueError(f"Invalid PCIe BDF address: {v!r} (expected format: 0000:01:00.0)")
        return v

    @field_validator("core_mask")
    @classmethod
    def validate_core_mask(cls, v: str | None) -> str | None:
        if v is not None and not _CORE_MASK_RE.fullmatch(v):
            raise ValueError(f"Invalid core mask: {v!r} (expected hex format: 0xFF)")
        return v


class WorkloadIOStats(BaseModel):
    """Aggregated I/O statistics from a workload run."""
    io_count_read: int = 0
    io_count_write: int = 0
    iops_read: float = 0.0
    iops_write: float = 0.0
    iops_total: float = 0.0
    bandwidth_read_mbps: float = 0.0
    bandwidth_write_mbps: float = 0.0
    bandwidth_total_mbps: float = 0.0
    latency_avg_us: float = 0.0
    latency_max_us: float = 0.0
    latency_p50_us: float = 0.0
    latency_p99_us: float = 0.0
    latency_p999_us: float = 0.0
    cpu_usage_percent: float = 0.0


class WorkloadProgress(BaseModel):
    """Live progress snapshot of a running workload."""
    workload_id: str
    elapsed_seconds: float = 0.0
    total_seconds: float = 0.0
    current_iops: float = 0.0
    current_bandwidth_mbps: float = 0.0
    state: WorkloadState = WorkloadState.RUNNING


class WorkloadResult(BaseModel):
    """Final result of a completed workload run."""
    workload_id: str
    config: WorkloadConfig
    stats: WorkloadIOStats | None = None
    duration_ms: float = 0.0
    error: str | None = None
    state: WorkloadState = WorkloadState.COMPLETED


class WorkloadStatus(BaseModel):
    """Full lifecycle status of a workload."""
    workload_id: str
    backend: BackendType
    target_bdf: str
    state: WorkloadState
    config: WorkloadConfig
    result: WorkloadResult | None = None
    progress: WorkloadProgress | None = None


class CombinedPerfView(BaseModel):
    """Host-side workload stats combined with switch-side performance snapshot."""
    workload_id: str
    workload_stats: WorkloadIOStats | None = None
    workload_state: WorkloadState = WorkloadState.PENDING
    switch_snapshot: dict | None = Field(
        default=None,
        description="PerfSnapshot dict from switch-side monitoring",
    )
