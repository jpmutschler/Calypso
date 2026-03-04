"""Error recovery test recipe -- repeatedly retrain and check AER for clean recovery."""

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

_POST_RETRAIN_SETTLE_S = 1.0


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
        params = {"port_number": port_number, "recovery_attempts": recovery_attempts}

        # --- Step 1: Clear AER errors ---
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
                message="AER errors cleared before recovery test",
                criticality=StepCriticality.MEDIUM,
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Failed to clear AER: {exc}",
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if result.status == StepStatus.ERROR:
            return self._make_summary(steps, start_time, params)

        # --- Recovery attempts loop ---
        transient_error_count = 0
        clean_count = 0

        for attempt in range(1, recovery_attempts + 1):
            if self._is_cancelled(cancel):
                skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
                yield skip
                steps.append(skip)
                return self._make_summary(steps, start_time, params)

            step = f"Recovery attempt {attempt}"
            yield self._make_running(step)
            t0 = time.monotonic()

            try:
                # Clear errors before retrain
                config.clear_aer_errors()

                # Retrain the link
                config.retrain_link()

                # Allow link to settle
                time.sleep(_POST_RETRAIN_SETTLE_S)

                # Check AER
                aer = config.get_aer_status()
                dur = round((time.monotonic() - t0) * 1000, 2)

                if aer is None:
                    result = self._make_result(
                        step,
                        StepStatus.WARN,
                        message=f"Attempt {attempt}: AER capability not found",
                        criticality=StepCriticality.MEDIUM,
                        duration_ms=dur,
                        port_number=port_number,
                    )
                    transient_error_count += 1
                else:
                    has_uncorr = aer.uncorrectable.raw_value != 0
                    has_corr = aer.correctable.raw_value != 0

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
                        msg = f"Attempt {attempt}: clean recovery"
                        clean_count += 1

                    result = self._make_result(
                        step,
                        status,
                        message=msg,
                        criticality=StepCriticality.HIGH,
                        measured_values={
                            "attempt": attempt,
                            "has_uncorrectable": has_uncorr,
                            "has_correctable": has_corr,
                        },
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

        if transient_error_count == 0:
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
            },
            duration_ms=dur,
            port_number=port_number,
        )
        yield result
        steps.append(result)

        return self._make_summary(steps, start_time, params)
