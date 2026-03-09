"""LTSSM monitoring recipe -- continuously poll LTSSM state and detect transitions."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.core.ltssm_trace import LtssmTracer
from calypso.models.ltssm import ltssm_state_name
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
from calypso.workflows.thresholds import LTSSM_RECOVERY_WARN

logger = get_logger(__name__)


class LtssmMonitorRecipe(Recipe):
    """Continuously poll LTSSM state and report transitions and recovery events."""

    @property
    def recipe_id(self) -> str:
        return "ltssm_monitor"

    @property
    def name(self) -> str:
        return "LTSSM Monitor"

    @property
    def description(self) -> str:
        return "Poll LTSSM state over a duration and detect state transitions"

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
                description="Target port to monitor",
                param_type="int",
                default=0,
                min_value=0,
                max_value=143,
            ),
            RecipeParameter(
                name="duration_s",
                label="Duration",
                description="How long to monitor",
                param_type="float",
                default=10.0,
                min_value=1.0,
                max_value=120.0,
                unit="s",
            ),
            RecipeParameter(
                name="poll_interval_ms",
                label="Poll Interval",
                description="Time between LTSSM polls",
                param_type="int",
                default=100,
                min_value=50,
                max_value=1000,
                unit="ms",
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
        poll_interval_ms: int = int(kwargs.get("poll_interval_ms", 100))
        device_id: str = str(kwargs.get("device_id", ""))

        params = {
            "port_number": port_number,
            "duration_s": duration_s,
            "poll_interval_ms": poll_interval_ms,
        }

        # --- Step 1: Start monitoring ---
        step = "Start monitoring"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            tracer = LtssmTracer(dev, dev_key, port_number)
            initial = tracer.get_snapshot()
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message=f"Initial state: {initial.ltssm_state_name}",
                criticality=StepCriticality.INFO,
                measured_values={
                    "initial_state": initial.ltssm_state_name,
                    "initial_recovery_count": initial.recovery_count,
                },
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Failed to start monitoring: {exc}",
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

        # --- Step 2: Poll samples ---
        step = "Poll LTSSM samples"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            transitions: list[dict[str, object]] = []
            prev_state = initial.ltssm_state_name
            sample_count = 0
            recovery_total = 0
            deadline = time.monotonic() + duration_s
            poll_s = poll_interval_ms / 1000

            while time.monotonic() < deadline:
                if self._is_cancelled(cancel):
                    break
                snap = tracer.get_snapshot()
                sample_count += 1
                recovery_total = snap.recovery_count

                if snap.ltssm_state_name != prev_state:
                    # Use ltssm_state_name() for full 12-bit sub-state decode
                    # (e.g. "Recovery.RcvrLock") via the snapshot's raw code.
                    sub_state = ltssm_state_name(snap.ltssm_state)
                    transitions.append(
                        {
                            "from": prev_state,
                            "to": snap.ltssm_state_name,
                            "sub_state": sub_state,
                            "ltssm_code": f"0x{snap.ltssm_state:03X}",
                            "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
                            "recovery_count": snap.recovery_count,
                        }
                    )
                    prev_state = snap.ltssm_state_name

                time.sleep(poll_s)

            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message=f"Collected {sample_count} samples, {len(transitions)} transition(s)",
                criticality=StepCriticality.MEDIUM,
                measured_values={
                    "sample_count": sample_count,
                    "transition_count": len(transitions),
                    "final_state": prev_state,
                    "recovery_count": recovery_total,
                },
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Polling failed: {exc}",
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if result.status == StepStatus.ERROR:
            return self._make_summary(steps, start_time, params, device_id)

        # --- Step 3: Analyze transitions ---
        step = "Analyze transitions"
        yield self._make_running(step)
        t0 = time.monotonic()

        transition_count = len(transitions)
        has_frequent_recovery = recovery_total >= LTSSM_RECOVERY_WARN

        if has_frequent_recovery:
            status = StepStatus.WARN
            msg = (
                f"Frequent recovery detected: {recovery_total} recovery entries over {duration_s}s"
            )
        elif transition_count > 0:
            status = StepStatus.PASS
            msg = f"Link stable with {transition_count} expected transition(s)"
        else:
            status = StepStatus.PASS
            msg = "Link remained stable with no transitions"

        dur = round((time.monotonic() - t0) * 1000, 2)
        result = self._make_result(
            step,
            status,
            message=msg,
            criticality=StepCriticality.HIGH,
            measured_values={
                "transition_count": transition_count,
                "recovery_count": recovery_total,
                "transitions": transitions,
            },
            duration_ms=dur,
            port_number=port_number,
        )
        yield result
        steps.append(result)

        return self._make_summary(steps, start_time, params, device_id)
