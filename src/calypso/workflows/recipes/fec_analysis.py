"""FEC counter analysis recipe -- measure FEC correction rate at Gen6 64GT/s."""

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
from calypso.workflows.thresholds import FEC_MARGIN_RATIO_CAP, FEC_RATE_FAIL, FEC_RATE_WARN

logger = get_logger(__name__)


class FecAnalysisRecipe(Recipe):
    """Measure FEC correction rate over a soak period on Gen6 64GT/s links."""

    @property
    def recipe_id(self) -> str:
        return "fec_analysis"

    @property
    def name(self) -> str:
        return "FEC Counter Analysis"

    @property
    def description(self) -> str:
        return "Measure FEC correction rate and margin at Gen6 64GT/s"

    @property
    def category(self) -> RecipeCategory:
        return RecipeCategory.SIGNAL_INTEGRITY

    @property
    def requires_link_up(self) -> bool:
        return True

    @property
    def estimated_duration_s(self) -> int:
        return 45

    @property
    def parameters(self) -> list[RecipeParameter]:
        return [
            RecipeParameter(
                name="port_number",
                label="Port Number",
                description="Target port for FEC analysis",
                param_type="int",
                default=0,
                min_value=0,
                max_value=143,
            ),
            RecipeParameter(
                name="soak_duration_s",
                label="Soak Duration",
                description="How long to count FEC events",
                param_type="float",
                default=30.0,
                min_value=5.0,
                max_value=300.0,
                unit="s",
            ),
            RecipeParameter(
                name="sample_interval_s",
                label="Sample Interval",
                description="Time between counter reads",
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
        soak_duration_s: float = float(kwargs.get("soak_duration_s", 30.0))
        sample_interval_s: float = float(kwargs.get("sample_interval_s", 1.0))
        device_id: str = str(kwargs.get("device_id", ""))

        params = {
            "port_number": port_number,
            "soak_duration_s": soak_duration_s,
            "sample_interval_s": sample_interval_s,
        }

        reader = PcieConfigReader(dev, dev_key)

        # --- Step 1: Verify Gen6 Flit mode ---
        step = "Verify Gen6 Flit mode"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            is_gen6 = self._is_gen6_flit(dev, dev_key)
            dur = _elapsed_ms(t0)
            if not is_gen6:
                result = self._make_result(
                    step,
                    StepStatus.SKIP,
                    message="Link is not operating at Gen6 64GT/s — FEC analysis requires Flit mode",
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
                message="Gen6 Flit mode confirmed",
                criticality=StepCriticality.MEDIUM,
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Gen6 check failed: {exc}",
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

        # --- Step 2: Read baseline FEC counters ---
        step = "Read baseline FEC counters"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            # Configure FEC counter for all errors (events_to_count=0)
            reader.configure_flit_error_counter(enable=True, events_to_count=0)
            baseline_status = reader.get_flit_logging_status()
            dur = _elapsed_ms(t0)

            if baseline_status is None:
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

            baseline_count = baseline_status.error_counter.counter
            result = self._make_result(
                step,
                StepStatus.PASS,
                message=f"Baseline FEC counter: {baseline_count}",
                criticality=StepCriticality.MEDIUM,
                measured_values={
                    "baseline_count": baseline_count,
                    "counter_enabled": baseline_status.error_counter.enable,
                },
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Baseline read failed: {exc}",
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

        # --- Step 3: FEC soak ---
        step = "FEC soak"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            time_series: list[dict[str, object]] = []
            elapsed = 0.0
            while elapsed < soak_duration_s:
                if self._is_cancelled(cancel):
                    break
                chunk = min(sample_interval_s, soak_duration_s - elapsed)
                time.sleep(chunk)
                elapsed += chunk

                try:
                    sample_status = reader.get_flit_logging_status()
                    if sample_status is not None:
                        time_series.append(
                            {
                                "t": round(elapsed, 2),
                                "count": sample_status.error_counter.counter,
                            }
                        )
                except Exception as sample_exc:
                    logger.debug("fec_sample_read_failed", error=str(sample_exc))

            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message=f"Soaked for {elapsed:.1f}s, collected {len(time_series)} samples",
                criticality=StepCriticality.MEDIUM,
                measured_values={
                    "actual_soak_s": round(elapsed, 1),
                    "samples_collected": len(time_series),
                },
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"FEC soak failed: {exc}",
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
                port_number=port_number,
            )
            time_series = []
        yield result
        steps.append(result)

        if result.status == StepStatus.ERROR:
            return self._make_summary(steps, start_time, params, device_id)

        # --- Step 4: Read final FEC counters ---
        step = "Read final FEC counters"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            final_status = reader.get_flit_logging_status()
            dur = _elapsed_ms(t0)
            if final_status is None:
                result = self._make_result(
                    step,
                    StepStatus.ERROR,
                    message="Flit Logging status unavailable after soak",
                    criticality=StepCriticality.HIGH,
                    duration_ms=dur,
                    port_number=port_number,
                )
            else:
                final_count = final_status.error_counter.counter
                delta = final_count - baseline_count
                result = self._make_result(
                    step,
                    StepStatus.PASS,
                    message=f"Final FEC counter: {final_count} (delta: {delta})",
                    criticality=StepCriticality.MEDIUM,
                    measured_values={
                        "final_count": final_count,
                        "fec_total_delta": delta,
                    },
                    duration_ms=dur,
                    port_number=port_number,
                )
        except Exception as exc:
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Final read failed: {exc}",
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if result.status == StepStatus.ERROR:
            return self._make_summary(steps, start_time, params, device_id)

        # --- Step 4b: Count uncorrectable events via Flit Error Log FIFO ---
        step = "Count uncorrectable events"
        yield self._make_running(step)
        t0 = time.monotonic()
        fec_uncorrectable = 0
        try:
            # Read Flit Error Log FIFO entries and classify uncorrectable events.
            # FIFO depth is limited (typically 64 entries); if the FIFO overflowed
            # during the soak, the uncorrectable count may undercount.
            entries = reader.read_all_flit_error_log_entries(max_entries=64)
            fec_uncorrectable = sum(1 for e in entries if e.fec_uncorrectable)
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message=(
                    f"FEC uncorrectable count: {fec_uncorrectable}"
                    f" (from {len(entries)} FIFO entries)"
                ),
                criticality=StepCriticality.MEDIUM,
                measured_values={
                    "fec_uncorrectable_raw": fec_uncorrectable,
                    "fifo_entries_read": len(entries),
                },
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = _elapsed_ms(t0)
            logger.debug("fec_uncorrectable_read_failed", error=str(exc))
            result = self._make_result(
                step,
                StepStatus.WARN,
                message=f"Uncorrectable read failed ({exc}); using 0",
                criticality=StepCriticality.MEDIUM,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        # --- Step 5: Analyze FEC rate ---
        step = "Analyze FEC rate"
        yield self._make_running(step)
        t0 = time.monotonic()

        fec_delta = final_count - baseline_count
        actual_soak = elapsed if elapsed > 0 else soak_duration_s

        # Compute correctable = all_errors - uncorrectable
        fec_correctable = max(fec_delta - fec_uncorrectable, 0)

        # Corrections per second
        fec_rate = fec_delta / actual_soak if actual_soak > 0 else 0.0

        # Per-lane bit rate at 64GT/s, scaled by link width
        lane_rate_bps = 64.0e9
        link_width = baseline_status.error_counter.link_width or 1
        bits_tested = actual_soak * lane_rate_bps * link_width

        # Corrections per bit (rough FEC correction BER)
        fec_ber = fec_delta / bits_tested if bits_tested > 0 else 0.0

        # Margin ratio: how far from the fail threshold (capped for JSON safety)
        fec_margin_ratio = (
            min(FEC_RATE_FAIL / fec_rate, FEC_MARGIN_RATIO_CAP)
            if fec_rate > 0
            else FEC_MARGIN_RATIO_CAP
        )

        if fec_rate >= FEC_RATE_FAIL:
            status = StepStatus.FAIL
            msg = (
                f"FEC correction rate {fec_rate:.1f}/s exceeds fail threshold"
                f" ({FEC_RATE_FAIL:.0f}/s)"
            )
        elif fec_rate >= FEC_RATE_WARN:
            status = StepStatus.WARN
            msg = (
                f"FEC correction rate {fec_rate:.1f}/s exceeds warn threshold"
                f" ({FEC_RATE_WARN:.0f}/s)"
            )
        elif fec_delta > 0:
            status = StepStatus.PASS
            msg = f"FEC corrections detected ({fec_delta}) but rate {fec_rate:.1f}/s within limits"
        else:
            status = StepStatus.PASS
            msg = "Zero FEC corrections during soak"

        dur = _elapsed_ms(t0)
        result = self._make_result(
            step,
            status,
            message=msg,
            criticality=StepCriticality.CRITICAL,
            measured_values={
                "fec_correctable_total": fec_correctable,
                "fec_uncorrectable_total": fec_uncorrectable,
                "fec_correction_rate": round(fec_rate, 4),
                "fec_correction_ber": fec_ber,
                "soak_duration_s": round(actual_soak, 1),
                "bits_tested": bits_tested,
                "fec_margin_ratio": round(fec_margin_ratio, 2),
                "time_series": time_series,
            },
            duration_ms=dur,
            port_number=port_number,
        )
        yield result
        steps.append(result)

        return self._make_summary(steps, start_time, params, device_id)


def _elapsed_ms(t0: float) -> float:
    return round((time.monotonic() - t0) * 1000, 2)
