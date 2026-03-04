"""PTrace capture recipe -- configure, capture, and analyze trace buffer entries."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.core.ptrace import PTraceEngine
from calypso.models.ptrace import (
    PTraceCaptureCfg,
    PTraceDirection,
    PTracePostTriggerCfg,
    PTraceTriggerCfg,
)
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


class PTraceCaptureRecipe(Recipe):
    """Capture PTrace traffic on a port and report buffer statistics."""

    @property
    def recipe_id(self) -> str:
        return "ptrace_capture"

    @property
    def name(self) -> str:
        return "PTrace Capture"

    @property
    def description(self) -> str:
        return "Configure PTrace, capture traffic, and analyze buffer entries"

    @property
    def category(self) -> RecipeCategory:
        return RecipeCategory.DEBUG

    @property
    def estimated_duration_s(self) -> int:
        return 15

    @property
    def parameters(self) -> list[RecipeParameter]:
        return [
            RecipeParameter(
                name="port_number",
                label="Port Number",
                description="Port to capture PTrace on",
                param_type="int",
                default=0,
                min_value=0,
                max_value=143,
            ),
            RecipeParameter(
                name="capture_duration_s",
                label="Capture Duration",
                description="How long to capture traffic",
                param_type="float",
                default=2.0,
                min_value=0.5,
                max_value=30.0,
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
        capture_duration_s: float = float(kwargs.get("capture_duration_s", 2.0))
        params = {"port_number": port_number, "capture_duration_s": capture_duration_s}

        direction = PTraceDirection.INGRESS

        # --- Step 1: Configure PTrace ---
        step = "Configure PTrace"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            engine = PTraceEngine(dev, dev_key, port_number)
            capture_cfg = PTraceCaptureCfg(
                direction=direction,
                port_number=port_number,
            )
            trigger_cfg = PTraceTriggerCfg()
            post_cfg = PTracePostTriggerCfg()

            engine.full_configure(
                direction=direction,
                capture=capture_cfg,
                trigger=trigger_cfg,
                post_trigger=post_cfg,
            )
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message="PTrace configured for ingress capture",
                criticality=StepCriticality.MEDIUM,
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"PTrace configuration failed: {exc}",
                criticality=StepCriticality.CRITICAL,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if result.status == StepStatus.ERROR:
            return self._make_summary(steps, start_time, params)

        if self._is_cancelled(cancel):
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return self._make_summary(steps, start_time, params)

        # --- Step 2: Capture traffic ---
        step = "Capture traffic"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            engine.start_capture(direction)

            elapsed = 0.0
            while elapsed < capture_duration_s:
                if self._is_cancelled(cancel):
                    break
                chunk = min(0.5, capture_duration_s - elapsed)
                time.sleep(chunk)
                elapsed += chunk

            engine.stop_capture(direction)
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message=f"Captured for {elapsed:.1f}s",
                criticality=StepCriticality.MEDIUM,
                measured_values={"actual_duration_s": round(elapsed, 1)},
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Capture failed: {exc}",
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if result.status == StepStatus.ERROR:
            return self._make_summary(steps, start_time, params)

        if self._is_cancelled(cancel):
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return self._make_summary(steps, start_time, params)

        # --- Step 3: Read buffer ---
        step = "Read buffer"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            buffer_result = engine.read_buffer(direction)
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message=f"Read {buffer_result.total_rows_read} buffer row(s)",
                criticality=StepCriticality.MEDIUM,
                measured_values={
                    "total_rows_read": buffer_result.total_rows_read,
                    "triggered": buffer_result.triggered,
                    "tbuf_wrapped": buffer_result.tbuf_wrapped,
                },
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Buffer read failed: {exc}",
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if result.status == StepStatus.ERROR:
            return self._make_summary(steps, start_time, params)

        # --- Step 4: Analyze entries ---
        step = "Analyze entries"
        yield self._make_running(step)
        t0 = time.monotonic()

        entry_count = buffer_result.total_rows_read
        dur = round((time.monotonic() - t0) * 1000, 2)
        result = self._make_result(
            step,
            StepStatus.PASS,
            message=f"Captured {entry_count} trace entries",
            criticality=StepCriticality.INFO,
            measured_values={
                "entry_count": entry_count,
                "triggered": buffer_result.triggered,
                "wrapped": buffer_result.tbuf_wrapped,
                "trigger_row_addr": buffer_result.trigger_row_addr,
            },
            duration_ms=dur,
            port_number=port_number,
        )
        yield result
        steps.append(result)

        return self._make_summary(steps, start_time, params)
