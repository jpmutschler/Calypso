"""T4.x Signal Integrity compliance tests.

Eye width/height measurement via lane margining, spec minimum check,
and per-lane margin comparison. Supports NRZ (single eye) and PAM4 (3-eye).
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
from calypso.compliance.thresholds import (
    EYE_THRESHOLDS,
    GEN_NAME_TO_SPEED_CODE,
    LANE_MARGIN_OUTLIER_PERCENT,
)
from calypso.core.lane_margining import LaneMarginingEngine
from calypso.core.pcie_config import PcieConfigReader
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

SUITE = TestSuiteId.SIGNAL_INTEGRITY


def run_signal_integrity_tests(
    device: PLX_DEVICE_OBJECT,
    device_key: PLX_DEVICE_KEY,
    device_id: str,
    port: PortConfig,
    config: TestRunConfig,
) -> tuple[list[TestResult], dict[str, object]]:
    """Execute signal integrity tests. Returns (results, eye_data_for_report)."""
    results: list[TestResult] = []
    eye_data: dict[str, object] = {}

    reader = PcieConfigReader(device, device_key)
    link_status = reader.get_link_status()
    speed_code = GEN_NAME_TO_SPEED_CODE.get(link_status.current_speed, 0)

    # Lane margining requires Gen4+ (16GT/s)
    if speed_code < 4:
        results.append(
            TestResult(
                test_id="T4.1",
                test_name="Eye Measurement",
                suite_id=SUITE,
                verdict=Verdict.SKIP,
                spec_reference="PCIe 6.0.1 Section 7.7.8",
                message=f"Lane margining requires Gen4+, current: {link_status.current_speed}",
                port_number=port.port_number,
            )
        )
        return results, eye_data

    try:
        engine = LaneMarginingEngine(device, device_key, port.port_number)
    except ValueError as exc:
        results.append(
            TestResult(
                test_id="T4.1",
                test_name="Eye Measurement",
                suite_id=SUITE,
                verdict=Verdict.SKIP,
                spec_reference="PCIe 6.0.1 Section 7.7.8",
                message=str(exc),
                port_number=port.port_number,
            )
        )
        return results, eye_data

    try:
        # Branch on modulation: PAM4 (Gen6) vs NRZ (Gen4/5)
        if speed_code >= 6:
            return _run_pam4_signal_integrity(
                engine,
                device_id,
                speed_code,
                port,
                results,
                eye_data,
            )

        return _run_nrz_signal_integrity(
            engine,
            device_id,
            speed_code,
            port,
            results,
            eye_data,
        )
    finally:
        engine.close()


def _run_nrz_signal_integrity(
    engine: LaneMarginingEngine,
    device_id: str,
    speed_code: int,
    port: PortConfig,
    results: list[TestResult],
    eye_data: dict[str, object],
) -> tuple[list[TestResult], dict[str, object]]:
    """NRZ signal integrity: single-eye sweep per lane (Gen4/5)."""
    # T4.1: Sweep each lane
    lane_measurements: list[dict[str, object]] = []
    for lane in range(port.num_lanes):
        t_start = time.monotonic()
        try:
            sweep = engine.sweep_lane(lane, device_id)
            measurement = {
                "lane": lane,
                "eye_width_ui": sweep.eye_width_ui,
                "eye_height_mv": sweep.eye_height_mv,
                "eye_width_steps": sweep.eye_width_steps,
                "eye_height_steps": sweep.eye_height_steps,
            }
            lane_measurements.append(measurement)

            results.append(
                TestResult(
                    test_id="T4.1",
                    test_name=f"Eye Measurement (Lane {lane})",
                    suite_id=SUITE,
                    verdict=Verdict.PASS,
                    spec_reference="PCIe 6.0.1 Section 7.7.8",
                    criteria="Margining sweep completed",
                    message=f"Eye: {sweep.eye_width_ui:.4f} UI x {sweep.eye_height_mv:.1f} mV",
                    measured_values=measurement,
                    duration_ms=_elapsed(t_start),
                    port_number=port.port_number,
                    lane=lane,
                )
            )
        except Exception as exc:
            results.append(
                TestResult(
                    test_id="T4.1",
                    test_name=f"Eye Measurement (Lane {lane})",
                    suite_id=SUITE,
                    verdict=Verdict.ERROR,
                    spec_reference="PCIe 6.0.1 Section 7.7.8",
                    message=str(exc),
                    duration_ms=_elapsed(t_start),
                    port_number=port.port_number,
                    lane=lane,
                )
            )

    eye_data["lane_measurements"] = lane_measurements

    # T4.2: Spec minimum check
    results.extend(
        _t4_2_spec_minimum_check(
            lane_measurements,
            speed_code,
            port,
        )
    )

    # T4.3: Per-lane comparison
    results.extend(_t4_3_lane_comparison(lane_measurements, port))

    return results, eye_data


def _run_pam4_signal_integrity(
    engine: LaneMarginingEngine,
    device_id: str,
    speed_code: int,
    port: PortConfig,
    results: list[TestResult],
    eye_data: dict[str, object],
) -> tuple[list[TestResult], dict[str, object]]:
    """PAM4 signal integrity: 3-eye sweep per lane (Gen6)."""
    eye_labels = ("upper", "middle", "lower")
    lane_measurements: list[dict[str, object]] = []

    for lane in range(port.num_lanes):
        t_start = time.monotonic()
        try:
            pam4 = engine.sweep_lane_pam4(lane, device_id)

            # Produce one measurement per eye for T4.2 spec minimum checks
            for label, eye_result in zip(
                eye_labels, (pam4.upper_eye, pam4.middle_eye, pam4.lower_eye)
            ):
                measurement = {
                    "lane": lane,
                    "eye": label,
                    "eye_width_ui": eye_result.eye_width_ui,
                    "eye_height_mv": eye_result.eye_height_mv,
                    "eye_width_steps": eye_result.eye_width_steps,
                    "eye_height_steps": eye_result.eye_height_steps,
                }
                lane_measurements.append(measurement)

                results.append(
                    TestResult(
                        test_id="T4.1",
                        test_name=f"PAM4 Eye Measurement (Lane {lane}, {label})",
                        suite_id=SUITE,
                        verdict=Verdict.PASS,
                        spec_reference="PCIe 6.0.1 Section 7.7.8",
                        criteria="PAM4 margining sweep completed",
                        message=(
                            f"{label.capitalize()} eye: "
                            f"{eye_result.eye_width_ui:.4f} UI x {eye_result.eye_height_mv:.1f} mV"
                        ),
                        measured_values=measurement,
                        duration_ms=eye_result.sweep_time_ms,
                        port_number=port.port_number,
                        lane=lane,
                    )
                )

        except Exception as exc:
            results.append(
                TestResult(
                    test_id="T4.1",
                    test_name=f"PAM4 Eye Measurement (Lane {lane})",
                    suite_id=SUITE,
                    verdict=Verdict.ERROR,
                    spec_reference="PCIe 6.0.1 Section 7.7.8",
                    message=str(exc),
                    duration_ms=_elapsed(t_start),
                    port_number=port.port_number,
                    lane=lane,
                )
            )

    eye_data["lane_measurements"] = lane_measurements
    eye_data["modulation"] = "PAM4"

    # T4.2: Spec minimum check (per-eye — each measurement is checked independently)
    results.extend(
        _t4_2_spec_minimum_check(
            lane_measurements,
            speed_code,
            port,
        )
    )

    # T4.3: Per-lane comparison using worst-case eye per lane
    worst_per_lane = _worst_case_per_lane(lane_measurements)
    results.extend(_t4_3_lane_comparison(worst_per_lane, port))

    # T4.4: PAM4 eye balance check
    results.extend(_t4_4_pam4_balance_check(lane_measurements, port))

    return results, eye_data


def _worst_case_per_lane(
    measurements: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Reduce PAM4 per-eye measurements to worst-case per lane."""
    lanes: dict[int, dict[str, object]] = {}
    for m in measurements:
        lane = int(m["lane"])
        w = float(m.get("eye_width_ui", 0))
        h = float(m.get("eye_height_mv", 0))
        if lane not in lanes:
            lanes[lane] = {
                "lane": lane,
                "eye_width_ui": w,
                "eye_height_mv": h,
            }
        else:
            existing = lanes[lane]
            existing["eye_width_ui"] = min(float(existing["eye_width_ui"]), w)
            existing["eye_height_mv"] = min(float(existing["eye_height_mv"]), h)
    return list(lanes.values())


