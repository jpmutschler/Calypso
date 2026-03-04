"""Speed Downshift Test recipe -- downshift through speeds and verify clean transitions."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.core.pcie_config import PcieConfigReader
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

# (label, speed_code, expected_speed_substring)
_DOWNSHIFT_SPEEDS: list[tuple[str, int, str]] = [
    ("Gen5 (32GT)", 5, "32"),
    ("Gen4 (16GT)", 4, "16"),
    ("Gen3 (8GT)", 3, "8.0"),
]

_SPEED_CHANGE_SETTLE_S = 2.0


class SpeedDownshiftTestRecipe(Recipe):
    """Downshift through PCIe speeds and verify clean transitions."""

    @property
    def recipe_id(self) -> str:
        return "speed_downshift_test"

    @property
    def name(self) -> str:
        return "Speed Downshift Test"

    @property
    def description(self) -> str:
        return "Downshift through Gen5/Gen4/Gen3 and verify clean transitions"

    @property
    def category(self) -> RecipeCategory:
        return RecipeCategory.LINK_HEALTH

    @property
    def estimated_duration_s(self) -> int:
        return 30

    @property
    def parameters(self) -> list[RecipeParameter]:
        return [
            RecipeParameter(
                name="port_number",
                label="Port Number",
                description="Target port for speed downshift test",
                param_type="int",
                default=0,
                min_value=0,
                max_value=143,
            ),
            RecipeParameter(
                name="settle_time_s",
                label="Settle Time",
                description="Time to wait after retrain for link to settle",
                param_type="float",
                default=2.0,
                min_value=0.5,
                max_value=10.0,
                unit="s",
            ),
            RecipeParameter(
                name="check_aer",
                label="Check AER",
                description="Check AER errors after each speed change",
                param_type="bool",
                default=True,
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
        settle_time_s: float = float(kwargs.get("settle_time_s", 2.0))
        check_aer: bool = bool(kwargs.get("check_aer", True))
        device_id: str = str(kwargs.get("device_id", ""))
        params = {
            "port_number": port_number,
            "settle_time_s": settle_time_s,
            "check_aer": check_aer,
        }

        config = PcieConfigReader(dev, dev_key)

        # --- Step 1: Record baseline ---
        step = "Record baseline"
        yield self._make_running(step)
        t0 = time.monotonic()
        original_speed_code = 0
        baseline_width = 0
        try:
            link = config.get_link_status()
            baseline_speed = link.current_speed or ""
            baseline_width = link.current_width or 0
            original_speed_code = _speed_string_to_code(baseline_speed)
            if check_aer:
                config.clear_aer_errors()
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message=f"Baseline: x{baseline_width} @ {baseline_speed}",
                criticality=StepCriticality.MEDIUM,
                measured_values={
                    "baseline_speed": baseline_speed,
                    "baseline_width": baseline_width,
                    "original_speed_code": original_speed_code,
                },
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Baseline read failed: {exc}",
                criticality=StepCriticality.CRITICAL,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if result.status == StepStatus.ERROR:
            return self._make_summary(steps, start_time, params, device_id)

        try:
            # --- Downshift loop ---
            for speed_label, speed_code, expected_substr in _DOWNSHIFT_SPEEDS:
                if self._is_cancelled(cancel):
                    skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
                    yield skip
                    steps.append(skip)
                    break

                step = f"Downshift to {speed_label}"
                yield self._make_running(step)
                t0 = time.monotonic()

                try:
                    if check_aer:
                        config.clear_aer_errors()

                    config.set_target_link_speed(speed_code)
                    config.retrain_link()
                    time.sleep(settle_time_s)

                    # Verify negotiated speed
                    post_link = config.get_link_status()
                    actual_speed = post_link.current_speed or ""
                    actual_width = post_link.current_width or 0
                    speed_matched = expected_substr in actual_speed

                    measured: dict[str, object] = {
                        "target_speed": speed_label,
                        "actual_speed": actual_speed,
                        "actual_width": actual_width,
                        "speed_matched": speed_matched,
                    }

                    # Check AER if requested
                    aer_ok = True
                    if check_aer:
                        aer = config.get_aer_status()
                        if aer is not None:
                            measured["aer_uncorrectable"] = aer.uncorrectable.raw_value
                            measured["aer_correctable"] = aer.correctable.raw_value
                            if aer.uncorrectable.raw_value != 0:
                                aer_ok = False

                    dur = _elapsed_ms(t0)

                    if not speed_matched:
                        status = StepStatus.FAIL
                        msg = f"{speed_label}: speed mismatch -- got {actual_speed}"
                    elif not aer_ok:
                        status = StepStatus.FAIL
                        msg = f"{speed_label}: uncorrectable AER errors"
                    else:
                        status = StepStatus.PASS
                        msg = f"{speed_label}: x{actual_width} @ {actual_speed}"

                    result = self._make_result(
                        step,
                        status,
                        message=msg,
                        criticality=StepCriticality.HIGH,
                        measured_values=measured,
                        duration_ms=dur,
                        port_number=port_number,
                    )
                except Exception as exc:
                    dur = _elapsed_ms(t0)
                    result = self._make_result(
                        step,
                        StepStatus.ERROR,
                        message=f"{speed_label} downshift failed: {exc}",
                        criticality=StepCriticality.HIGH,
                        duration_ms=dur,
                        port_number=port_number,
                    )

                yield result
                steps.append(result)
        finally:
            # --- Restore max speed (always runs) ---
            if original_speed_code > 0:
                step = "Restore max speed"
                yield self._make_running(step)
                t0 = time.monotonic()
                try:
                    config.set_target_link_speed(original_speed_code)
                    config.retrain_link()
                    time.sleep(settle_time_s)
                    restored_link = config.get_link_status()
                    dur = _elapsed_ms(t0)
                    result = self._make_result(
                        step,
                        StepStatus.PASS,
                        message=(
                            f"Restored to x{restored_link.current_width} "
                            f"@ {restored_link.current_speed}"
                        ),
                        criticality=StepCriticality.MEDIUM,
                        measured_values={
                            "restored_speed": restored_link.current_speed,
                            "restored_width": restored_link.current_width,
                        },
                        duration_ms=dur,
                        port_number=port_number,
                    )
                except Exception as exc:
                    dur = _elapsed_ms(t0)
                    result = self._make_result(
                        step,
                        StepStatus.WARN,
                        message=f"Speed restore failed: {exc}",
                        criticality=StepCriticality.MEDIUM,
                        duration_ms=dur,
                        port_number=port_number,
                    )
                yield result
                steps.append(result)

        return self._make_summary(steps, start_time, params, device_id)


def _speed_string_to_code(speed_str: str) -> int:
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


def _elapsed_ms(t0: float) -> float:
    return round((time.monotonic() - t0) * 1000, 2)
