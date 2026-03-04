"""Flit Error Log Drain recipe -- read and analyze Flit Error Log FIFO entries."""

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


class FlitErrorLogDrainRecipe(Recipe):
    """Drain and analyze the Flit Error Log FIFO for Gen6 links."""

    @property
    def recipe_id(self) -> str:
        return "flit_error_log_drain"

    @property
    def name(self) -> str:
        return "Flit Error Log Drain"

    @property
    def description(self) -> str:
        return "Read Flit Error Log FIFO entries and analyze FEC error distribution"

    @property
    def category(self) -> RecipeCategory:
        return RecipeCategory.ERROR_TESTING

    @property
    def estimated_duration_s(self) -> int:
        return 10

    @property
    def parameters(self) -> list[RecipeParameter]:
        return [
            RecipeParameter(
                name="port_number",
                label="Port Number",
                description="Target port for Flit Error Log drain",
                param_type="int",
                default=0,
                min_value=0,
                max_value=143,
            ),
            RecipeParameter(
                name="max_entries",
                label="Max Entries",
                description="Maximum FIFO entries to read",
                param_type="int",
                default=64,
                min_value=1,
                max_value=256,
            ),
            RecipeParameter(
                name="enable_counter",
                label="Enable Error Counter",
                description="Enable the Flit Error Counter before draining",
                param_type="bool",
                default=True,
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
        max_entries: int = int(kwargs.get("max_entries", 64))
        enable_counter: bool = bool(kwargs.get("enable_counter", True))
        device_id: str = str(kwargs.get("device_id", ""))

        params = {
            "port_number": port_number,
            "max_entries": max_entries,
            "enable_counter": enable_counter,
        }

        reader = PcieConfigReader(dev, dev_key)

        # --- Step 1: Check Flit Logging capability ---
        step = "Check Flit Logging capability"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            flit_status = reader.get_flit_logging_status()
            dur = _elapsed_ms(t0)
            if flit_status is None:
                result = self._make_result(
                    step,
                    StepStatus.SKIP,
                    message="Flit Logging capability not present",
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
                message=f"Flit Logging capability found at offset 0x{flit_status.cap_offset:X}",
                criticality=StepCriticality.MEDIUM,
                measured_values={"cap_offset": flit_status.cap_offset},
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Failed to check Flit Logging: {exc}",
                criticality=StepCriticality.CRITICAL,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if result.status in (StepStatus.ERROR, StepStatus.SKIP):
            return self._make_summary(steps, start_time, params, device_id)

        if self._is_cancelled(cancel):
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return self._make_summary(steps, start_time, params, device_id)

        # --- Step 2: Read Flit Logging status ---
        step = "Read Flit Logging status"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message="Flit Logging status read",
                criticality=StepCriticality.INFO,
                measured_values={
                    "counter_enabled": flit_status.error_counter.enable,
                    "counter_value": flit_status.error_counter.counter,
                    "fber_enabled": flit_status.fber.enabled,
                },
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.WARN,
                message=f"Status read issue: {exc}",
                criticality=StepCriticality.LOW,
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

        # --- Step 3: Configure error counter ---
        if enable_counter:
            step = "Configure error counter"
            yield self._make_running(step)
            t0 = time.monotonic()
            try:
                reader.configure_flit_error_counter(enable=True)
                dur = _elapsed_ms(t0)
                result = self._make_result(
                    step,
                    StepStatus.PASS,
                    message="Error counter enabled",
                    criticality=StepCriticality.MEDIUM,
                    duration_ms=dur,
                    port_number=port_number,
                )
            except Exception as exc:
                dur = _elapsed_ms(t0)
                result = self._make_result(
                    step,
                    StepStatus.WARN,
                    message=f"Counter configuration failed: {exc}",
                    criticality=StepCriticality.LOW,
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

        # --- Step 4: Drain error log FIFO ---
        step = "Drain error log FIFO"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            entries = reader.read_all_flit_error_log_entries(max_entries)
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message=f"Drained {len(entries)} FIFO entry/entries",
                criticality=StepCriticality.MEDIUM,
                measured_values={"entries_read": len(entries)},
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"FIFO drain failed: {exc}",
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
                port_number=port_number,
            )
            yield result
            steps.append(result)
            return self._make_summary(steps, start_time, params, device_id)
        yield result
        steps.append(result)

        # --- Step 5: Analyze error entries ---
        step = "Analyze error entries"
        yield self._make_running(step)
        t0 = time.monotonic()

        fec_uncorrectable = sum(1 for e in entries if e.fec_uncorrectable)
        fec_correctable = len(entries) - fec_uncorrectable
        unrecognized = sum(1 for e in entries if e.unrecognized_flit)
        consecutive_clusters = sum(1 for e in entries if e.consecutive_errors > 0)

        # Syndrome distribution
        syndrome_counts: dict[int, int] = {}
        for e in entries:
            for s in (e.syndrome_0, e.syndrome_1, e.syndrome_2, e.syndrome_3):
                if s != 0:
                    syndrome_counts[s] = syndrome_counts.get(s, 0) + 1

        measured: dict[str, object] = {
            "total_entries": len(entries),
            "fec_uncorrectable": fec_uncorrectable,
            "fec_correctable": fec_correctable,
            "unrecognized_flits": unrecognized,
            "consecutive_error_clusters": consecutive_clusters,
            "unique_syndromes": len(syndrome_counts),
        }

        if fec_uncorrectable > 0:
            status = StepStatus.FAIL
            message = f"FEC uncorrectable errors: {fec_uncorrectable}"
        elif len(entries) > 0:
            status = StepStatus.WARN
            message = (
                f"{fec_correctable} correctable, "
                f"{unrecognized} unrecognized, "
                f"{consecutive_clusters} consecutive clusters"
            )
        else:
            status = StepStatus.PASS
            message = "No Flit Error Log entries"

        dur = _elapsed_ms(t0)
        result = self._make_result(
            step,
            status,
            message=message,
            criticality=StepCriticality.CRITICAL,
            measured_values=measured,
            duration_ms=dur,
            port_number=port_number,
        )
        yield result
        steps.append(result)

        return self._make_summary(steps, start_time, params, device_id)


def _elapsed_ms(t0: float) -> float:
    return round((time.monotonic() - t0) * 1000, 2)