def _t4_2_spec_minimum_check(
    measurements: list[dict[str, object]],
    speed_gen: int,
    port: PortConfig,
) -> list[TestResult]:
    """T4.2: Compare eye dimensions against spec thresholds."""
    results: list[TestResult] = []

    threshold = EYE_THRESHOLDS.get(speed_gen)
    if threshold is None:
        results.append(
            TestResult(
                test_id="T4.2",
                test_name="Spec Minimum Eye Check",
                suite_id=SUITE,
                verdict=Verdict.SKIP,
                spec_reference="PCIe CEM 6.0",
                message=f"No threshold defined for Gen{speed_gen}",
                port_number=port.port_number,
            )
        )
        return results

    for m in measurements:
        lane = m["lane"]
        eye_label = m.get("eye", "")
        width = float(m.get("eye_width_ui", 0))
        height = float(m.get("eye_height_mv", 0))

        width_ok = width >= threshold.min_eye_width_ui
        height_ok = height >= threshold.min_eye_height_mv

        suffix = f", {eye_label}" if eye_label else ""
        test_name = f"Spec Minimum Eye Check (Lane {lane}{suffix})"

        if width_ok and height_ok:
            verdict = Verdict.PASS
            msg = (
                f"Lane {lane}{suffix}: {width:.4f} UI >= {threshold.min_eye_width_ui} UI, "
                f"{height:.1f} mV >= {threshold.min_eye_height_mv} mV"
            )
        else:
            verdict = Verdict.FAIL
            parts = []
            if not width_ok:
                parts.append(f"width {width:.4f} < {threshold.min_eye_width_ui} UI")
            if not height_ok:
                parts.append(f"height {height:.1f} < {threshold.min_eye_height_mv} mV")
            msg = f"Lane {lane}{suffix}: {'; '.join(parts)}"

        results.append(
            TestResult(
                test_id="T4.2",
                test_name=test_name,
                suite_id=SUITE,
                verdict=verdict,
                spec_reference="PCIe CEM 6.0",
                criteria=f"Eye >= {threshold.min_eye_width_ui} UI x {threshold.min_eye_height_mv} mV",
                message=msg,
                measured_values={
                    "lane": lane,
                    "eye": eye_label,
                    "eye_width_ui": width,
                    "eye_height_mv": height,
                    "min_width_ui": threshold.min_eye_width_ui,
                    "min_height_mv": threshold.min_eye_height_mv,
                },
                port_number=port.port_number,
                lane=int(lane),
            )
        )

    return results


