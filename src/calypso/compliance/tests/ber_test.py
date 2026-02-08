"""T5.x BER (Bit Error Rate) compliance tests.

Uses User Test Pattern (PRBS31) and SerDes error counters to approximate BER.
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
from calypso.compliance.thresholds import EYE_THRESHOLDS, GEN_NAME_TO_SPEED_CODE
from calypso.core.pcie_config import PcieConfigReader
from calypso.core.phy_monitor import PhyMonitor
from calypso.hardware.atlas3_phy import UserTestPattern
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

SUITE = TestSuiteId.BER_TEST

# PRBS31 pattern for BER testing (16-byte seed)
_PRBS31_SEED = bytes([
    0xFF, 0xFF, 0xFF, 0xFF,
    0xFF, 0xFF, 0xFF, 0xFF,
    0xFF, 0xFF, 0xFF, 0xFF,
    0xFF, 0xFF, 0xFF, 0xFF,
])

# Approximate bits per second for each generation (per lane)
_BITS_PER_SEC: dict[int, float] = {
    1: 2.5e9,
    2: 5.0e9,
    3: 8.0e9,
    4: 16.0e9,
    5: 32.0e9,
    6: 64.0e9,
}


def run_ber_tests(
    device: PLX_DEVICE_OBJECT,
    device_key: PLX_DEVICE_KEY,
    device_id: str,
    port: PortConfig,
    config: TestRunConfig,
) -> tuple[list[TestResult], dict[str, object]]:
    """Execute BER tests. Returns (results, ber_data_for_report)."""
    results: list[TestResult] = []
    ber_data: dict[str, object] = {}

    reader = PcieConfigReader(device, device_key)
    phy = PhyMonitor(device, device_key, port.port_number)

    # T5.1: PRBS BER at current speed
    link_status = reader.get_link_status()
    speed_code = GEN_NAME_TO_SPEED_CODE.get(link_status.current_speed, 0)

    t5_1_results, lane_bers = _t5_1_prbs_ber(
        phy, reader, port, config, speed_code,
    )
    results.extend(t5_1_results)
    ber_data["current_speed"] = {
        "gen": speed_code,
        "lane_bers": lane_bers,
    }

    # T5.2: Multi-speed BER
    t5_2_results, multi_ber = _t5_2_multi_speed_ber(
        phy, reader, port, config, speed_code,
    )
    results.extend(t5_2_results)
    ber_data["multi_speed"] = multi_ber

    return results, ber_data


def _t5_1_prbs_ber(
    phy: PhyMonitor,
    reader: PcieConfigReader,
    port: PortConfig,
    config: TestRunConfig,
    speed_code: int,
) -> tuple[list[TestResult], list[dict[str, object]]]:
    """T5.1: Run PRBS31 pattern test and calculate per-lane BER."""
    results: list[TestResult] = []
    lane_bers: list[dict[str, object]] = []
    t_start = time.monotonic()

    threshold = EYE_THRESHOLDS.get(speed_code)
    max_ber = threshold.max_ber if threshold else 1e-12
    bits_per_sec = _BITS_PER_SEC.get(speed_code, 8.0e9)

    try:
        pattern = UserTestPattern.from_bytes(_PRBS31_SEED)
        phy.prepare_utp_test(pattern, port_select=port.port_select)

        # Clear all lane error counters
        for lane in range(port.num_lanes):
            phy.clear_serdes_errors(lane)

        # Wait for the configured BER duration
        time.sleep(config.ber_duration_s)

        # Collect results
        utp_results = phy.collect_utp_results(port.num_lanes)
        total_bits = bits_per_sec * config.ber_duration_s

        for utp_res in utp_results:
            lane = utp_res.lane
            if lane >= port.num_lanes:
                continue

            error_count = utp_res.error_count
            ber = error_count / total_bits if total_bits > 0 else 0.0

            lane_entry = {
                "lane": lane,
                "error_count": error_count,
                "ber": ber,
                "synced": utp_res.synced,
                "total_bits": total_bits,
            }
            lane_bers.append(lane_entry)

            if not utp_res.synced:
                verdict = Verdict.ERROR
                msg = f"Lane {lane}: UTP not synced"
            elif ber <= max_ber:
                verdict = Verdict.PASS
                msg = f"Lane {lane}: BER={ber:.2e} <= {max_ber:.0e} ({error_count} errors in {config.ber_duration_s}s)"
            else:
                verdict = Verdict.FAIL
                msg = f"Lane {lane}: BER={ber:.2e} > {max_ber:.0e} ({error_count} errors)"

            results.append(TestResult(
                test_id="T5.1",
                test_name=f"PRBS BER Test (Lane {lane})",
                suite_id=SUITE,
                verdict=verdict,
                spec_reference="PCIe 6.0.1 Section 4.2.8",
                criteria=f"BER <= {max_ber:.0e}",
                message=msg,
                measured_values=lane_entry,
                duration_ms=_elapsed(t_start),
                port_number=port.port_number,
                lane=lane,
            ))

    except Exception as exc:
        results.append(TestResult(
            test_id="T5.1",
            test_name="PRBS BER Test",
            suite_id=SUITE,
            verdict=Verdict.ERROR,
            spec_reference="PCIe 6.0.1 Section 4.2.8",
            message=str(exc),
            duration_ms=_elapsed(t_start),
            port_number=port.port_number,
        ))

    return results, lane_bers


def _t5_2_multi_speed_ber(
    phy: PhyMonitor,
    reader: PcieConfigReader,
    port: PortConfig,
    config: TestRunConfig,
    original_speed_code: int,
) -> tuple[list[TestResult], list[dict[str, object]]]:
    """T5.2: Run BER test at each supported speed."""
    results: list[TestResult] = []
    multi_ber: list[dict[str, object]] = []

    speeds = reader.get_supported_speeds()
    supported = [
        GEN_NAME_TO_SPEED_CODE[name]
        for name in speeds.as_list
        if GEN_NAME_TO_SPEED_CODE.get(name, 0) >= 3  # BER testing meaningful at Gen3+
    ]

    # Skip if only one speed (already tested in T5.1)
    if len(supported) <= 1:
        results.append(TestResult(
            test_id="T5.2",
            test_name="Multi-Speed BER",
            suite_id=SUITE,
            verdict=Verdict.SKIP,
            spec_reference="PCIe 6.0.1 Section 4.2.8",
            message="Only one speed at Gen3+; covered by T5.1",
            port_number=port.port_number,
        ))
        return results, multi_ber

    try:
        for speed_code in supported:
            if speed_code == original_speed_code:
                continue  # Already tested

            t_start = time.monotonic()
            gen_name = f"Gen{speed_code}"

            try:
                reader.set_target_link_speed(speed_code)
                reader.retrain_link()
                time.sleep(config.speed_settle_s)

                # Run abbreviated BER (half duration for multi-speed)
                half_config = TestRunConfig(
                    suites=config.suites,
                    ports=config.ports,
                    ber_duration_s=config.ber_duration_s / 2,
                    idle_wait_s=config.idle_wait_s,
                    speed_settle_s=config.speed_settle_s,
                )
                sub_results, lane_bers = _t5_1_prbs_ber(
                    phy, reader, port, half_config, speed_code,
                )

                # Re-tag as T5.2 with immutable copies
                for r in sub_results:
                    retagged = r.model_copy(update={
                        "test_id": "T5.2",
                        "test_name": f"Multi-Speed BER ({gen_name}, {r.test_name.split('(')[-1]})",
                    })
                    results.append(retagged)
                multi_ber.append({
                    "gen": speed_code,
                    "gen_name": gen_name,
                    "lane_bers": lane_bers,
                })

            except Exception as exc:
                results.append(TestResult(
                    test_id="T5.2",
                    test_name=f"Multi-Speed BER ({gen_name})",
                    suite_id=SUITE,
                    verdict=Verdict.ERROR,
                    spec_reference="PCIe 6.0.1 Section 4.2.8",
                    message=str(exc),
                    duration_ms=_elapsed(t_start),
                    port_number=port.port_number,
                ))

    finally:
        # Restore original speed
        if original_speed_code >= 1:
            try:
                reader.set_target_link_speed(original_speed_code)
                reader.retrain_link()
                time.sleep(config.speed_settle_s)
            except Exception:
                logger.warning("speed_restore_failed", port=port.port_number)

    return results, multi_ber


def _elapsed(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 2)
