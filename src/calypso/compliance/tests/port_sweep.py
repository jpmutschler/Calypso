"""T6.x Port Sweep compliance tests.

All-port link status, error sweep, and recovery count audit.
"""

from __future__ import annotations

import time

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.compliance.models import (
    PortConfig,
    TestResult,
    TestRunConfig,
    TestSuiteId,
    Verdict,
)
from calypso.core.error_aggregator import ErrorAggregator
from calypso.core.ltssm_trace import LtssmTracer
from calypso.core.port_manager import PortManager
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

SUITE = TestSuiteId.PORT_SWEEP


def run_port_sweep_tests(
    device: PLX_DEVICE_OBJECT,
    device_key: PLX_DEVICE_KEY,
    port: PortConfig,
    config: TestRunConfig,
) -> list[TestResult]:
    """Execute all-port sweep tests."""
    results: list[TestResult] = []

    results.extend(_t6_1_all_port_link_status(device, device_key))
    results.extend(_t6_2_all_port_error_sweep(device, device_key))
    results.extend(_t6_3_all_port_recovery_count(device, device_key))

    return results


def _t6_1_all_port_link_status(
    device: PLX_DEVICE_OBJECT,
    device_key: PLX_DEVICE_KEY,
) -> list[TestResult]:
    """T6.1: Enumerate all ports and report link state per port."""
    t_start = time.monotonic()

    try:
        pm = PortManager(device, device_key)
        statuses = pm.get_all_port_statuses()

        up_count = sum(1 for s in statuses if s.is_link_up)
        down_count = len(statuses) - up_count

        port_details: list[dict[str, object]] = []
        for s in statuses:
            port_details.append({
                "port": s.port_number,
                "link_up": s.is_link_up,
                "speed": str(s.link_speed),
                "width": s.link_width,
                "role": str(s.role),
            })

        verdict = Verdict.PASS if up_count > 0 else Verdict.WARN
        msg = f"{len(statuses)} ports found: {up_count} up, {down_count} down"

        return [TestResult(
            test_id="T6.1",
            test_name="All-Port Link Status",
            suite_id=SUITE,
            verdict=verdict,
            spec_reference="PCIe 6.0.1 Section 7.5.3.6",
            criteria="Port enumeration completes, at least one link up",
            message=msg,
            measured_values={
                "total_ports": len(statuses),
                "up_count": up_count,
                "down_count": down_count,
                "ports": port_details,
            },
            duration_ms=_elapsed(t_start),
        )]
    except Exception as exc:
        return [TestResult(
            test_id="T6.1",
            test_name="All-Port Link Status",
            suite_id=SUITE,
            verdict=Verdict.ERROR,
            spec_reference="PCIe 6.0.1 Section 7.5.3.6",
            message=str(exc),
            duration_ms=_elapsed(t_start),
        )]


def _t6_2_all_port_error_sweep(
    device: PLX_DEVICE_OBJECT,
    device_key: PLX_DEVICE_KEY,
) -> list[TestResult]:
    """T6.2: Check AER + LTSSM errors across all active ports."""
    t_start = time.monotonic()

    try:
        pm = PortManager(device, device_key)
        statuses = pm.get_all_port_statuses()
        active_ports = [s.port_number for s in statuses if s.is_link_up]

        agg = ErrorAggregator(device, device_key)
        overview = agg.get_overview(active_ports=active_ports)

        total_errors = overview.total_aer_uncorrectable + overview.total_aer_correctable
        port_errors = [
            {
                "port": pe.port_number,
                "ltssm_recovery": pe.ltssm_recovery_count,
                "ltssm_link_down": pe.ltssm_link_down_count,
            }
            for pe in overview.port_errors
            if pe.ltssm_recovery_count > 0 or pe.ltssm_link_down_count > 0
        ]

        if total_errors == 0 and not port_errors:
            verdict = Verdict.PASS
            msg = f"No errors across {len(active_ports)} active ports"
        elif overview.total_aer_uncorrectable > 0:
            verdict = Verdict.FAIL
            msg = f"Uncorrectable AER errors found (raw: 0x{overview.aer_uncorrectable_raw:08X})"
        else:
            verdict = Verdict.WARN
            parts = []
            if overview.total_aer_correctable > 0:
                parts.append(f"{overview.total_aer_correctable} correctable AER")
            if port_errors:
                parts.append(f"{len(port_errors)} ports with LTSSM issues")
            msg = "; ".join(parts)

        return [TestResult(
            test_id="T6.2",
            test_name="All-Port Error Sweep",
            suite_id=SUITE,
            verdict=verdict,
            spec_reference="PCIe 6.0.1 Section 7.8.4",
            criteria="No uncorrectable errors across all ports",
            message=msg,
            measured_values={
                "active_ports": len(active_ports),
                "aer_uncorrectable": overview.total_aer_uncorrectable,
                "aer_correctable": overview.total_aer_correctable,
                "ports_with_issues": port_errors,
            },
            duration_ms=_elapsed(t_start),
        )]
    except Exception as exc:
        return [TestResult(
            test_id="T6.2",
            test_name="All-Port Error Sweep",
            suite_id=SUITE,
            verdict=Verdict.ERROR,
            spec_reference="PCIe 6.0.1 Section 7.8.4",
            message=str(exc),
            duration_ms=_elapsed(t_start),
        )]


def _t6_3_all_port_recovery_count(
    device: PLX_DEVICE_OBJECT,
    device_key: PLX_DEVICE_KEY,
) -> list[TestResult]:
    """T6.3: Check recovery count on each active port, flag non-zero."""
    t_start = time.monotonic()

    try:
        pm = PortManager(device, device_key)
        statuses = pm.get_all_port_statuses()
        active_ports = [s.port_number for s in statuses if s.is_link_up]

        non_zero: list[dict[str, object]] = []
        total_checked = 0

        for port_num in active_ports:
            try:
                tracer = LtssmTracer(device, device_key, port_num)
                recovery, rx_eval = tracer.read_recovery_count(port_select=0)
                total_checked += 1
                if recovery > 0:
                    non_zero.append({
                        "port": port_num,
                        "recovery_count": recovery,
                        "rx_eval_count": rx_eval,
                    })
            except Exception:
                logger.debug("recovery_read_failed", port=port_num)

        if not non_zero:
            verdict = Verdict.PASS
            msg = f"All {total_checked} active ports have zero recovery count"
        else:
            verdict = Verdict.WARN
            ports_str = ", ".join(
                f"port {p['port']}={p['recovery_count']}" for p in non_zero[:5]
            )
            msg = f"{len(non_zero)}/{total_checked} ports with recoveries: {ports_str}"

        return [TestResult(
            test_id="T6.3",
            test_name="All-Port Recovery Count",
            suite_id=SUITE,
            verdict=verdict,
            spec_reference="PCIe 6.0.1 Section 4.2.6.3",
            criteria="Zero recovery count on all active ports",
            message=msg,
            measured_values={
                "total_checked": total_checked,
                "non_zero_count": len(non_zero),
                "non_zero_ports": non_zero,
            },
            duration_ms=_elapsed(t_start),
        )]
    except Exception as exc:
        return [TestResult(
            test_id="T6.3",
            test_name="All-Port Recovery Count",
            suite_id=SUITE,
            verdict=Verdict.ERROR,
            spec_reference="PCIe 6.0.1 Section 4.2.6.3",
            message=str(exc),
            duration_ms=_elapsed(t_start),
        )]


def _elapsed(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 2)
