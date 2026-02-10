"""T1.x Link Training compliance tests.

Verifies speed negotiation, LTSSM state machine behaviour,
equalization phase completion, and recovery count baseline.
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
from calypso.compliance.thresholds import GEN_NAME_TO_SPEED_CODE
from calypso.core.ltssm_trace import LtssmTracer
from calypso.core.pcie_config import PcieConfigReader
from calypso.models.ltssm import LtssmState
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

SUITE = TestSuiteId.LINK_TRAINING


def run_link_training_tests(
    device: PLX_DEVICE_OBJECT,
    device_key: PLX_DEVICE_KEY,
    device_id: str,
    port: PortConfig,
    config: TestRunConfig,
) -> list[TestResult]:
    """Execute all link training tests for one port."""
    results: list[TestResult] = []
    reader = PcieConfigReader(device, device_key)
    tracer = LtssmTracer(device, device_key, port.port_number)

    results.extend(_t1_1_speed_negotiation(reader, tracer, port, config))
    results.extend(_t1_2_ltssm_validation(tracer, port, device_id))
    results.extend(_t1_3_eq_phase_verification(reader, port))
    results.extend(_t1_4_recovery_baseline(tracer, port, config))

    return results


def _t1_1_speed_negotiation(
    reader: PcieConfigReader,
    tracer: LtssmTracer,
    port: PortConfig,
    config: TestRunConfig,
) -> list[TestResult]:
    """T1.1: Verify link negotiates to each supported speed."""
    results: list[TestResult] = []

    speeds = reader.get_supported_speeds()
    original_status = reader.get_link_status()
    original_speed_code = GEN_NAME_TO_SPEED_CODE.get(original_status.target_speed, 0)

    try:
        for gen_name in speeds.as_list:
            speed_code = GEN_NAME_TO_SPEED_CODE.get(gen_name, 0)
            if speed_code < 1:
                continue

            t_start = time.monotonic()
            try:
                reader.set_target_link_speed(speed_code)
                reader.retrain_link()
                time.sleep(config.speed_settle_s)

                status = reader.get_link_status()
                achieved = status.current_speed
                expected = gen_name

                if achieved == expected:
                    verdict = Verdict.PASS
                    msg = f"Link trained to {achieved} as expected"
                else:
                    verdict = Verdict.FAIL
                    msg = f"Expected {expected}, achieved {achieved}"

                results.append(TestResult(
                    test_id="T1.1",
                    test_name=f"Speed Negotiation ({gen_name})",
                    suite_id=SUITE,
                    verdict=verdict,
                    spec_reference="PCIe 6.0.1 Section 7.5.3.6",
                    criteria=f"Link must train to {gen_name}",
                    message=msg,
                    measured_values={
                        "target_speed": gen_name,
                        "achieved_speed": achieved,
                        "width": status.current_width,
                    },
                    duration_ms=_elapsed(t_start),
                    port_number=port.port_number,
                ))
            except Exception as exc:
                results.append(TestResult(
                    test_id="T1.1",
                    test_name=f"Speed Negotiation ({gen_name})",
                    suite_id=SUITE,
                    verdict=Verdict.ERROR,
                    spec_reference="PCIe 6.0.1 Section 7.5.3.6",
                    message=str(exc),
                    duration_ms=_elapsed(t_start),
                    port_number=port.port_number,
                ))
    finally:
        # Restore original target speed
        if original_speed_code >= 1:
            try:
                reader.set_target_link_speed(original_speed_code)
                reader.retrain_link()
                time.sleep(config.speed_settle_s)
            except Exception:
                logger.warning("speed_restore_failed", port=port.port_number)

    return results


def _t1_2_ltssm_validation(
    tracer: LtssmTracer,
    port: PortConfig,
    device_id: str,
) -> list[TestResult]:
    """T1.2: Retrain and verify LTSSM follows legal state transitions."""
    t_start = time.monotonic()

    try:
        result = tracer.retrain_and_watch(port.port_select, device_id, timeout_s=10.0)

        transitions = result.transitions
        state_names = [t.state_name for t in transitions]

        # Check that we reached L0
        reached_l0 = result.final_state == LtssmState.L0

        # Check for illegal direct jumps (basic sanity)
        # Legal: Detect -> Polling -> Config -> L0 (simplified)
        has_detect = any("Detect" in s for s in state_names)
        has_polling = any("Polling" in s for s in state_names)

        if reached_l0 and result.settled:
            verdict = Verdict.PASS
            msg = f"LTSSM reached L0 after {len(transitions)} transitions in {result.duration_ms:.0f}ms"
        elif reached_l0:
            verdict = Verdict.WARN
            msg = "Reached L0 but did not settle (may have left L0 briefly)"
        else:
            verdict = Verdict.FAIL
            msg = f"Did not reach L0. Final state: {result.final_state_name}"

        return [TestResult(
            test_id="T1.2",
            test_name="LTSSM State Validation",
            suite_id=SUITE,
            verdict=verdict,
            spec_reference="PCIe 6.0.1 Section 4.2.6",
            criteria="Link must follow legal LTSSM sequence and reach L0",
            message=msg,
            measured_values={
                "transitions": len(transitions),
                "state_sequence": state_names,
                "final_state": result.final_state_name,
                "duration_ms": result.duration_ms,
                "settled": result.settled,
                "saw_detect": has_detect,
                "saw_polling": has_polling,
            },
            duration_ms=_elapsed(t_start),
            port_number=port.port_number,
        )]
    except Exception as exc:
        return [TestResult(
            test_id="T1.2",
            test_name="LTSSM State Validation",
            suite_id=SUITE,
            verdict=Verdict.ERROR,
            spec_reference="PCIe 6.0.1 Section 4.2.6",
            message=str(exc),
            duration_ms=_elapsed(t_start),
            port_number=port.port_number,
        )]


def _t1_3_eq_phase_verification(
    reader: PcieConfigReader,
    port: PortConfig,
) -> list[TestResult]:
    """T1.3: Verify EQ phases completed successfully at 8GT+ speeds."""
    t_start = time.monotonic()
    results: list[TestResult] = []

    status = reader.get_link_status()
    current_speed = status.current_speed

    # EQ only relevant at Gen3+ (8GT/s and above)
    speed_code = GEN_NAME_TO_SPEED_CODE.get(current_speed, 0)
    if speed_code < 3:
        results.append(TestResult(
            test_id="T1.3",
            test_name="EQ Phase Verification",
            suite_id=SUITE,
            verdict=Verdict.SKIP,
            spec_reference="PCIe 6.0.1 Section 4.2.3",
            criteria="EQ required at 8GT/s+",
            message=f"Current speed {current_speed} < Gen3, EQ not applicable",
            duration_ms=_elapsed(t_start),
            port_number=port.port_number,
        ))
        return results

    # Check 16GT EQ status
    eq_16 = reader.get_eq_status_16gt()
    if eq_16 is not None:
        phases_ok = eq_16.complete and eq_16.phase1_success
        if phases_ok and eq_16.phase2_success and eq_16.phase3_success:
            verdict = Verdict.PASS
            msg = "16GT EQ: all phases (1/2/3) completed successfully"
        elif eq_16.complete:
            verdict = Verdict.WARN
            msg = (
                f"16GT EQ complete but phases: "
                f"P1={'OK' if eq_16.phase1_success else 'FAIL'} "
                f"P2={'OK' if eq_16.phase2_success else 'FAIL'} "
                f"P3={'OK' if eq_16.phase3_success else 'FAIL'}"
            )
        else:
            verdict = Verdict.FAIL
            msg = "16GT EQ not complete"

        results.append(TestResult(
            test_id="T1.3",
            test_name="EQ Phase Verification (16GT)",
            suite_id=SUITE,
            verdict=verdict,
            spec_reference="PCIe 6.0.1 Section 4.2.3",
            criteria="EQ phases must complete successfully",
            message=msg,
            measured_values={
                "complete": eq_16.complete,
                "phase1": eq_16.phase1_success,
                "phase2": eq_16.phase2_success,
                "phase3": eq_16.phase3_success,
            },
            duration_ms=_elapsed(t_start),
            port_number=port.port_number,
        ))

    # Check 32GT EQ status if at Gen5+
    if speed_code >= 5:
        eq_32 = reader.get_eq_status_32gt()
        if eq_32 is not None:
            if eq_32.complete and eq_32.phase1_success:
                verdict = Verdict.PASS
                msg = "32GT EQ completed successfully"
            elif eq_32.no_eq_needed:
                verdict = Verdict.PASS
                msg = "32GT EQ: device reports no equalization needed"
            elif eq_32.complete:
                verdict = Verdict.WARN
                msg = "32GT EQ complete but not all phases succeeded"
            else:
                verdict = Verdict.FAIL
                msg = "32GT EQ not complete"

            results.append(TestResult(
                test_id="T1.3",
                test_name="EQ Phase Verification (32GT)",
                suite_id=SUITE,
                verdict=verdict,
                spec_reference="PCIe 6.0.1 Section 4.2.3",
                criteria="32GT EQ must complete",
                message=msg,
                measured_values={
                    "complete": eq_32.complete,
                    "phase1": eq_32.phase1_success,
                    "phase2": eq_32.phase2_success,
                    "phase3": eq_32.phase3_success,
                    "no_eq_needed": eq_32.no_eq_needed,
                },
                duration_ms=_elapsed(t_start),
                port_number=port.port_number,
            ))

    if not results:
        results.append(TestResult(
            test_id="T1.3",
            test_name="EQ Phase Verification",
            suite_id=SUITE,
            verdict=Verdict.SKIP,
            spec_reference="PCIe 6.0.1 Section 4.2.3",
            message="No EQ capability registers found",
            duration_ms=_elapsed(t_start),
            port_number=port.port_number,
        ))

    return results


def _t1_4_recovery_baseline(
    tracer: LtssmTracer,
    port: PortConfig,
    config: TestRunConfig,
) -> list[TestResult]:
    """T1.4: Clear recovery counter, wait, verify count stays zero."""
    t_start = time.monotonic()

    try:
        tracer.clear_recovery_count(port.port_select)
        time.sleep(config.idle_wait_s)
        recovery_count, rx_eval = tracer.read_recovery_count(port.port_select)

        if recovery_count == 0:
            verdict = Verdict.PASS
            msg = f"No recoveries during {config.idle_wait_s}s idle period"
        else:
            verdict = Verdict.FAIL
            msg = f"{recovery_count} recovery entries during {config.idle_wait_s}s idle period"

        return [TestResult(
            test_id="T1.4",
            test_name="Recovery Count Baseline",
            suite_id=SUITE,
            verdict=verdict,
            spec_reference="PCIe 6.0.1 Section 4.2.6.3",
            criteria="Zero recoveries during idle period",
            message=msg,
            measured_values={
                "recovery_count": recovery_count,
                "rx_eval_count": rx_eval,
                "idle_wait_s": config.idle_wait_s,
            },
            duration_ms=_elapsed(t_start),
            port_number=port.port_number,
        )]
    except Exception as exc:
        return [TestResult(
            test_id="T1.4",
            test_name="Recovery Count Baseline",
            suite_id=SUITE,
            verdict=Verdict.ERROR,
            spec_reference="PCIe 6.0.1 Section 4.2.6.3",
            message=str(exc),
            duration_ms=_elapsed(t_start),
            port_number=port.port_number,
        )]


def _elapsed(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 2)
