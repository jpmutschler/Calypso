"""Parser for SPDK spdk_nvme_perf text output."""

from __future__ import annotations

import re

from calypso.workloads.models import WorkloadIOStats


# Regex patterns for spdk_nvme_perf output lines
_TOTAL_LINE_RE = re.compile(
    r"Total\s*:\s*"
    r"(?P<iops>[\d.]+)\s*IOPS\s+"
    r"(?P<bw>[\d.]+)\s*MiB/s",
)
_LATENCY_AVG_RE = re.compile(
    r"Average\s+Latency\s*:\s*(?P<val>[\d.]+)\s*us",
    re.IGNORECASE,
)
_LATENCY_MAX_RE = re.compile(
    r"(?:Max|Maximum)\s+Latency\s*:\s*(?P<val>[\d.]+)\s*us",
    re.IGNORECASE,
)
_LATENCY_P50_RE = re.compile(
    r"50(?:\.0+)?(?:th)?\s*(?:percentile|pctile|%ile)\s*.*?:\s*(?P<val>[\d.]+)\s*us",
    re.IGNORECASE,
)
_LATENCY_P99_RE = re.compile(
    r"99(?:\.0+)?(?:th)?\s*(?:percentile|pctile|%ile)\s*.*?:\s*(?P<val>[\d.]+)\s*us",
    re.IGNORECASE,
)
_LATENCY_P999_RE = re.compile(
    r"99\.9(?:0+)?(?:th)?\s*(?:percentile|pctile|%ile)\s*.*?:\s*(?P<val>[\d.]+)\s*us",
    re.IGNORECASE,
)
_READ_IOPS_RE = re.compile(
    r"Read\s*:\s*(?P<iops>[\d.]+)\s*IOPS\s+(?P<bw>[\d.]+)\s*MiB/s",
    re.IGNORECASE,
)
_WRITE_IOPS_RE = re.compile(
    r"Write\s*:\s*(?P<iops>[\d.]+)\s*IOPS\s+(?P<bw>[\d.]+)\s*MiB/s",
    re.IGNORECASE,
)
_CPU_RE = re.compile(
    r"CPU\s+Usage\s*:\s*(?P<val>[\d.]+)\s*%",
    re.IGNORECASE,
)


def parse_spdk_output(text: str) -> WorkloadIOStats:
    """Parse spdk_nvme_perf stdout into a WorkloadIOStats model.

    Handles multiple output format variations across SPDK versions.
    """
    iops_total = 0.0
    bw_total_mbps = 0.0
    iops_read = 0.0
    iops_write = 0.0
    bw_read_mbps = 0.0
    bw_write_mbps = 0.0
    latency_avg = 0.0
    latency_max = 0.0
    latency_p50 = 0.0
    latency_p99 = 0.0
    latency_p999 = 0.0
    cpu_usage = 0.0

    for line in text.splitlines():
        m = _TOTAL_LINE_RE.search(line)
        if m:
            iops_total = float(m.group("iops"))
            bw_total_mbps = float(m.group("bw"))
            continue

        m = _READ_IOPS_RE.search(line)
        if m:
            iops_read = float(m.group("iops"))
            bw_read_mbps = float(m.group("bw"))
            continue

        m = _WRITE_IOPS_RE.search(line)
        if m:
            iops_write = float(m.group("iops"))
            bw_write_mbps = float(m.group("bw"))
            continue

        m = _LATENCY_AVG_RE.search(line)
        if m:
            latency_avg = float(m.group("val"))
            continue

        m = _LATENCY_MAX_RE.search(line)
        if m:
            latency_max = float(m.group("val"))
            continue

        m = _LATENCY_P50_RE.search(line)
        if m:
            latency_p50 = float(m.group("val"))
            continue

        # p999 must be checked before p99 (more specific match first)
        m = _LATENCY_P999_RE.search(line)
        if m:
            latency_p999 = float(m.group("val"))
            continue

        m = _LATENCY_P99_RE.search(line)
        if m:
            latency_p99 = float(m.group("val"))
            continue

        m = _CPU_RE.search(line)
        if m:
            cpu_usage = float(m.group("val"))
            continue

    # When only a Total line is present (no separate Read/Write), leave
    # per-direction fields at zero -- the caller knows the workload type and
    # can attribute correctly if needed.

    return WorkloadIOStats(
        iops_read=iops_read,
        iops_write=iops_write,
        iops_total=iops_total if iops_total > 0 else iops_read + iops_write,
        bandwidth_read_mbps=bw_read_mbps,
        bandwidth_write_mbps=bw_write_mbps,
        bandwidth_total_mbps=(
            bw_total_mbps if bw_total_mbps > 0 else bw_read_mbps + bw_write_mbps
        ),
        latency_avg_us=latency_avg,
        latency_max_us=latency_max,
        latency_p50_us=latency_p50,
        latency_p99_us=latency_p99,
        latency_p999_us=latency_p999,
        cpu_usage_percent=cpu_usage,
    )
