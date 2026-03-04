"""Link training debug recipe -- retrain a port and observe LTSSM/AER behaviour."""

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

_POLL_INTERVAL_MS = 50


class LinkTrainingDebugRecipe(Recipe):
    """Force a link retrain and capture LTSSM transitions with AER checks."""

    @property
    def recipe_id(self) -> str:
        return "link_training_debug"

    @property
    def name(self) -> str:
        return "Link Training Debug"

    @property
    def description(self) -> str:
        return "Retrain a port link and monitor LTSSM transitions with AER error checks"

    @property
    def category(self) -> RecipeCategory:
        return RecipeCategory.LINK_HEALTH

    @property
    def estimated_duration_s(self) -> int:
        return 60

    @property
    def parameters(self) -> list[RecipeParameter]:
        return [
            RecipeParameter(
                name="port_number",
                label="Port Number",
                description="Target port to retrain",
                param_type="int",
                default=0,
                min_value=0,
                max_value=143,
            ),
            RecipeParameter(
                name="timeout_s",
                label="Timeout",
                description="Maximum time to monitor LTSSM after retrain",
                param_type="float",
                default=10.0,
                min_value=2.0,
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
        timeout_s: float = float(kwargs.get("timeout_s", 10.0))

        # --- Step 1: Read initial LTSSM ---
        step = "Read initial LTSSM"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            tracer = LtssmTracer(dev, dev_key, port_number)
            snapshot = tracer.get_snapshot()
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message=f"LTSSM state: {snapshot.ltssm_state_name}",
                criticality=StepCriticality.INFO,
                measured_values={
                    "ltssm_state": snapshot.ltssm_state_name,
                    "recovery_count": snapshot.recovery_count,
                },
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Failed to read LTSSM: {exc}",
                criticality=StepCriticality.CRITICAL,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if result.status == StepStatus.ERROR:
            return self._make_summary(
                steps, start_time, {"port_number": port_number, "timeout_s": timeout_s}
            )

        if self._is_cancelled(cancel):
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return self._make_summary(
                steps, start_time, {"port_number": port_number, "timeout_s": timeout_s}
            )

        # --- Step 2: Clear AER errors ---
        step = "Clear AER errors"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            config = PcieConfigReader(dev, dev_key)
            config.clear_aer_errors()
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message="AER errors cleared",
                criticality=StepCriticality.MEDIUM,
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.WARN,
                message=f"Could not clear AER: {exc}",
                criticality=StepCriticality.MEDIUM,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if self._is_cancelled(cancel):
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return self._make_summary(
                steps, start_time, {"port_number": port_number, "timeout_s": timeout_s}
            )

        # --- Step 3: Retrain link ---
        step = "Retrain link"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            config.retrain_link()
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message="Link retrain initiated",
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Retrain failed: {exc}",
                criticality=StepCriticality.CRITICAL,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if result.status == StepStatus.ERROR:
            return self._make_summary(
                steps, start_time, {"port_number": port_number, "timeout_s": timeout_s}
            )

        if self._is_cancelled(cancel):
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return self._make_summary(
                steps, start_time, {"port_number": port_number, "timeout_s": timeout_s}
            )

        # --- Step 4: Monitor LTSSM transitions ---
        step = "Monitor LTSSM transitions"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            transitions: list[dict[str, object]] = []
            prev_state = ""
            deadline = time.monotonic() + timeout_s

            while time.monotonic() < deadline:
                if self._is_cancelled(cancel):
                    break
                snap = tracer.get_snapshot()
                if snap.ltssm_state_name != prev_state:
                    transitions.append(
                        {
                            "state": snap.ltssm_state_name,
                            "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
                            "recovery_count": snap.recovery_count,
                        }
                    )
                    prev_state = snap.ltssm_state_name
                time.sleep(_POLL_INTERVAL_MS / 1000)

            dur = round((time.monotonic() - t0) * 1000, 2)
            status = StepStatus.PASS if transitions else StepStatus.WARN
            result = self._make_result(
                step,
                status,
                message=f"Observed {len(transitions)} LTSSM transition(s)",
                criticality=StepCriticality.HIGH,
                measured_values={
                    "transition_count": len(transitions),
                    "final_state": prev_state,
                    "transitions": transitions,
                },
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Monitoring failed: {exc}",
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if self._is_cancelled(cancel):
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return self._make_summary(
                steps, start_time, {"port_number": port_number, "timeout_s": timeout_s}
            )

        # --- Step 5: Check post-retrain AER ---
        step = "Check post-retrain AER"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            aer = config.get_aer_status()
            dur = round((time.monotonic() - t0) * 1000, 2)
            if aer is None:
                result = self._make_result(
                    step,
                    StepStatus.WARN,
                    message="AER capability not found",
                    criticality=StepCriticality.MEDIUM,
                    duration_ms=dur,
                    port_number=port_number,
                )
            else:
                has_uncorr = aer.uncorrectable.raw_value != 0
                has_corr = aer.correctable.raw_value != 0
                if has_uncorr:
                    status = StepStatus.FAIL
                    msg = "Uncorrectable AER errors detected after retrain"
                elif has_corr:
                    status = StepStatus.WARN
                    msg = "Correctable AER errors detected after retrain"
                else:
                    status = StepStatus.PASS
                    msg = "No AER errors after retrain"

                result = self._make_result(
                    step,
                    status,
                    message=msg,
                    criticality=StepCriticality.HIGH,
                    measured_values={
                        "uncorrectable_raw": aer.uncorrectable.raw_value,
                        "correctable_raw": aer.correctable.raw_value,
                        "first_error_pointer": aer.first_error_pointer,
                    },
                    duration_ms=dur,
                    port_number=port_number,
                )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"AER check failed: {exc}",
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        return self._make_summary(
            steps, start_time, {"port_number": port_number, "timeout_s": timeout_s}
        )
