"""Compliance test runner engine.

Orchestrates test execution, tracks progress via module-level state,
and aggregates results into a TestRun.  Follows the same threading
pattern used by lane_margining.py and ltssm_trace.py.
"""

from __future__ import annotations

import threading
import time
import uuid

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.compliance.models import (
    DeviceMetadata,
    PortConfig,
    SUITE_DISPLAY_NAMES,
    TestResult,
    TestRun,
    TestRunConfig,
    TestRunProgress,
    TestSuiteId,
    TestSuiteResult,
    Verdict,
)
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

# Module-level state, keyed by device_id
_lock = threading.Lock()
_active_runs: dict[str, TestRunProgress] = {}
_completed_runs: dict[str, TestRun] = {}
_cancel_flags: dict[str, bool] = {}


def get_run_progress(device_id: str) -> TestRunProgress:
    """Get the current compliance run progress."""
    with _lock:
        return _active_runs.get(device_id, TestRunProgress())


def get_run_result(device_id: str) -> TestRun | None:
    """Get the completed compliance run result."""
    with _lock:
        return _completed_runs.get(device_id)


def cancel_run(device_id: str) -> None:
    """Request cancellation of a running compliance test."""
    with _lock:
        _cancel_flags[device_id] = True


def _is_cancelled(device_id: str) -> bool:
    with _lock:
        return _cancel_flags.get(device_id, False)


# Mapping from suite ID to the test runner function
def _get_suite_runner(suite_id: TestSuiteId):
    """Lazily import and return the runner function for a suite."""
    if suite_id == TestSuiteId.LINK_TRAINING:
        from calypso.compliance.tests.link_training import run_link_training_tests
        return run_link_training_tests
    elif suite_id == TestSuiteId.ERROR_AUDIT:
        from calypso.compliance.tests.error_audit import run_error_audit_tests
        return run_error_audit_tests
    elif suite_id == TestSuiteId.CONFIG_AUDIT:
        from calypso.compliance.tests.config_audit import run_config_audit_tests
        return run_config_audit_tests
    elif suite_id == TestSuiteId.SIGNAL_INTEGRITY:
        from calypso.compliance.tests.signal_integrity import run_signal_integrity_tests
        return run_signal_integrity_tests
    elif suite_id == TestSuiteId.BER_TEST:
        from calypso.compliance.tests.ber_test import run_ber_tests
        return run_ber_tests
    elif suite_id == TestSuiteId.PORT_SWEEP:
        from calypso.compliance.tests.port_sweep import run_port_sweep_tests
        return run_port_sweep_tests
    return None


# Rough per-port test count estimate for each suite
_SUITE_TEST_ESTIMATES: dict[TestSuiteId, int] = {
    TestSuiteId.LINK_TRAINING: 8,
    TestSuiteId.ERROR_AUDIT: 3,
    TestSuiteId.CONFIG_AUDIT: 4,
    TestSuiteId.SIGNAL_INTEGRITY: 20,
    TestSuiteId.BER_TEST: 18,
    TestSuiteId.PORT_SWEEP: 3,
}


