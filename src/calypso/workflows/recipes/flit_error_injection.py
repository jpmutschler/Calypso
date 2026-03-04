"""Flit Error Injection recipe -- inject flit errors and verify detection."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.core.pcie_config import PcieConfigReader
from calypso.models.pcie_config import FlitErrorInjectionConfig
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

_INJECTION_SETTLE_S = 2.0


class FlitErrorInjectionRecipe(Recipe):
    """Inject Flit errors and verify they appear in the Flit Error Log."""

    @property
    def recipe_id(self) -> str:
        return "flit_error_injection"

    @property
    def name(self) -> str:
        return "Flit Error Injection"

    @property
    def description(self) -> str:
        return "Inject Flit errors and verify detection via Flit Error Log"

    @property
    def category(self) -> RecipeCategory:
        return RecipeCategory.ERROR_TESTING

    @property
    def estimated_duration_s(self) -> int:
        return 15

    @property
    def parameters(self) -> list[RecipeParameter]:
        return [
            RecipeParameter(
                name="port_number",
                label="Port Number",
                description="Target port for error injection",
                param_type="int",
                default=0,
                min_value=0,
                max_value=143,
            ),
            RecipeParameter(
                name="num_errors",
                label="Number of Errors",
                description="Number of Flit errors to inject (1-31)",
                param_type="int",
                default=1,
                min_value=1,
                max_value=31,
            ),
            RecipeParameter(
                name="error_type",
                label="Error Type",
                description="Flit error type code (0-3)",
                param_type="int",
                default=0,
                min_value=0,
                max_value=3,
            ),
            RecipeParameter(
                name="inject_tx",
                label="Inject TX",
                description="Inject errors on TX path",
                param_type="bool",
                default=True,
            ),
            RecipeParameter(
                name="inject_rx",
                label="Inject RX",
                description="Inject errors on RX path",
                param_type="bool",
                default=False,
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
        num_errors: int = int(kwargs.get("num_errors", 1))
        error_type: int = int(kwargs.get("error_type", 0))
        inject_tx: bool = bool(kwargs.get("inject_tx", True))
        inject_rx: bool = bool(kwargs.get("inject_rx", False))
        device_id: str = str(kwargs.get("device_id", ""))

        params = {
            "port_number": port_number,
            "num_errors": num_errors,
            "error_type": error_type,
            "inject_tx": inject_tx,
            "inject_rx": inject_rx,
        }

        reader = PcieConfigReader(dev, dev_key)

        # --- Step 1: Verify Flit Error Injection capability ---
        step = "Verify Flit Error Injection capability"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            inj_status = reader.get_flit_error_injection_status()
            dur = _elapsed_ms(t0)
            if inj_status is None:
                result = self._make_result(
                    step,
                    StepStatus.SKIP,
                    message="Flit Error Injection capability not present",
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
                message="Flit Error Injection capability present",
                criticality=StepCriticality.MEDIUM,
                measured_values={"cap_offset": inj_status.cap_offset},
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

        # --- Step 2: Establish clean baseline ---
        step = "Establish clean baseline"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            # Clear Flit Error Log
            reader.read_all_flit_error_log_entries(max_entries=256)
            # Clear FBER counters
            reader.clear_fber_counters()
            # Clear AER
            reader.clear_aer_errors()
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message="Baseline cleared (Flit Log + FBER + AER)",
                criticality=StepCriticality.MEDIUM,
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.WARN,
                message=f"Baseline clear incomplete: {exc}",
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
            return self._make_summary(steps, start_time, params, device_id)

        # --- Step 3: Configure and trigger injection ---
        step = "Configure injection"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            config = FlitErrorInjectionConfig(
                inject_tx=inject_tx,
                inject_rx=inject_rx,
                num_errors=num_errors,
                error_type=error_type,
            )
            reader.configure_flit_error_injection(config)
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message=(
                    f"Injection configured: {num_errors} errors, "
                    f"type={error_type}, TX={inject_tx}, RX={inject_rx}"
                ),
                criticality=StepCriticality.HIGH,
                measured_values={
                    "num_errors": num_errors,
                    "error_type": error_type,
                    "inject_tx": inject_tx,
                    "inject_rx": inject_rx,
                },
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Injection configuration failed: {exc}",
                criticality=StepCriticality.CRITICAL,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if result.status == StepStatus.ERROR:
            return self._make_summary(steps, start_time, params, device_id)

        try:
            # --- Step 4: Wait for injection ---
            step = "Wait for injection"
            yield self._make_running(step)
            t0 = time.monotonic()
            elapsed = 0.0
            while elapsed < _INJECTION_SETTLE_S:
                if self._is_cancelled(cancel):
                    break
                chunk = min(0.5, _INJECTION_SETTLE_S - elapsed)
                time.sleep(chunk)
                elapsed += chunk
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message=f"Waited {elapsed:.1f}s for injection",
                criticality=StepCriticality.INFO,
                duration_ms=dur,
                port_number=port_number,
            )
            yield result
            steps.append(result)

            # --- Step 5: Read injection status ---
            step = "Read injection status"
            yield self._make_running(step)
            t0 = time.monotonic()
            try:
                post_inj = reader.get_flit_error_injection_status()
                dur = _elapsed_ms(t0)
                measured: dict[str, object] = {}
                if post_inj is not None:
                    measured = {
                        "flit_tx_status": post_inj.flit_tx_status,
                        "flit_rx_status": post_inj.flit_rx_status,
                    }
                result = self._make_result(
                    step,
                    StepStatus.PASS,
                    message="Injection status read",
                    criticality=StepCriticality.MEDIUM,
                    measured_values=measured,
                    duration_ms=dur,
                    port_number=port_number,
                )
            except Exception as exc:
                dur = _elapsed_ms(t0)
                result = self._make_result(
                    step,
                    StepStatus.WARN,
                    message=f"Status read issue: {exc}",
                    criticality=StepCriticality.MEDIUM,
                    duration_ms=dur,
                    port_number=port_number,
                )
            yield result
            steps.append(result)

            # --- Step 6: Drain Flit Error Log ---
            step = "Drain Flit Error Log"
            yield self._make_running(step)
            t0 = time.monotonic()
            try:
                entries = reader.read_all_flit_error_log_entries()
                dur = _elapsed_ms(t0)
                result = self._make_result(
                    step,
                    StepStatus.PASS,
                    message=f"Read {len(entries)} Flit Error Log entries",
                    criticality=StepCriticality.HIGH,
                    measured_values={
                        "entries_read": len(entries),
                        "expected_entries": num_errors,
                    },
                    duration_ms=dur,
                    port_number=port_number,
                )
            except Exception as exc:
                dur = _elapsed_ms(t0)
                result = self._make_result(
                    step,
                    StepStatus.ERROR,
                    message=f"Log drain failed: {exc}",
                    criticality=StepCriticality.HIGH,
                    duration_ms=dur,
                    port_number=port_number,
                )
            yield result
            steps.append(result)

            if result.status == StepStatus.ERROR:
                return self._make_summary(steps, start_time, params, device_id)

            # --- Step 7: Check post-injection AER ---
            step = "Check post-injection AER"
            yield self._make_running(step)
            t0 = time.monotonic()
            try:
                aer = reader.get_aer_status()
                dur = _elapsed_ms(t0)
                if aer is None:
                    result = self._make_result(
                        step,
                        StepStatus.SKIP,
                        message="AER not present",
                        criticality=StepCriticality.LOW,
                        duration_ms=dur,
                        port_number=port_number,
                    )
                else:
                    has_uncorr = aer.uncorrectable.raw_value != 0
                    has_corr = aer.correctable.raw_value != 0
                    if has_uncorr:
                        aer_status = StepStatus.WARN
                        aer_msg = "Uncorrectable AER errors after injection"
                    elif has_corr:
                        aer_status = StepStatus.WARN
                        aer_msg = "Correctable AER errors after injection"
                    else:
                        aer_status = StepStatus.PASS
                        aer_msg = "No AER errors after injection"
                    result = self._make_result(
                        step,
                        aer_status,
                        message=aer_msg,
                        criticality=StepCriticality.MEDIUM,
                        measured_values={
                            "uncorrectable_raw": aer.uncorrectable.raw_value,
                            "correctable_raw": aer.correctable.raw_value,
                        },
                        duration_ms=dur,
                        port_number=port_number,
                    )
            except Exception as exc:
                dur = _elapsed_ms(t0)
                result = self._make_result(
                    step,
                    StepStatus.WARN,
                    message=f"AER check failed: {exc}",
                    criticality=StepCriticality.MEDIUM,
                    duration_ms=dur,
                    port_number=port_number,
                )
            yield result
            steps.append(result)
        finally:
            # --- Step 8: Disable injection (always runs) ---
            step = "Disable injection"
            yield self._make_running(step)
            t0 = time.monotonic()
            try:
                reader.disable_flit_error_injection()
                dur = _elapsed_ms(t0)
                result = self._make_result(
                    step,
                    StepStatus.PASS,
                    message="Flit error injection disabled",
                    criticality=StepCriticality.MEDIUM,
                    duration_ms=dur,
                    port_number=port_number,
                )
            except Exception as exc:
                dur = _elapsed_ms(t0)
                result = self._make_result(
                    step,
                    StepStatus.WARN,
                    message=f"Failed to disable injection: {exc}",
                    criticality=StepCriticality.MEDIUM,
                    duration_ms=dur,
                    port_number=port_number,
                )
            yield result
            steps.append(result)

        # --- Step 9: Final verdict ---
        step = "Verify injection results"
        yield self._make_running(step)
        t0 = time.monotonic()

        entries_count = len(entries) if entries else 0
        if entries_count >= num_errors:
            final_status = StepStatus.PASS
            msg = f"Injection verified: {entries_count} log entries match {num_errors} injected"
        elif entries_count > 0:
            final_status = StepStatus.WARN
            msg = f"Partial match: {entries_count} log entries vs {num_errors} injected"
        else:
            final_status = StepStatus.FAIL
            msg = f"No log entries detected for {num_errors} injected errors"

        dur = _elapsed_ms(t0)
        result = self._make_result(
            step,
            final_status,
            message=msg,
            criticality=StepCriticality.CRITICAL,
            measured_values={
                "entries_detected": entries_count,
                "errors_injected": num_errors,
                "match": entries_count >= num_errors,
            },
            duration_ms=dur,
            port_number=port_number,
        )
        yield result
        steps.append(result)

        return self._make_summary(steps, start_time, params, device_id)


def _elapsed_ms(t0: float) -> float:
    return round((time.monotonic() - t0) * 1000, 2)
