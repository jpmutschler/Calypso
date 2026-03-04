"""Datapath BIST test recipe -- run DP BIST and verify pass/fail."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.core.packet_exerciser import PacketExerciserEngine
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

_POLL_INTERVAL_S = 0.25


class DpBistTestRecipe(Recipe):
    """Run Datapath BIST on a port and verify zero failures."""

    @property
    def recipe_id(self) -> str:
        return "dp_bist_test"

    @property
    def name(self) -> str:
        return "Datapath BIST Test"

    @property
    def description(self) -> str:
        return "Run Datapath BIST TLP generation and verify pass/fail status"

    @property
    def category(self) -> RecipeCategory:
        return RecipeCategory.PERFORMANCE

    @property
    def estimated_duration_s(self) -> int:
        return 30

    @property
    def parameters(self) -> list[RecipeParameter]:
        return [
            RecipeParameter(
                name="port_number",
                label="Port Number",
                description="Port to run DP BIST on",
                param_type="int",
                default=0,
                min_value=0,
                max_value=143,
            ),
            RecipeParameter(
                name="duration_s",
                label="Duration",
                description="Maximum time to wait for BIST completion",
                param_type="float",
                default=5.0,
                min_value=1.0,
                max_value=60.0,
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
        duration_s: float = float(kwargs.get("duration_s", 5.0))
        params = {"port_number": port_number, "duration_s": duration_s}

        # --- Step 1: Start DP BIST ---
        step = "Start DP BIST"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            engine = PacketExerciserEngine(dev, dev_key, port_number)
            engine.start_dp_bist(loop_count=1, inner_loop_count=1)
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message="DP BIST started",
                criticality=StepCriticality.MEDIUM,
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Failed to start DP BIST: {exc}",
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

        # --- Step 2: Wait for completion ---
        step = "Wait for completion"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            deadline = time.monotonic() + duration_s
            bist_done = False
            bist_status = None

            while time.monotonic() < deadline:
                if self._is_cancelled(cancel):
                    break
                bist_status = engine.read_dp_bist_status()
                if bist_status.tx_done and bist_status.rx_done:
                    bist_done = True
                    break
                time.sleep(_POLL_INTERVAL_S)

            dur = round((time.monotonic() - t0) * 1000, 2)

            if not bist_done:
                result = self._make_result(
                    step,
                    StepStatus.WARN,
                    message=f"BIST did not complete within {duration_s}s",
                    criticality=StepCriticality.HIGH,
                    measured_values={
                        "tx_done": bist_status.tx_done if bist_status else False,
                        "rx_done": bist_status.rx_done if bist_status else False,
                    },
                    duration_ms=dur,
                    port_number=port_number,
                )
            else:
                result = self._make_result(
                    step,
                    StepStatus.PASS,
                    message="BIST completed",
                    criticality=StepCriticality.MEDIUM,
                    duration_ms=dur,
                    port_number=port_number,
                )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"BIST polling failed: {exc}",
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

        # --- Step 3: Read results ---
        step = "Read results"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            final_status = engine.read_dp_bist_status()
            dur = round((time.monotonic() - t0) * 1000, 2)

            if final_status.passed:
                status = StepStatus.PASS
                msg = "DP BIST passed -- zero failures"
            else:
                status = StepStatus.FAIL
                msg = "DP BIST failed"

            result = self._make_result(
                step,
                status,
                message=msg,
                criticality=StepCriticality.CRITICAL,
                measured_values={
                    "passed": final_status.passed,
                    "tx_done": final_status.tx_done,
                    "rx_done": final_status.rx_done,
                },
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Failed to read BIST results: {exc}",
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        # Stop BIST regardless of outcome
        try:
            engine.stop_dp_bist()
        except Exception:
            logger.warning("dp_bist_stop_failed", port=port_number)

        return self._make_summary(steps, start_time, params)
