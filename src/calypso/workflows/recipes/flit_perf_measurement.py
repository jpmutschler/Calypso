"""Flit Performance Measurement recipe -- track flit throughput and LTSSM counters."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.core.pcie_config import PcieConfigReader
from calypso.models.pcie_config import FlitPerfConfig
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

_SOAK_POLL_INTERVAL_S = 1.0


class FlitPerfMeasurementRecipe(Recipe):
    """Track flit throughput and LTSSM state dwell times at 64GT/s."""

    @property
    def recipe_id(self) -> str:
        return "flit_perf_measurement"

    @property
    def name(self) -> str:
        return "Flit Performance Measurement"

    @property
    def description(self) -> str:
        return "Track flit throughput and LTSSM counters for Gen6 64GT/s links"

    @property
    def category(self) -> RecipeCategory:
        return RecipeCategory.PERFORMANCE

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
                description="Target port for flit performance measurement",
                param_type="int",
                default=0,
                min_value=0,
                max_value=143,
            ),
            RecipeParameter(
                name="duration_s",
                label="Duration",
                description="Measurement duration in seconds",
                param_type="float",
                default=10.0,
                min_value=1.0,
                max_value=120.0,
                unit="s",
            ),
            RecipeParameter(
                name="flit_type",
                label="Flit Type",
                description="Flit type filter (0=all, 1-3=specific)",
                param_type="int",
                default=0,
                min_value=0,
                max_value=3,
            ),
            RecipeParameter(
                name="response_type",
                label="Response Type",
                description="Response type filter (0-7)",
                param_type="int",
                default=0,
                min_value=0,
                max_value=7,
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
        duration_s: float = float(kwargs.get("duration_s", 10.0))
        flit_type: int = int(kwargs.get("flit_type", 0))
        response_type: int = int(kwargs.get("response_type", 0))
        device_id: str = str(kwargs.get("device_id", ""))
        params = {
            "port_number": port_number,
            "duration_s": duration_s,
            "flit_type": flit_type,
            "response_type": response_type,
        }

        reader = PcieConfigReader(dev, dev_key)

        # --- Step 1: Verify Flit Perf Measurement capability ---
        step = "Verify Flit Perf Measurement capability"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            perf_status = reader.get_flit_perf_status()
            dur = _elapsed_ms(t0)
            if perf_status is None:
                result = self._make_result(
                    step,
                    StepStatus.SKIP,
                    message="Flit Performance Measurement capability not present",
                    criticality=StepCriticality.CRITICAL,
                    duration_ms=dur,
                    port_number=port_number,
                )
                yield result
                steps.append(result)
                return self._make_summary(steps, start_time, params, device_id)

            result = self._make_result(
                step,
                StepStatus.PASS,
                message="Flit Perf Measurement capability present",
                criticality=StepCriticality.MEDIUM,
                measured_values={
                    "cap_offset": perf_status.cap_offset,
                    "ltssm_tracking_count": perf_status.ltssm_tracking_count,
                    "interrupt_vector": perf_status.interrupt_vector,
                },
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
            return self._make_summary(steps, start_time, params, device_id)

        # --- Step 2: Read capability register ---
        step = "Read capability register"
        yield self._make_running(step)
        t0 = time.monotonic()
        dur = _elapsed_ms(t0)
        result = self._make_result(
            step,
            StepStatus.PASS,
            message=(
                f"LTSSM tracking count support: {perf_status.ltssm_tracking_count}, "
                f"raw capability: 0x{perf_status.raw_capability:08X}"
            ),
            criticality=StepCriticality.INFO,
            measured_values={
                "ltssm_tracking_count": perf_status.ltssm_tracking_count,
                "raw_capability": perf_status.raw_capability,
                "raw_control": perf_status.raw_control,
                "raw_status": perf_status.raw_status,
            },
            duration_ms=dur,
            port_number=port_number,
        )
        yield result
        steps.append(result)

        if self._is_cancelled(cancel):
            return self._make_summary(steps, start_time, params, device_id)

        # --- Step 3: Start measurement ---
        step = "Start measurement"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            config = FlitPerfConfig(
                flit_type=flit_type,
                response_type=response_type,
            )
            reader.start_flit_perf_measurement(config)
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message=(
                    f"Measurement started (flit_type={flit_type}, response_type={response_type})"
                ),
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Failed to start measurement: {exc}",
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
            step = "Soak"
            yield self._make_running(step)
            t0 = time.monotonic()
            elapsed = 0.0
            while elapsed < duration_s:
                if self._is_cancelled(cancel):
                    break
                sleep_time = min(_SOAK_POLL_INTERVAL_S, duration_s - elapsed)
                time.sleep(sleep_time)
                elapsed = time.monotonic() - t0

            actual_soak = time.monotonic() - t0
            dur = _elapsed_ms(t0)
            cancelled = self._is_cancelled(cancel)
            result = self._make_result(
                step,
                StepStatus.WARN if cancelled else StepStatus.PASS,
                message=(
                    f"Soaked {actual_soak:.1f}s" + (" (cancelled early)" if cancelled else "")
                ),
                criticality=StepCriticality.LOW,
                measured_values={"actual_soak_s": round(actual_soak, 2)},
                duration_ms=dur,
                port_number=port_number,
            )
            yield result
            steps.append(result)

            # --- Step 5: Read results ---
            step = "Read results"
            yield self._make_running(step)
            t0 = time.monotonic()
            flits_tracked = 0
            ltssm_statuses = []
            try:
                post_status = reader.get_flit_perf_status()
                dur = _elapsed_ms(t0)
                if post_status is None:
                    result = self._make_result(
                        step,
                        StepStatus.ERROR,
                        message="Capability disappeared during measurement",
                        criticality=StepCriticality.CRITICAL,
                        duration_ms=dur,
                        port_number=port_number,
                    )
                else:
                    flits_tracked = post_status.flits_tracked
                    ltssm_statuses = post_status.ltssm_statuses
                    measured: dict[str, object] = {
                        "tracking_status": post_status.tracking_status,
                        "flits_tracked": flits_tracked,
                        "ltssm_counter": post_status.ltssm_counter,
                        "interrupt_generated": post_status.interrupt_generated,
                    }
                    for idx, ls in enumerate(ltssm_statuses):
                        measured[f"ltssm_{idx}_tracking_status"] = ls.tracking_status
                        measured[f"ltssm_{idx}_counter"] = ls.counter
                        measured[f"ltssm_{idx}_tracking_count"] = ls.tracking_count

                    result = self._make_result(
                        step,
                        StepStatus.PASS,
                        message=(
                            f"Flits tracked: {flits_tracked}, "
                            f"LTSSM registers: {len(ltssm_statuses)}"
                        ),
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
                    message=f"Failed to read results: {exc}",
                    criticality=StepCriticality.HIGH,
                    duration_ms=dur,
                    port_number=port_number,
                )
            yield result
            steps.append(result)
        finally:
            # --- Step 6: Stop measurement (always runs) ---
            step = "Stop measurement"
            yield self._make_running(step)
            t0 = time.monotonic()
            try:
                reader.stop_flit_perf_measurement()
                dur = _elapsed_ms(t0)
                result = self._make_result(
                    step,
                    StepStatus.PASS,
                    message="Measurement stopped",
                    criticality=StepCriticality.MEDIUM,
                    duration_ms=dur,
                    port_number=port_number,
                )
            except Exception as exc:
                dur = _elapsed_ms(t0)
                result = self._make_result(
                    step,
                    StepStatus.WARN,
                    message=f"Stop measurement failed: {exc}",
                    criticality=StepCriticality.MEDIUM,
                    duration_ms=dur,
                    port_number=port_number,
                )
            yield result
            steps.append(result)

        # --- Step 7: Analyze ---
        step = "Analyze"
        yield self._make_running(step)
        t0 = time.monotonic()

        if flits_tracked > 0:
            analyze_status = StepStatus.PASS
            msg = f"Measurement successful: {flits_tracked} flits tracked"
        elif flits_tracked == 0 and not cancelled:
            analyze_status = StepStatus.WARN
            msg = "Zero flits tracked -- link may not be active at 64GT/s"
        else:
            analyze_status = StepStatus.WARN
            msg = "Measurement cancelled early, results may be incomplete"

        ltssm_summary: dict[str, object] = {
            "flits_tracked": flits_tracked,
            "ltssm_register_count": len(ltssm_statuses),
        }
        for idx, ls in enumerate(ltssm_statuses):
            ltssm_summary[f"ltssm_{idx}_counter"] = ls.counter

        dur = _elapsed_ms(t0)
        result = self._make_result(
            step,
            analyze_status,
            message=msg,
            criticality=StepCriticality.CRITICAL,
            measured_values=ltssm_summary,
            duration_ms=dur,
            port_number=port_number,
        )
        yield result
        steps.append(result)

        return self._make_summary(steps, start_time, params, device_id)


def _elapsed_ms(t0: float) -> float:
    return round((time.monotonic() - t0) * 1000, 2)
