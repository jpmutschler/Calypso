"""Performance monitoring wrapping PLX SDK perf functions."""

from __future__ import annotations

from ctypes import byref

from calypso.bindings.constants import PlxPerfCmd
from calypso.bindings.library import get_library
from calypso.bindings.types import PLX_DEVICE_OBJECT, PLX_PERF_PROP, PLX_PERF_STATS
from calypso.exceptions import check_status
from calypso.utils.logging import get_logger

logger = get_logger(__name__)


def init_properties(device: PLX_DEVICE_OBJECT, perf_props: PLX_PERF_PROP) -> None:
    """Initialize performance properties for monitoring.

    The SDK fills in port/station info for the perf_props array.
    """
    lib = get_library()
    status = lib.PlxPci_PerformanceInitializeProperties(byref(device), byref(perf_props))
    check_status(status, "PerformanceInitializeProperties")


def start_monitoring(device: PLX_DEVICE_OBJECT) -> None:
    """Start performance monitoring on the device."""
    lib = get_library()
    status = lib.PlxPci_PerformanceMonitorControl(byref(device), PlxPerfCmd.START.value)
    check_status(status, "PerformanceMonitorControl(START)")
    logger.info("perf_monitoring_started")


def stop_monitoring(device: PLX_DEVICE_OBJECT) -> None:
    """Stop performance monitoring on the device."""
    lib = get_library()
    status = lib.PlxPci_PerformanceMonitorControl(byref(device), PlxPerfCmd.STOP.value)
    check_status(status, "PerformanceMonitorControl(STOP)")
    logger.info("perf_monitoring_stopped")


def reset_counters(
    device: PLX_DEVICE_OBJECT, perf_props: PLX_PERF_PROP, num_objects: int
) -> None:
    """Reset all performance counters."""
    lib = get_library()
    status = lib.PlxPci_PerformanceResetCounters(byref(device), byref(perf_props), num_objects)
    check_status(status, "PerformanceResetCounters")


def get_counters(
    device: PLX_DEVICE_OBJECT, perf_props: PLX_PERF_PROP, num_objects: int
) -> None:
    """Read current performance counters into the perf_props array."""
    lib = get_library()
    status = lib.PlxPci_PerformanceGetCounters(byref(device), byref(perf_props), num_objects)
    check_status(status, "PerformanceGetCounters")


def calc_statistics(
    perf_prop: PLX_PERF_PROP, elapsed_ms: int
) -> PLX_PERF_STATS:
    """Calculate performance statistics from counter values.

    Args:
        perf_prop: Performance properties with current counter values.
        elapsed_ms: Time elapsed since last counter read in milliseconds.

    Returns:
        Calculated performance statistics.
    """
    lib = get_library()
    stats = PLX_PERF_STATS()
    status = lib.PlxPci_PerformanceCalcStatistics(byref(perf_prop), byref(stats), elapsed_ms)
    check_status(status, "PerformanceCalcStatistics")
    return stats