def _t4_3_lane_comparison(
    measurements: list[dict[str, object]],
    port: PortConfig,
) -> list[TestResult]:
    """T4.3: Flag lanes significantly worse than average."""
    if len(measurements) < 2:
        return [
            TestResult(
                test_id="T4.3",
                test_name="Per-Lane Margin Comparison",
                suite_id=SUITE,
                verdict=Verdict.SKIP,
                spec_reference="PCIe CEM 6.0",
                message="Need at least 2 lanes for comparison",
                port_number=port.port_number,
            )
        ]

    widths = [float(m.get("eye_width_ui", 0)) for m in measurements]
    heights = [float(m.get("eye_height_mv", 0)) for m in measurements]

    avg_width = sum(widths) / len(widths)
    avg_height = sum(heights) / len(heights)

    outliers: list[str] = []
    threshold_pct = LANE_MARGIN_OUTLIER_PERCENT / 100.0

    for m in measurements:
        lane = m["lane"]
        w = float(m.get("eye_width_ui", 0))
        h = float(m.get("eye_height_mv", 0))

        if avg_width > 0 and w < avg_width * (1.0 - threshold_pct):
            outliers.append(
                f"Lane {lane} width {w:.4f} UI ({_pct_below(w, avg_width):.0f}% below avg)"
            )
        if avg_height > 0 and h < avg_height * (1.0 - threshold_pct):
            outliers.append(
                f"Lane {lane} height {h:.1f} mV ({_pct_below(h, avg_height):.0f}% below avg)"
            )

    if not outliers:
        verdict = Verdict.PASS
        msg = f"All lanes within {LANE_MARGIN_OUTLIER_PERCENT}% of average (avg: {avg_width:.4f} UI, {avg_height:.1f} mV)"
    else:
        verdict = Verdict.WARN
        msg = f"{len(outliers)} outlier(s): {'; '.join(outliers[:5])}"

    return [
        TestResult(
            test_id="T4.3",
            test_name="Per-Lane Margin Comparison",
            suite_id=SUITE,
            verdict=verdict,
            spec_reference="PCIe CEM 6.0",
            criteria=f"No lane >{LANE_MARGIN_OUTLIER_PERCENT}% below average",
            message=msg,
            measured_values={
                "avg_width_ui": round(avg_width, 4),
                "avg_height_mv": round(avg_height, 1),
                "outliers": outliers,
                "lane_count": len(measurements),
            },
            port_number=port.port_number,
        )
    ]


