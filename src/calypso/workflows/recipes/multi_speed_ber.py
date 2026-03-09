"""Multi-speed BER recipe -- set link speed then run BER soak at each PCIe gen."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.core.pcie_config import PcieConfigReader
from calypso.core.phy_monitor import PhyMonitor
from calypso.hardware.atlas3_phy import UserTestPattern
from calypso.utils.logging import get_logger
from calypso.workflows.base import Recipe
from calypso.workflows.models import (
    RecipeCategory,
    RecipeParameter,
    RecipeResult,
    RecipeSummary,
    StepCriticality,
    StepStatus,
)

logger = get_logger(__name__)

_BER_PASS_THRESHOLD = 1e-12
_BER_WARN_THRESHOLD = 1e-9

# (label, link_speed_code, expected_speed_substring)
_ALL_SPEEDS: list[tuple[str, int, str]] = [
    ("8GT", 3, "8.0"),
    ("16GT", 4, "16.0"),
    ("32GT", 5, "32.0"),
    ("64GT", 6, "64"),
]

_SPEED_SETS: dict[str, list[tuple[str, int, str]]] = {
    "all": _ALL_SPEEDS,
    "gen3_gen4": [("8GT", 3, "8.0"), ("16GT", 4, "16.0")],
    "gen5_gen6": [("32GT", 5, "32.0"), ("64GT", 6, "64")],
}

# Default 16-byte UTP pattern
_DEFAULT_PATTERN = bytes([0xAA, 0x55] * 8)

# Approximate per-lane bit rates by speed code for BER estimation
_LANE_RATE_BPS: dict[int, float] = {
    3: 8.0e9,  # Gen3 8GT/s
    4: 16.0e9,  # Gen4 16GT/s
    5: 32.0e9,  # Gen5 32GT/s
    6: 64.0e9,  # Gen6 64GT/s
}

# Time to wait for link to retrain at new speed
_SPEED_CHANGE_SETTLE_S = 2.0


class MultiSpeedBerRecipe(Recipe):
    """Run BER soak at multiple PCIe link speeds to validate signal integrity."""

    @property
    def recipe_id(self) -> str:
        return "multi_speed_ber"

    @property
    def name(self) -> str:
        return "Multi-Speed BER Test"

    @property
    def description(self) -> str:
        return "Set link speed then run BER soak (UTP or FBER) at each PCIe generation"

    @property
    def category(self) -> RecipeCategory:
        return RecipeCategory.ERROR_TESTING

    @property
    def estimated_duration_s(self) -> int:
        return 180

    @property
    def parameters(self) -> list[RecipeParameter]:
        return [
            RecipeParameter(
                name="port_number",
                label="Port Number",
                description="Target port for multi-speed BER",
                param_type="int",
                default=0,
                min_value=0,
                max_value=143,
            ),
            RecipeParameter(
                name="ber_duration_s",
                label="BER Duration per Speed",
                description="Soak duration at each speed",
                param_type="float",
                default=10.0,
                min_value=5.0,
                max_value=120.0,
                unit="s",
            ),
            RecipeParameter(
                name="speeds",
                label="Speed Set",
                description="Which link speeds to test",
                param_type="choice",
                default="all",
                choices=["all", "gen3_gen4", "gen5_gen6"],
            ),
        ]

    def run(
        self,
        dev: PLX_DEVICE_OBJECT,
        dev_key: PLX_DEVICE_KEY,
        cancel: dict[str, bool],
        **kwargs: Any,
    ) -> Generator[RecipeResult, None, RecipeSummary]:
        start_time = time.monotonic()
        steps: list[RecipeResult] = []

        port_number: int = int(kwargs.get("port_number", 0))
        ber_duration_s: float = float(kwargs.get("ber_duration_s", 10.0))
        speeds_key: str = str(kwargs.get("speeds", "all"))
        device_id: str = str(kwargs.get("device_id", ""))

        params = {
            "port_number": port_number,
            "ber_duration_s": ber_duration_s,
            "speeds": speeds_key,
        }

        speed_list = _SPEED_SETS.get(speeds_key, _ALL_SPEEDS)

        # Record original speed for restoration
        original_speed_code: int | None = None

        # Initialise hardware helpers
        try:
            config = PcieConfigReader(dev, dev_key)
            phy = PhyMonitor(dev, dev_key, port_number)
            link = config.get_link_status()
            original_speed_code = _speed_string_to_code(link.current_speed or "")
        except Exception as exc:
            step = f"BER at {speed_list[0][0]}"
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Hardware init failed: {exc}",
                criticality=StepCriticality.CRITICAL,
                port_number=port_number,
            )
            yield self._make_running(step)
            yield result
            steps.append(result)
            return self._make_summary(steps, start_time, params, device_id)

        pattern = UserTestPattern(data=_DEFAULT_PATTERN)

        for speed_label, speed_code, expected_substr in speed_list:
            if self._is_cancelled(cancel):
                skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
                yield skip
                steps.append(skip)
                break

            step = f"BER at {speed_label} (Gen{speed_code})"
            yield self._make_running(step)
            t0 = time.monotonic()

            try:
                # Set target link speed and retrain
                config.set_target_link_speed(speed_code)
                config.retrain_link()
                time.sleep(_SPEED_CHANGE_SETTLE_S)

                # Verify negotiated speed
                post_link = config.get_link_status()
                actual_speed = post_link.current_speed or ""
                speed_matched = expected_substr in actual_speed

                if not speed_matched:
                    dur = round((time.monotonic() - t0) * 1000, 2)
                    result = self._make_result(
                        step,
                        StepStatus.WARN,
                        message=(
                            f"{speed_label}: speed mismatch — "
                            f"expected {expected_substr}, got {actual_speed}"
                        ),
                        criticality=StepCriticality.HIGH,
                        measured_values={
                            "speed": speed_label,
                            "speed_code": speed_code,
                            "actual_speed": actual_speed,
                            "speed_matched": False,
                        },
                        duration_ms=dur,
                        port_number=port_number,
                    )
                    yield result
                    steps.append(result)
                    continue

                is_64gt = speed_code == 6

                if is_64gt:
                    # FBER path for 64GT/s
                    config.clear_fber_counters()
                    config.start_fber_measurement(0)

                    elapsed = 0.0
                    while elapsed < ber_duration_s:
                        if self._is_cancelled(cancel):
                            break
                        chunk = min(1.0, ber_duration_s - elapsed)
                        time.sleep(chunk)
                        elapsed += chunk

                    config.stop_fber_measurement()
                    fber = config.get_fber_status()
                    dur = round((time.monotonic() - t0) * 1000, 2)

                    if fber is None:
                        status = StepStatus.ERROR
                        msg = f"{speed_label}: FBER capability not present"
                        bits_tested = 0.0
                        lane_details: list[dict[str, object]] = []
                    else:
                        total_errors = sum(fber.lane_counters)
                        bits_tested = elapsed * 64.0e9
                        lane_details = []
                        for lane_idx, count in enumerate(fber.lane_counters):
                            ber = count / bits_tested if bits_tested > 0 else 0.0
                            lane_details.append(
                                {
                                    "lane": lane_idx,
                                    "error_count": count,
                                    "estimated_ber": ber,
                                }
                            )
                        if total_errors == 0:
                            status = StepStatus.PASS
                            msg = f"{speed_label}: zero FBER errors across all lanes"
                        else:
                            status = StepStatus.WARN
                            msg = f"{speed_label}: {total_errors} FBER error(s) detected"

                    result = self._make_result(
                        step,
                        status,
                        message=msg,
                        criticality=StepCriticality.CRITICAL,
                        measured_values={
                            "speed": speed_label,
                            "speed_code": speed_code,
                            "actual_speed": actual_speed,
                            "mode": "fber",
                            "total_errors": total_errors if fber else 0,
                            "bits_tested": bits_tested,
                            "flit_counter": fber.flit_counter if fber else 0,
                            "soak_duration_s": round(elapsed, 1),
                            "lane_counters": fber.lane_counters if fber else [],
                            "lanes": lane_details,
                        },
                        duration_ms=dur,
                        port_number=port_number,
                    )
                else:
                    # UTP path for <=32GT/s
                    phy.prepare_utp_test(pattern)

                    elapsed = 0.0
                    while elapsed < ber_duration_s:
                        if self._is_cancelled(cancel):
                            break
                        chunk = min(1.0, ber_duration_s - elapsed)
                        time.sleep(chunk)
                        elapsed += chunk

                    utp_results = phy.collect_utp_results()
                    dur = round((time.monotonic() - t0) * 1000, 2)

                    total_errors = sum(r.error_count for r in utp_results)
                    all_synced = all(r.synced for r in utp_results)

                    bits_tested = elapsed * _LANE_RATE_BPS.get(speed_code, 32.0e9)
                    lane_details_utp: list[dict[str, object]] = []
                    for r in utp_results:
                        ber = r.error_count / bits_tested if bits_tested > 0 else 0.0
                        lane_details_utp.append(
                            {
                                "lane": r.lane,
                                "error_count": r.error_count,
                                "synced": r.synced,
                                "estimated_ber": ber,
                            }
                        )

                    if not all_synced:
                        status = StepStatus.FAIL
                        msg = f"{speed_label}: sync failure on some lanes"
                    elif total_errors == 0:
                        status = StepStatus.PASS
                        msg = f"{speed_label}: zero errors across all lanes"
                    else:
                        status = StepStatus.WARN
                        msg = f"{speed_label}: {total_errors} error(s) detected"

                    result = self._make_result(
                        step,
                        status,
                        message=msg,
                        criticality=StepCriticality.CRITICAL,
                        measured_values={
                            "speed": speed_label,
                            "speed_code": speed_code,
                            "actual_speed": actual_speed,
                            "mode": "utp",
                            "total_errors": total_errors,
                            "bits_tested": bits_tested,
                            "all_synced": all_synced,
                            "soak_duration_s": round(elapsed, 1),
                            "lanes_tested": len(utp_results),
                            "lanes": lane_details_utp,
                        },
                        duration_ms=dur,
                        port_number=port_number,
                    )
            except Exception as exc:
                dur = round((time.monotonic() - t0) * 1000, 2)
                result = self._make_result(
                    step,
                    StepStatus.ERROR,
                    message=f"{speed_label} BER test failed: {exc}",
                    criticality=StepCriticality.HIGH,
                    duration_ms=dur,
                    port_number=port_number,
                )

            yield result
            steps.append(result)

        # Restore original speed
        if original_speed_code is not None and original_speed_code > 0:
            step = "Restore original speed"
            yield self._make_running(step)
            t0 = time.monotonic()
            try:
                config.set_target_link_speed(original_speed_code)
                config.retrain_link()
                time.sleep(_SPEED_CHANGE_SETTLE_S)
                restored_link = config.get_link_status()
                dur = round((time.monotonic() - t0) * 1000, 2)
                result = self._make_result(
                    step,
                    StepStatus.PASS,
                    message=f"Restored to {restored_link.current_speed}",
                    criticality=StepCriticality.MEDIUM,
                    measured_values={"restored_speed": restored_link.current_speed},
                    duration_ms=dur,
                    port_number=port_number,
                )
            except Exception as exc:
                dur = round((time.monotonic() - t0) * 1000, 2)
                result = self._make_result(
                    step,
                    StepStatus.WARN,
                    message=f"Failed to restore original speed: {exc}",
                    criticality=StepCriticality.MEDIUM,
                    duration_ms=dur,
                    port_number=port_number,
                )
            yield result
            steps.append(result)

        return self._make_summary(steps, start_time, params, device_id)


def _speed_string_to_code(speed_str: str) -> int:
    """Map a speed string like '64 GT/s' to a code (1-6). Returns 0 if unknown."""
    if "64" in speed_str:
        return 6
    if "32" in speed_str:
        return 5
    if "16" in speed_str:
        return 4
    if "8.0" in speed_str:
        return 3
    if "5.0" in speed_str:
        return 2
    if "2.5" in speed_str:
        return 1
    return 0
