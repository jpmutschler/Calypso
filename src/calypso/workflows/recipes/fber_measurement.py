"""FBER Measurement recipe -- measure Flit Bit Error Rate per lane on Gen6 links."""

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

# Per-lane FBER thresholds
_FBER_WARN_THRESHOLD = 100
_FBER_FAIL_THRESHOLD = 10000


class FberMeasurementRecipe(Recipe):
    """Measure Flit Bit Error Rate per lane for Gen6 64GT/s links."""

    @property
    def recipe_id(self) -> str:
        return "fber_measurement"

    @property
    def name(self) -> str:
        return "FBER Measurement"

    @property
    def description(self) -> str:
        return "Measure Flit Bit Error Rate per lane on Gen6 64GT/s links"

    @property
    def category(self) -> RecipeCategory:
        return RecipeCategory.SIGNAL_INTEGRITY

    @property
    def requires_link_up(self) -> bool:
        return True

    @property
    def estimated_duration_s(self) -> int:
        return 60

    @property
    def parameters(self) -> list[RecipeParameter]:
        return [
            RecipeParameter(
                name="port_number",
                label="Port Number",
                description="Target port for FBER measurement",
                param_type="int",
                default=0,
                min_value=0,
                max_value=143,
            ),
            RecipeParameter(
                name="duration_s",
                label="Measurement Duration",
                description="How long to run the FBER measurement",
                param_type="float",
                default=30.0,
                min_value=5.0,
                max_value=600.0,
                unit="s",
            ),
            RecipeParameter(
                name="granularity",
                label="Granularity",
                description="FBER measurement granularity (0-3)",
                param_type="int",
                default=0,
                min_value=0,
                max_value=3,
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
        duration_s: float = float(kwargs.get("duration_s", 30.0))
        granularity: int = int(kwargs.get("granularity", 0))
        device_id: str = str(kwargs.get("device_id", ""))

        params = {
            "port_number": port_number,
            "duration_s": duration_s,
            "granularity": granularity,
        }

        reader = PcieConfigReader(dev, dev_key)

        # --- Step 1: Verify Flit Logging capability ---
        step = "Verify Flit Logging capability"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            flit_status = reader.get_flit_logging_status()
            dur = _elapsed_ms(t0)
            if flit_status is None:
                result = self._make_result(
                    step,
                    StepStatus.SKIP,
                    message="Flit Logging capability not present (not Gen6?)",
                    criticality=StepCriticality.HIGH,
                    duration_ms=dur,
                    port_number=port_number,
                )
                yield result
                steps.append(result)
                return self._make_summary(steps, start_time, params, device_id)

            result = self._make_result(
                step,
                StepStatus.PASS,
                message="Flit Logging capability present",
                criticality=StepCriticality.MEDIUM,
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Capability check failed: {exc}",
                criticality=StepCriticality.CRITICAL,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if result.status == StepStatus.ERROR:
            return self._make_summary(steps, start_time, params, device_id)

        if self._is_cancelled(cancel):
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return self._make_summary(steps, start_time, params, device_id)

        # --- Step 2: Clear FBER counters ---
        step = "Clear FBER counters"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            reader.clear_fber_counters()
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message="FBER counters cleared",
                criticality=StepCriticality.MEDIUM,
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Failed to clear counters: {exc}",
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if result.status == StepStatus.ERROR:
            return self._make_summary(steps, start_time, params, device_id)

        if self._is_cancelled(cancel):
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return self._make_summary(steps, start_time, params, device_id)

        # --- Step 3: Start FBER measurement ---
        step = "Start FBER measurement"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            reader.start_fber_measurement(granularity)
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message=f"FBER measurement started (granularity={granularity})",
                criticality=StepCriticality.MEDIUM,
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Failed to start FBER: {exc}",
                criticality=StepCriticality.CRITICAL,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if result.status == StepStatus.ERROR:
            return self._make_summary(steps, start_time, params, device_id)

        try:
            # --- Step 4: Soak ---
            step = f"Soak for {duration_s}s"
            yield self._make_running(step)
            t0 = time.monotonic()
            elapsed = 0.0
            while elapsed < duration_s:
                if self._is_cancelled(cancel):
                    break
                chunk = min(1.0, duration_s - elapsed)
                time.sleep(chunk)
                elapsed += chunk

            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message=f"Soaked for {elapsed:.1f}s",
                criticality=StepCriticality.INFO,
                measured_values={"actual_duration_s": round(elapsed, 1)},
                duration_ms=dur,
                port_number=port_number,
            )
            yield result
            steps.append(result)

            # --- Step 6: Read FBER results ---
            step = "Read FBER results"
            yield self._make_running(step)
            t0 = time.monotonic()
            try:
                fber = reader.get_fber_status()
                dur = _elapsed_ms(t0)
                if fber is None:
                    result = self._make_result(
                        step,
                        StepStatus.ERROR,
                        message="FBER status not available",
                        criticality=StepCriticality.HIGH,
                        duration_ms=dur,
                        port_number=port_number,
                    )
                    yield result
                    steps.append(result)
                    return self._make_summary(steps, start_time, params, device_id)

                result = self._make_result(
                    step,
                    StepStatus.PASS,
                    message=f"FBER results: flit_counter={fber.flit_counter}",
                    criticality=StepCriticality.MEDIUM,
                    measured_values={
                        "flit_counter": fber.flit_counter,
                        "lane_counters": fber.lane_counters,
                    },
                    duration_ms=dur,
                    port_number=port_number,
                )
            except Exception as exc:
                dur = _elapsed_ms(t0)
                result = self._make_result(
                    step,
                    StepStatus.ERROR,
                    message=f"Failed to read FBER results: {exc}",
                    criticality=StepCriticality.HIGH,
                    duration_ms=dur,
                    port_number=port_number,
                )
            yield result
            steps.append(result)

            if result.status == StepStatus.ERROR:
                return self._make_summary(steps, start_time, params, device_id)
        finally:
            # --- Step 5: Stop FBER measurement (always runs) ---
            step = "Stop FBER measurement"
            yield self._make_running(step)
            t0 = time.monotonic()
            try:
                reader.stop_fber_measurement()
                dur = _elapsed_ms(t0)
                result = self._make_result(
                    step,
                    StepStatus.PASS,
                    message="FBER measurement stopped",
                    criticality=StepCriticality.MEDIUM,
                    duration_ms=dur,
                    port_number=port_number,
                )
            except Exception as exc:
                dur = _elapsed_ms(t0)
                result = self._make_result(
                    step,
                    StepStatus.WARN,
                    message=f"FBER stop issue: {exc}",
                    criticality=StepCriticality.MEDIUM,
                    duration_ms=dur,
                    port_number=port_number,
                )
            yield result
            steps.append(result)

        # --- Step 7: Analyze per-lane results ---
        step = "Analyze per-lane results"
        yield self._make_running(step)
        t0 = time.monotonic()

        lane_counters = fber.lane_counters
        total_errors = sum(lane_counters)
        lanes_with_errors = [i for i, c in enumerate(lane_counters) if c > 0]

        lane_details: list[dict[str, object]] = []
        worst_status = StepStatus.PASS

        for idx, count in enumerate(lane_counters):
            lane_info: dict[str, object] = {"lane": idx, "error_count": count}

            if count >= _FBER_FAIL_THRESHOLD:
                lane_info["status"] = "fail"
                worst_status = StepStatus.FAIL
            elif count >= _FBER_WARN_THRESHOLD:
                lane_info["status"] = "warn"
                if worst_status != StepStatus.FAIL:
                    worst_status = StepStatus.WARN
            elif count > 0:
                lane_info["status"] = "marginal"
                if worst_status == StepStatus.PASS:
                    worst_status = StepStatus.WARN
            else:
                lane_info["status"] = "pass"

            # Relative distribution
            if total_errors > 0:
                lane_info["error_pct"] = round(count / total_errors * 100, 1)

            lane_details.append(lane_info)

        if total_errors == 0:
            msg = "All lanes zero FBER errors"
        else:
            msg = f"{total_errors} total errors across {len(lanes_with_errors)} lane(s)"

        dur = _elapsed_ms(t0)
        result = self._make_result(
            step,
            worst_status,
            message=msg,
            criticality=StepCriticality.CRITICAL,
            measured_values={
                "total_errors": total_errors,
                "lanes_with_errors": len(lanes_with_errors),
                "flit_counter": fber.flit_counter,
                "lanes": lane_details,
            },
            duration_ms=dur,
            port_number=port_number,
        )
        yield result
        steps.append(result)

        return self._make_summary(steps, start_time, params, device_id)


def _elapsed_ms(t0: float) -> float:
    return round((time.monotonic() - t0) * 1000, 2)