def _t4_4_pam4_balance_check(
    measurements: list[dict[str, object]],
    port: PortConfig,
) -> list[TestResult]:
    """T4.4: Check PAM4 3-eye height balance per lane.

    All 3 eye heights should be within 20% of their average. Significant
    imbalance indicates transmitter or channel linearity issues.
    """
    # Group measurements by lane
    lanes: dict[int, dict[str, float]] = {}
    for m in measurements:
        lane = int(m["lane"])
        eye = str(m.get("eye", ""))
        height = float(m.get("eye_height_mv", 0))
        if lane not in lanes:
            lanes[lane] = {}
        lanes[lane][eye] = height

    results: list[TestResult] = []
    for lane in sorted(lanes.keys()):
        heights = lanes[lane]
        upper = heights.get("upper", 0.0)
        middle = heights.get("middle", 0.0)
        lower = heights.get("lower", 0.0)

        if upper == 0 and middle == 0 and lower == 0:
            continue

        avg = (upper + middle + lower) / 3
        if avg == 0:
            balanced = True
        else:
            balanced = all(abs(h - avg) / avg <= 0.2 for h in (upper, middle, lower))

        if balanced:
            verdict = Verdict.PASS
            msg = (
                f"Lane {lane}: heights {upper:.1f}/{middle:.1f}/{lower:.1f} mV "
                f"(avg {avg:.1f} mV) - balanced"
            )
        else:
            verdict = Verdict.WARN
            msg = (
                f"Lane {lane}: heights {upper:.1f}/{middle:.1f}/{lower:.1f} mV "
                f"(avg {avg:.1f} mV) - imbalanced (>20% deviation)"
            )

        results.append(
            TestResult(
                test_id="T4.4",
                test_name=f"PAM4 Eye Balance (Lane {lane})",
                suite_id=SUITE,
                verdict=verdict,
                spec_reference="PCIe 6.0.1 Section 4.2",
                criteria="3 PAM4 eye heights within 20% of average",
                message=msg,
                measured_values={
                    "lane": lane,
                    "upper_height_mv": upper,
                    "middle_height_mv": middle,
                    "lower_height_mv": lower,
                    "avg_height_mv": round(avg, 1),
                    "balanced": balanced,
                },
                port_number=port.port_number,
                lane=lane,
            )
        )

    if not results:
        results.append(
            TestResult(
                test_id="T4.4",
                test_name="PAM4 Eye Balance",
                suite_id=SUITE,
                verdict=Verdict.SKIP,
                spec_reference="PCIe 6.0.1 Section 4.2",
                message="No PAM4 eye height data available",
                port_number=port.port_number,
            )
        )

    return results


def _pct_below(value: float, avg: float) -> float:
    if avg == 0:
        return 0.0
    return ((avg - value) / avg) * 100.0


def _elapsed(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 2)
