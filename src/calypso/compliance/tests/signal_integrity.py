"""T4.x Signal Integrity compliance tests.

Eye width/height measurement via lane margining, spec minimum check,
and per-lane margin comparison.
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
        results.append(TestResult(
            test_id="T4.1",
            test_name="Eye Measurement",
            suite_id=SUITE,
            verdict=Verdict.SKIP,
            spec_reference="PCIe 6.0.1 Section 7.7.8",
            message=f"Lane margining requires Gen4+, current: {link_status.current_speed}",
            port_number=port.port_number,
        ))
        return results, eye_data

    try:
        engine = LaneMarginingEngine(device, device_key, port.port_number)
    except ValueError as exc:
        results.append(TestResult(
            test_id="T4.1",
            test_name="Eye Measurement",
            suite_id=SUITE,
            verdict=Verdict.SKIP,
            spec_reference="PCIe 6.0.1 Section 7.7.8",
            message=str(exc),
            port_number=port.port_number,
        ))
        return results, eye_data

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

            results.append(TestResult(
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
            ))
        except Exception as exc:
            results.append(TestResult(
                test_id="T4.1",
                test_name=f"Eye Measurement (Lane {lane})",
                suite_id=SUITE,
                verdict=Verdict.ERROR,
                spec_reference="PCIe 6.0.1 Section 7.7.8",
                message=str(exc),
                duration_ms=_elapsed(t_start),
                port_number=port.port_number,
                lane=lane,
            ))

    eye_data["lane_measurements"] = lane_measurements

    # T4.2: Spec minimum check
    results.extend(_t4_2_spec_minimum_check(
        lane_measurements, speed_code, port,
    ))

    # T4.3: Per-lane comparison
    results.extend(_t4_3_lane_comparison(lane_measurements, port))

    return results, eye_data


def _t4_2_spec_minimum_check(
    measurements: list[dict[str, object]],
    speed_gen: int,
    port: PortConfig,
) -> list[TestResult]:
    """T4.2: Compare eye dimensions against spec thresholds."""
    results: list[TestResult] = []

    threshold = EYE_THRESHOLDS.get(speed_gen)
    if threshold is None:
        results.append(TestResult(
            test_id="T4.2",
            test_name="Spec Minimum Eye Check",
            suite_id=SUITE,
            verdict=Verdict.SKIP,
            spec_reference="PCIe CEM 6.0",
            message=f"No threshold defined for Gen{speed_gen}",
            port_number=port.port_number,
        ))
        return results

    for m in measurements:
        lane = m["lane"]
        width = float(m.get("eye_width_ui", 0))
        height = float(m.get("eye_height_mv", 0))

        width_ok = width >= threshold.min_eye_width_ui
        height_ok = height >= threshold.min_eye_height_mv

        if width_ok and height_ok:
            verdict = Verdict.PASS
            msg = (
                f"Lane {lane}: {width:.4f} UI >= {threshold.min_eye_width_ui} UI, "
                f"{height:.1f} mV >= {threshold.min_eye_height_mv} mV"
            )
        else:
            verdict = Verdict.FAIL
            parts = []
            if not width_ok:
                parts.append(f"width {width:.4f} < {threshold.min_eye_width_ui} UI")
            if not height_ok:
                parts.append(f"height {height:.1f} < {threshold.min_eye_height_mv} mV")
            msg = f"Lane {lane}: {'; '.join(parts)}"

        results.append(TestResult(
            test_id="T4.2",
            test_name=f"Spec Minimum Eye Check (Lane {lane})",
            suite_id=SUITE,
            verdict=verdict,
            spec_reference="PCIe CEM 6.0",
            criteria=f"Eye >= {threshold.min_eye_width_ui} UI x {threshold.min_eye_height_mv} mV",
            message=msg,
            measured_values={
                "lane": lane,
                "eye_width_ui": width,
                "eye_height_mv": height,
                "min_width_ui": threshold.min_eye_width_ui,
                "min_height_mv": threshold.min_eye_height_mv,
            },
            port_number=port.port_number,
            lane=int(lane),
        ))

    return results


def _t4_3_lane_comparison(
    measurements: list[dict[str, object]],
    port: PortConfig,
) -> list[TestResult]:
    """T4.3: Flag lanes significantly worse than average."""
    if len(measurements) < 2:
        return [TestResult(
            test_id="T4.3",
            test_name="Per-Lane Margin Comparison",
            suite_id=SUITE,
            verdict=Verdict.SKIP,
            spec_reference="PCIe CEM 6.0",
            message="Need at least 2 lanes for comparison",
            port_number=port.port_number,
        )]

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
            outliers.append(f"Lane {lane} width {w:.4f} UI ({_pct_below(w, avg_width):.0f}% below avg)")
        if avg_height > 0 and h < avg_height * (1.0 - threshold_pct):
            outliers.append(f"Lane {lane} height {h:.1f} mV ({_pct_below(h, avg_height):.0f}% below avg)")

    if not outliers:
        verdict = Verdict.PASS
        msg = f"All lanes within {LANE_MARGIN_OUTLIER_PERCENT}% of average (avg: {avg_width:.4f} UI, {avg_height:.1f} mV)"
    else:
        verdict = Verdict.WARN
        msg = f"{len(outliers)} outlier(s): {'; '.join(outliers[:5])}"

    return [TestResult(
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
    )]


def _pct_below(value: float, avg: float) -> float:
    if avg == 0:
        return 0.0
    return ((avg - value) / avg) * 100.0


def _elapsed(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 2)
