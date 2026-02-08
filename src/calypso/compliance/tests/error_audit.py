"""T2.x Error Audit compliance tests.

Verifies AER error status, error reporting enables, and error-free operation.
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
from calypso.core.pcie_config import PcieConfigReader
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

SUITE = TestSuiteId.ERROR_AUDIT


def run_error_audit_tests(
    device: PLX_DEVICE_OBJECT,
    device_key: PLX_DEVICE_KEY,
    port: PortConfig,
    config: TestRunConfig,
) -> list[TestResult]:
    """Execute all error audit tests."""
    reader = PcieConfigReader(device, device_key)
    results: list[TestResult] = []

    results.extend(_t2_1_aer_error_audit(reader, port))
    results.extend(_t2_2_error_reporting_enables(reader, port))
    results.extend(_t2_3_error_free_operation(reader, port, config))

    return results


def _t2_1_aer_error_audit(
    reader: PcieConfigReader,
    port: PortConfig,
) -> list[TestResult]:
    """T2.1: Check that no AER errors are currently active."""
    t_start = time.monotonic()

    try:
        aer = reader.get_aer_status()
        if aer is None:
            return [TestResult(
                test_id="T2.1",
                test_name="AER Error Audit",
                suite_id=SUITE,
                verdict=Verdict.SKIP,
                spec_reference="PCIe 6.0.1 Section 7.8.4",
                message="AER capability not present",
                duration_ms=_elapsed(t_start),
                port_number=port.port_number,
            )]

        uncorr_active = aer.uncorrectable.raw_value != 0
        corr_active = aer.correctable.raw_value != 0

        if not uncorr_active and not corr_active:
            verdict = Verdict.PASS
            msg = "No AER errors active"
        elif uncorr_active:
            verdict = Verdict.FAIL
            msg = f"Uncorrectable errors active: 0x{aer.uncorrectable.raw_value:08X}"
        else:
            verdict = Verdict.WARN
            msg = f"Correctable errors active: 0x{aer.correctable.raw_value:08X}"

        return [TestResult(
            test_id="T2.1",
            test_name="AER Error Audit",
            suite_id=SUITE,
            verdict=verdict,
            spec_reference="PCIe 6.0.1 Section 7.8.4",
            criteria="No uncorrectable or correctable errors active",
            message=msg,
            measured_values={
                "uncorrectable_raw": f"0x{aer.uncorrectable.raw_value:08X}",
                "correctable_raw": f"0x{aer.correctable.raw_value:08X}",
                "first_error_pointer": aer.first_error_pointer,
            },
            duration_ms=_elapsed(t_start),
            port_number=port.port_number,
        )]
    except Exception as exc:
        return [TestResult(
            test_id="T2.1",
            test_name="AER Error Audit",
            suite_id=SUITE,
            verdict=Verdict.ERROR,
            spec_reference="PCIe 6.0.1 Section 7.8.4",
            message=str(exc),
            duration_ms=_elapsed(t_start),
            port_number=port.port_number,
        )]


def _t2_2_error_reporting_enables(
    reader: PcieConfigReader,
    port: PortConfig,
) -> list[TestResult]:
    """T2.2: Verify error reporting bits are enabled in Device Control."""
    t_start = time.monotonic()

    try:
        ctrl = reader.get_device_control()

        enabled = []
        disabled = []
        for field_name, label in [
            ("correctable_error_reporting", "Correctable"),
            ("non_fatal_error_reporting", "Non-Fatal"),
            ("fatal_error_reporting", "Fatal"),
        ]:
            if getattr(ctrl, field_name):
                enabled.append(label)
            else:
                disabled.append(label)

        if not disabled:
            verdict = Verdict.PASS
            msg = "All error reporting enables active"
        else:
            verdict = Verdict.WARN
            msg = f"Disabled: {', '.join(disabled)}"

        return [TestResult(
            test_id="T2.2",
            test_name="Error Reporting Enables",
            suite_id=SUITE,
            verdict=verdict,
            spec_reference="PCIe 6.0.1 Section 7.5.1.1",
            criteria="Correctable, Non-Fatal, and Fatal error reporting should be enabled",
            message=msg,
            measured_values={
                "correctable": ctrl.correctable_error_reporting,
                "non_fatal": ctrl.non_fatal_error_reporting,
                "fatal": ctrl.fatal_error_reporting,
            },
            duration_ms=_elapsed(t_start),
            port_number=port.port_number,
        )]
    except Exception as exc:
        return [TestResult(
            test_id="T2.2",
            test_name="Error Reporting Enables",
            suite_id=SUITE,
            verdict=Verdict.ERROR,
            spec_reference="PCIe 6.0.1 Section 7.5.1.1",
            message=str(exc),
            duration_ms=_elapsed(t_start),
            port_number=port.port_number,
        )]


def _t2_3_error_free_operation(
    reader: PcieConfigReader,
    port: PortConfig,
    config: TestRunConfig,
) -> list[TestResult]:
    """T2.3: Clear AER, wait, re-read to verify no new errors appear."""
    t_start = time.monotonic()

    try:
        aer_before = reader.get_aer_status()
        if aer_before is None:
            return [TestResult(
                test_id="T2.3",
                test_name="Error-Free Operation",
                suite_id=SUITE,
                verdict=Verdict.SKIP,
                spec_reference="PCIe 6.0.1 Section 6.2",
                message="AER capability not present",
                duration_ms=_elapsed(t_start),
                port_number=port.port_number,
            )]

        reader.clear_aer_errors()
        time.sleep(config.idle_wait_s)
        aer_after = reader.get_aer_status()

        new_uncorr = aer_after.uncorrectable.raw_value if aer_after else 0
        new_corr = aer_after.correctable.raw_value if aer_after else 0

        if new_uncorr == 0 and new_corr == 0:
            verdict = Verdict.PASS
            msg = f"No new errors during {config.idle_wait_s}s idle period"
        elif new_uncorr != 0:
            verdict = Verdict.FAIL
            msg = f"New uncorrectable errors: 0x{new_uncorr:08X}"
        else:
            verdict = Verdict.WARN
            msg = f"New correctable errors: 0x{new_corr:08X}"

        return [TestResult(
            test_id="T2.3",
            test_name="Error-Free Operation",
            suite_id=SUITE,
            verdict=verdict,
            spec_reference="PCIe 6.0.1 Section 6.2",
            criteria="No new errors during idle period",
            message=msg,
            measured_values={
                "new_uncorrectable": f"0x{new_uncorr:08X}",
                "new_correctable": f"0x{new_corr:08X}",
                "idle_wait_s": config.idle_wait_s,
            },
            duration_ms=_elapsed(t_start),
            port_number=port.port_number,
        )]
    except Exception as exc:
        return [TestResult(
            test_id="T2.3",
            test_name="Error-Free Operation",
            suite_id=SUITE,
            verdict=Verdict.ERROR,
            spec_reference="PCIe 6.0.1 Section 6.2",
            message=str(exc),
            duration_ms=_elapsed(t_start),
            port_number=port.port_number,
        )]


def _elapsed(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 2)
