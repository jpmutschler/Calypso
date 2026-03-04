"""Error Aggregation Sweep recipe -- aggregate errors across all active ports."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.core.error_aggregator import ErrorAggregator
from calypso.core.port_manager import PortManager
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

_RECOVERY_WARN_DEFAULT = 10


class ErrorAggregationSweepRecipe(Recipe):
    """Aggregate errors across all active ports with optional MCU data."""

    @property
    def recipe_id(self) -> str:
        return "error_aggregation_sweep"

    @property
    def name(self) -> str:
        return "Error Aggregation Sweep"

    @property
    def description(self) -> str:
        return "Aggregate AER, LTSSM, and MCU errors across all active ports"

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
                name="mcu_port",
                label="MCU Port",
                description="Serial port for MCU connection (empty to skip)",
                param_type="str",
                default="",
            ),
            RecipeParameter(
                name="recovery_warn_threshold",
                label="Recovery Warn Threshold",
                description="LTSSM recovery count threshold for warnings",
                param_type="int",
                default=_RECOVERY_WARN_DEFAULT,
                min_value=1,
                max_value=1000,
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

        mcu_port: str = str(kwargs.get("mcu_port", ""))
        recovery_warn_threshold: int = int(
            kwargs.get("recovery_warn_threshold", _RECOVERY_WARN_DEFAULT)
        )
        device_id: str = str(kwargs.get("device_id", ""))
        params = {
            "mcu_port": mcu_port,
            "recovery_warn_threshold": recovery_warn_threshold,
        }

        # --- Step 1: Enumerate active ports ---
        step = "Enumerate active ports"
        yield self._make_running(step)
        t0 = time.monotonic()
        active_ports: list[int] = []
        try:
            pm = PortManager(dev, dev_key)
            port_statuses = pm.get_all_port_statuses()
            active_ports = [p.port_number for p in port_statuses if p.is_link_up]
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message=(
                    f"Found {len(active_ports)} active port(s) out of {len(port_statuses)} total"
                ),
                criticality=StepCriticality.MEDIUM,
                measured_values={
                    "total_ports": len(port_statuses),
                    "active_ports": len(active_ports),
                    "active_port_numbers": active_ports,
                },
                duration_ms=dur,
            )
        except Exception as exc:
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Port enumeration failed: {exc}",
                criticality=StepCriticality.CRITICAL,
                duration_ms=dur,
            )
        yield result
        steps.append(result)

        if result.status == StepStatus.ERROR:
            return self._make_summary(steps, start_time, params, device_id)

        if self._is_cancelled(cancel):
            return self._make_summary(steps, start_time, params, device_id)

        # --- Step 2: Build error overview ---
        step = "Build error overview"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            aggregator = ErrorAggregator(dev, dev_key)
            overview = aggregator.get_overview(
                mcu_port=mcu_port if mcu_port else None,
                active_ports=active_ports,
            )
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message="Error overview built",
                criticality=StepCriticality.MEDIUM,
                measured_values={
                    "aer_available": overview.aer_available,
                    "total_aer_uncorrectable": overview.total_aer_uncorrectable,
                    "total_aer_correctable": overview.total_aer_correctable,
                    "total_mcu_errors": overview.total_mcu_errors,
                    "total_ltssm_recoveries": overview.total_ltssm_recoveries,
                    "mcu_connected": overview.mcu_connected,
                },
                duration_ms=dur,
            )
        except Exception as exc:
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Error aggregation failed: {exc}",
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
            )
        yield result
        steps.append(result)

        if result.status == StepStatus.ERROR:
            return self._make_summary(steps, start_time, params, device_id)

        if self._is_cancelled(cancel):
            return self._make_summary(steps, start_time, params, device_id)

        # --- Step 3: Per-port error reports ---
        outlier_ports: list[int] = []
        avg_recoveries = 0.0
        if overview.port_errors:
            recovery_counts = [pe.ltssm_recovery_count for pe in overview.port_errors]
            avg_recoveries = sum(recovery_counts) / len(recovery_counts) if recovery_counts else 0

        for pe in overview.port_errors:
            if self._is_cancelled(cancel):
                break

            port_step = f"Port {pe.port_number} errors"
            yield self._make_running(port_step)
            t0 = time.monotonic()

            is_outlier = pe.ltssm_recovery_count > max(recovery_warn_threshold, avg_recoveries * 3)
            if is_outlier:
                outlier_ports.append(pe.port_number)

            if pe.aer_uncorrectable_count > 0:
                port_status = StepStatus.FAIL
                msg = f"Port {pe.port_number}: {pe.aer_uncorrectable_count} uncorrectable AER"
            elif is_outlier:
                port_status = StepStatus.WARN
                msg = f"Port {pe.port_number}: outlier recoveries ({pe.ltssm_recovery_count})"
            elif pe.aer_correctable_count > 0 or pe.mcu_error_count > 0:
                port_status = StepStatus.WARN
                msg = (
                    f"Port {pe.port_number}: "
                    f"{pe.aer_correctable_count} correctable AER, "
                    f"{pe.mcu_error_count} MCU errors"
                )
            else:
                port_status = StepStatus.PASS
                msg = f"Port {pe.port_number}: clean"

            dur = _elapsed_ms(t0)
            port_result = self._make_result(
                port_step,
                port_status,
                message=msg,
                criticality=StepCriticality.MEDIUM,
                measured_values={
                    "recovery_count": pe.ltssm_recovery_count,
                    "link_down_count": pe.link_down_count,
                    "aer_uncorrectable": pe.aer_uncorrectable_count,
                    "aer_correctable": pe.aer_correctable_count,
                    "mcu_errors": pe.mcu_error_count,
                },
                duration_ms=dur,
                port_number=pe.port_number,
            )
            yield port_result
            steps.append(port_result)

        # --- Step 4: Aggregate totals ---
        step = "Aggregate totals"
        yield self._make_running(step)
        t0 = time.monotonic()

        if overview.total_aer_uncorrectable > 0:
            final_status = StepStatus.FAIL
            msg = (
                f"Uncorrectable AER errors: {overview.total_aer_uncorrectable}, "
                f"correctable: {overview.total_aer_correctable}, "
                f"MCU: {overview.total_mcu_errors}, "
                f"recoveries: {overview.total_ltssm_recoveries}"
            )
        elif overview.total_ltssm_recoveries > recovery_warn_threshold * len(active_ports):
            final_status = StepStatus.WARN
            msg = f"Excessive total recoveries: {overview.total_ltssm_recoveries}"
        elif overview.total_aer_correctable > 0 or overview.total_mcu_errors > 0:
            final_status = StepStatus.WARN
            msg = (
                f"Correctable errors present: "
                f"AER={overview.total_aer_correctable}, "
                f"MCU={overview.total_mcu_errors}"
            )
        else:
            final_status = StepStatus.PASS
            msg = "Zero errors across all ports"

        dur = _elapsed_ms(t0)
        result = self._make_result(
            step,
            final_status,
            message=msg,
            criticality=StepCriticality.CRITICAL,
            measured_values={
                "total_aer_uncorrectable": overview.total_aer_uncorrectable,
                "total_aer_correctable": overview.total_aer_correctable,
                "total_mcu_errors": overview.total_mcu_errors,
                "total_ltssm_recoveries": overview.total_ltssm_recoveries,
                "outlier_ports": outlier_ports,
            },
            duration_ms=dur,
        )
        yield result
        steps.append(result)

        return self._make_summary(steps, start_time, params, device_id)


def _elapsed_ms(t0: float) -> float:
    return round((time.monotonic() - t0) * 1000, 2)
