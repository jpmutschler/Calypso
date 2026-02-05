"""Real-time performance monitoring for switch ports."""

from __future__ import annotations

import time
from ctypes import byref

from calypso.bindings.constants import PEX_MAX_PORT
from calypso.bindings.types import PLX_DEVICE_OBJECT, PLX_PERF_PROP, PLX_PERF_STATS
from calypso.models.performance import PerfCounters, PerfSnapshot, PerfStats
from calypso.sdk import performance as sdk_perf
from calypso.utils.logging import get_logger

logger = get_logger(__name__)


class PerfMonitor:
    """Manages performance counter monitoring for a switch device."""

    def __init__(self, device: PLX_DEVICE_OBJECT) -> None:
        self._device = device
        self._perf_props: list[PLX_PERF_PROP] = []
        self._num_ports: int = 0
        self._is_running: bool = False
        self._last_read_time_ms: int = 0

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def num_ports(self) -> int:
        return self._num_ports

    def initialize(self) -> int:
        """Initialize performance properties for all ports.

        Returns:
            Number of valid port entries found.
        """
        perf_array = (PLX_PERF_PROP * PEX_MAX_PORT)()
        sdk_perf.init_properties(self._device, perf_array[0])

        valid_ports: list[PLX_PERF_PROP] = []
        for i in range(PEX_MAX_PORT):
            if perf_array[i].IsValidTag != 0:
                valid_ports.append(perf_array[i])

        self._perf_props = valid_ports
        self._num_ports = len(valid_ports)
        logger.info("perf_initialized", port_count=self._num_ports)
        return self._num_ports

    def start(self) -> None:
        """Start performance counter collection."""
        if self._is_running:
            return
        if not self._perf_props:
            self.initialize()
        sdk_perf.start_monitoring(self._device)
        self._is_running = True
        self._last_read_time_ms = int(time.monotonic() * 1000)

    def stop(self) -> None:
        """Stop performance counter collection."""
        if not self._is_running:
            return
        sdk_perf.stop_monitoring(self._device)
        self._is_running = False

    def read_snapshot(self) -> PerfSnapshot:
        """Read current counters and calculate statistics.

        Returns:
            PerfSnapshot with stats for all monitored ports.
        """
        now_ms = int(time.monotonic() * 1000)
        elapsed_ms = now_ms - self._last_read_time_ms if self._last_read_time_ms else 1000
        self._last_read_time_ms = now_ms

        if not self._perf_props:
            return PerfSnapshot(timestamp_ms=now_ms, elapsed_ms=elapsed_ms)

        perf_array = (PLX_PERF_PROP * len(self._perf_props))(*self._perf_props)
        sdk_perf.get_counters(self._device, perf_array[0], len(self._perf_props))

        port_stats: list[PerfStats] = []
        for i in range(len(self._perf_props)):
            prop = perf_array[i]
            stats = sdk_perf.calc_statistics(prop, elapsed_ms)

            port_stats.append(PerfStats(
                port_number=prop.PortNumber,
                ingress_total_bytes=stats.IngressTotalBytes,
                ingress_total_byte_rate=float(stats.IngressTotalByteRate),
                ingress_payload_read_bytes=stats.IngressPayloadReadBytes,
                ingress_payload_write_bytes=stats.IngressPayloadWriteBytes,
                ingress_payload_total_bytes=stats.IngressPayloadTotalBytes,
                ingress_payload_avg_per_tlp=float(stats.IngressPayloadAvgPerTlp),
                ingress_payload_byte_rate=float(stats.IngressPayloadByteRate),
                ingress_link_utilization=float(stats.IngressLinkUtilization),
                egress_total_bytes=stats.EgressTotalBytes,
                egress_total_byte_rate=float(stats.EgressTotalByteRate),
                egress_payload_read_bytes=stats.EgressPayloadReadBytes,
                egress_payload_write_bytes=stats.EgressPayloadWriteBytes,
                egress_payload_total_bytes=stats.EgressPayloadTotalBytes,
                egress_payload_avg_per_tlp=float(stats.EgressPayloadAvgPerTlp),
                egress_payload_byte_rate=float(stats.EgressPayloadByteRate),
                egress_link_utilization=float(stats.EgressLinkUtilization),
            ))

        self._perf_props = list(perf_array)
        return PerfSnapshot(
            timestamp_ms=now_ms,
            elapsed_ms=elapsed_ms,
            port_stats=port_stats,
        )

    def reset(self) -> None:
        """Reset all performance counters."""
        if self._perf_props:
            perf_array = (PLX_PERF_PROP * len(self._perf_props))(*self._perf_props)
            sdk_perf.reset_counters(self._device, perf_array[0], len(self._perf_props))
            self._last_read_time_ms = int(time.monotonic() * 1000)