class ComplianceRunner:
    """Orchestrates a full compliance test run."""

    def __init__(
        self,
        device: PLX_DEVICE_OBJECT,
        device_key: PLX_DEVICE_KEY,
        device_id: str,
    ) -> None:
        self._device = device
        self._key = device_key
        self._device_id = device_id

    def run(self, config: TestRunConfig, metadata: DeviceMetadata) -> TestRun:
        """Execute the compliance test run.

        Thread-safe: updates _active_runs progress, stores result in
        _completed_runs, and honours _cancel_flags.
        """
        run_id = str(uuid.uuid4())[:8]
        device_id = self._device_id
        start_time = time.monotonic()

        # Estimate total tests
        total_estimate = 0
        for suite_id in config.suites:
            per_port = _SUITE_TEST_ESTIMATES.get(suite_id, 4)
            if suite_id == TestSuiteId.PORT_SWEEP:
                total_estimate += per_port  # Port sweep runs once, not per-port
            else:
                total_estimate += per_port * len(config.ports)

        with _lock:
            _cancel_flags[device_id] = False
            _active_runs[device_id] = TestRunProgress(
                status="running",
                tests_total=total_estimate,
            )

        suite_results: list[TestSuiteResult] = []
        all_tests: list[TestResult] = []
        eye_data: dict[str, object] = {}
        ber_data: dict[str, object] = {}
        tests_completed = 0

        try:
            for suite_id in config.suites:
                if _is_cancelled(device_id):
                    break

                suite_name = SUITE_DISPLAY_NAMES.get(suite_id, suite_id.value)
                suite_tests: list[TestResult] = []

                with _lock:
                    _active_runs[device_id] = TestRunProgress(
                        status="running",
                        current_suite=suite_name,
                        current_test="",
                        tests_completed=tests_completed,
                        tests_total=total_estimate,
                        percent=_pct(tests_completed, total_estimate),
                        elapsed_ms=_elapsed(start_time),
                    )

                runner = _get_suite_runner(suite_id)
                if runner is None:
                    continue

                # Port sweep runs once (not per-port)
                if suite_id == TestSuiteId.PORT_SWEEP:
                    ports_to_run = [config.ports[0]] if config.ports else [PortConfig()]
                else:
                    ports_to_run = config.ports

                for port in ports_to_run:
                    if _is_cancelled(device_id):
                        break

                    try:
                        # Signal integrity and BER return extra data
                        if suite_id == TestSuiteId.SIGNAL_INTEGRITY:
                            results, si_eye = runner(
                                self._device, self._key, device_id,
                                port, config,
                            )
                            eye_data.update(si_eye)
                        elif suite_id == TestSuiteId.BER_TEST:
                            results, ber_extra = runner(
                                self._device, self._key, device_id,
                                port, config,
                            )
                            ber_data.update(ber_extra)
                        elif suite_id == TestSuiteId.LINK_TRAINING:
                            results = runner(
                                self._device, self._key, device_id,
                                port, config,
                            )
                        elif suite_id == TestSuiteId.PORT_SWEEP:
                            results = runner(
                                self._device, self._key,
                                port, config,
                            )
                        else:
                            # error_audit, config_audit
                            results = runner(
                                self._device, self._key,
                                port, config,
                            )
                    except Exception as exc:
                        logger.error(
                            "suite_execution_failed",
                            suite=suite_id, port=port.port_number,
                            error=str(exc),
                        )
                        results = [TestResult(
                            test_id=f"{suite_id.value}",
                            test_name=f"{suite_name} (port {port.port_number})",
                            suite_id=suite_id,
                            verdict=Verdict.ERROR,
                            message=str(exc),
                            port_number=port.port_number,
                        )]

                    suite_tests.extend(results)
                    tests_completed += len(results)

                    with _lock:
                        _active_runs[device_id] = TestRunProgress(
                            status="running",
                            current_suite=suite_name,
                            current_test=results[-1].test_name if results else "",
                            tests_completed=tests_completed,
                            tests_total=max(total_estimate, tests_completed),
                            percent=_pct(tests_completed, max(total_estimate, tests_completed)),
                            elapsed_ms=_elapsed(start_time),
                        )

                suite_results.append(TestSuiteResult(
                    suite_id=suite_id,
                    suite_name=suite_name,
                    tests=suite_tests,
                ))
                all_tests.extend(suite_tests)

        except Exception as exc:
            logger.error("compliance_run_failed", error=str(exc))
            with _lock:
                _active_runs[device_id] = TestRunProgress(
                    status="error",
                    tests_completed=tests_completed,
                    tests_total=total_estimate,
                    elapsed_ms=_elapsed(start_time),
                    error=str(exc),
                )
            raise

        # Compute overall verdict
        if _is_cancelled(device_id):
            overall = Verdict.SKIP
        elif any(t.verdict == Verdict.FAIL for t in all_tests):
            overall = Verdict.FAIL
        elif any(t.verdict == Verdict.ERROR for t in all_tests):
            overall = Verdict.ERROR
        elif any(t.verdict == Verdict.WARN for t in all_tests):
            overall = Verdict.WARN
        else:
            overall = Verdict.PASS

        duration_ms = _elapsed(start_time)

        test_run = TestRun(
            run_id=run_id,
            config=config,
            device=metadata,
            suites=suite_results,
            overall_verdict=overall,
            total_pass=sum(1 for t in all_tests if t.verdict == Verdict.PASS),
            total_fail=sum(1 for t in all_tests if t.verdict == Verdict.FAIL),
            total_warn=sum(1 for t in all_tests if t.verdict == Verdict.WARN),
            total_skip=sum(1 for t in all_tests if t.verdict == Verdict.SKIP),
            total_error=sum(1 for t in all_tests if t.verdict == Verdict.ERROR),
            duration_ms=duration_ms,
            eye_data=eye_data,
            ber_data=ber_data,
        )

        status = "cancelled" if _is_cancelled(device_id) else "complete"

        with _lock:
            _completed_runs[device_id] = test_run
            _active_runs[device_id] = TestRunProgress(
                status=status,
                tests_completed=tests_completed,
                tests_total=tests_completed,
                percent=100.0,
                elapsed_ms=duration_ms,
            )
            _cancel_flags.pop(device_id, None)

        return test_run


def _pct(completed: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((completed / total) * 100, 1)


def _elapsed(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 2)
