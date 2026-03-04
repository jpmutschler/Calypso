"""Error recovery test recipe -- repeatedly retrain and check AER for clean recovery."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.core.ltssm_trace import LtssmTracer
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


class ErrorRecoveryTestRecipe(Recipe):
    """Repeatedly retrain a link and verify clean AER error recovery."""

    @property
    def recipe_id(self) -> str:
        return "error_recovery_test"

    @property
    def name(self) -> str:
        return "Error Recovery Test"

    @property
    def description(self) -> str:
        return "Repeatedly retrain and check AER to verify clean error recovery"

    @property
    def category(self) -> RecipeCategory:
        return RecipeCategory.ERROR_TESTING

    @property
    def estimated_duration_s(self) -> int:
        return 30

    @property
    def parameters(self) -> list[RecipeParameter]:
        return [
            RecipeParameter(
                name="port_number",
                label="Port Number",
                description="Target port for recovery testing",
                param_type="int",
                default=0,
                min_value=0,
                max_value=143,
            ),
            RecipeParameter(
                name="recovery_attempts",
                label="Recovery Attempts",
                description="Number of retrain/check cycles",
                param_type="int",
                default=3,
                min_value=1,
                max_value=10,
            ),
            RecipeParameter(
                name="settle_time_s",
                label="Settle Time",
                description="Time to wait after retrain for link to settle",
                param_type="float",
                default=1.0,
                min_value=0.5,
                max_value=10.0,
                unit="s",
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
        recovery_attempts: int = int(kwargs.get("recovery_attempts", 3))
        settle_time_s: float = float(kwargs.get("settle_time_s", 1.0))
        device_id: str = str(kwargs.get("device_id", ""))
        params = {
            "port_number": port_number,
            "recovery_attempts": recovery_attempts,
            "settle_time_s": settle_time_s,
        }

        config = PcieConfigReader(dev, dev_key)

        # --- Step 1: Record baseline ---
        step = "Record baseline"
        yield self._make_running(step)
        t0 = time.monotonic()
        baseline_speed = ""
        baseline_width = 0
        baseline_recovery_count = 0
        tracer: LtssmTracer | None = None
        try:
            link = config.get_link_status()
            baseline_speed = link.current_speed or ""
            baseline_width = link.current_width or 0
            config.clear_aer_errors()
            try:
                tracer = LtssmTracer(dev, dev_key, port_number)
                baseline_recovery_count, _ = tracer.read_recovery_count()
            except Exception:
                pass
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message=(
                    f"Baseline: x{baseline_width} @ {baseline_speed}, "
                    f"recoveries={baseline_recovery_count}"
                ),
                criticality=StepCriticality.MEDIUM,
                measured_values={
                    "baseline_speed": baseline_speed,
                    "baseline_width": baseline_width,
                    "baseline_recovery_count": baseline_recovery_count,
                },
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Failed to record baseline: {exc}",
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if result.status == StepStatus.ERROR:
            return self._make_summary(steps, start_time, params, device_id)

        # --- Recovery attempts loop ---
        transient_error_count = 0
        clean_count = 0
        degraded_count = 0

        for attempt in range(1, recovery_attempts + 1):
            if self._is_cancelled(cancel):
                skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
                yield skip
                steps.append(skip)
                return self._make_summary(steps, start_time, params, device_id)

            step = f"Recovery attempt {attempt}"
            yield self._make_running(step)
            t0 = time.monotonic()

            try:
                # Clear errors before retrain
                config.clear_aer_errors()

                # Read pre-retrain recovery count
                pre_recovery = 0
                if tracer is not None:
                    try:
                        pre_recovery, _ = tracer.read_recovery_count()
                    except Exception:
                        pass

                # Retrain the link
                config.retrain_link()

                # Allow link to settle
                time.sleep(settle_time_s)

                # Read post-retrain link status
                post_link = config.get_link_status()
                post_speed = post_link.current_speed or ""
                post_width = post_link.current_width or 0

                # Read post-retrain recovery count
                post_recovery = 0
                if tracer is not None:
                    try:
                        post_recovery, _ = tracer.read_recovery_count()
                    except Exception:
                        pass

                # Check AER
                aer = config.get_aer_status()
                dur = round((time.monotonic() - t0) * 1000, 2)

                measured: dict[str, object] = {
                    "attempt": attempt,
                    "post_speed": post_speed,
                    "post_width": post_width,
                    "recovery_delta": post_recovery - pre_recovery,
                }

                # Check for degradation
                speed_degraded = _speed_rank(post_speed) < _speed_rank(baseline_speed)
                width_degraded = post_width < baseline_width

                if speed_degraded or width_degraded:
                    status = StepStatus.FAIL
                    msg_parts = [f"Attempt {attempt}: link degraded"]
                    if speed_degraded:
                        msg_parts.append(f"speed {post_speed} < {baseline_speed}")
                    if width_degraded:
                        msg_parts.append(f"width x{post_width} < x{baseline_width}")
                    msg = " -- ".join(msg_parts)
                    degraded_count += 1
                    measured["speed_degraded"] = speed_degraded
                    measured["width_degraded"] = width_degraded
                elif aer is None:
                    status = StepStatus.WARN
                    msg = f"Attempt {attempt}: AER capability not found"
                    transient_error_count += 1
                else:
                    has_uncorr = aer.uncorrectable.raw_value != 0
                    has_corr = aer.correctable.raw_value != 0
                    measured["has_uncorrectable"] = has_uncorr
                    measured["has_correctable"] = has_corr

                    if has_uncorr:
                        status = StepStatus.FAIL
                        msg = f"Attempt {attempt}: uncorrectable errors after retrain"
                        transient_error_count += 1
                    elif has_corr:
                        status = StepStatus.WARN
                        msg = f"Attempt {attempt}: correctable errors after retrain (transient)"
                        transient_error_count += 1
                    else:
                        status = StepStatus.PASS
                        msg = f"Attempt {attempt}: clean recovery at x{post_width} @ {post_speed}"
                        clean_count += 1

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
                dur = round((time.monotonic() - t0) * 1000, 2)
                result = self._make_result(
                    step,
                    StepStatus.ERROR,
                    message=f"Attempt {attempt} failed: {exc}",
                    criticality=StepCriticality.HIGH,
                    duration_ms=dur,
                    port_number=port_number,
                )
                transient_error_count += 1

            yield result
            steps.append(result)

        # --- Final assessment ---
        step = "Final assessment"
        yield self._make_running(step)
        t0 = time.monotonic()

        if degraded_count > 0:
            status = StepStatus.FAIL
            msg = f"{degraded_count}/{recovery_attempts} attempt(s) caused link degradation"
        elif transient_error_count == 0:
            status = StepStatus.PASS
            msg = f"All {recovery_attempts} recovery attempt(s) clean"
        elif clean_count > 0:
            status = StepStatus.WARN
            msg = (
                f"{clean_count}/{recovery_attempts} clean, "
                f"{transient_error_count} with transient errors"
            )
        else:
            status = StepStatus.FAIL
            msg = f"All {recovery_attempts} attempt(s) had errors"

        dur = round((time.monotonic() - t0) * 1000, 2)
        result = self._make_result(
            step,
            status,
            message=msg,
            criticality=StepCriticality.CRITICAL,
            measured_values={
                "total_attempts": recovery_attempts,
                "clean_count": clean_count,
                "transient_error_count": transient_error_count,
                "degraded_count": degraded_count,
            },
            duration_ms=dur,
            port_number=port_number,
        )
        yield result
        steps.append(result)

        return self._make_summary(steps, start_time, params, device_id)


def _speed_rank(speed_str: str) -> int:
    """Map a PCIe speed string to a numeric rank for comparison."""
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
