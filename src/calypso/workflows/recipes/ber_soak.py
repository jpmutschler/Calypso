"""BER soak recipe -- run User Test Pattern and measure bit error rate per lane."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.core.phy_monitor import PhyMonitor
from calypso.hardware.atlas3_phy import UserTestPattern
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

_BER_PASS_THRESHOLD = 1e-12
_BER_WARN_THRESHOLD = 1e-9

# Default 16-byte UTP pattern (alternating 0xAA/0x55)
_DEFAULT_PATTERN = bytes([0xAA, 0x55] * 8)


class BerSoakRecipe(Recipe):
    """Soak a port with User Test Pattern traffic and measure BER per lane."""

    @property
    def recipe_id(self) -> str:
        return "ber_soak"

    @property
    def name(self) -> str:
        return "BER Soak Test"

    @property
    def description(self) -> str:
        return "Run UTP-based BER soak test and measure per-lane bit error rates"

    @property
    def category(self) -> RecipeCategory:
        return RecipeCategory.SIGNAL_INTEGRITY

    @property
    def estimated_duration_s(self) -> int:
        return 120

    @property
    def parameters(self) -> list[RecipeParameter]:
        return [
            RecipeParameter(
                name="port_number",
                label="Port Number",
                description="Target port for BER test",
                param_type="int",
                default=0,
                min_value=0,
                max_value=143,
            ),
            RecipeParameter(
                name="duration_s",
                label="Soak Duration",
                description="How long to run the BER soak",
                param_type="float",
                default=30.0,
                min_value=5.0,
                max_value=600.0,
                unit="s",
            ),
            RecipeParameter(
                name="num_lanes",
                label="Number of Lanes",
                description="Lanes to measure",
                param_type="int",
                default=4,
                min_value=1,
                max_value=16,
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
        duration_s: float = float(kwargs.get("duration_s", 30.0))
        num_lanes: int = int(kwargs.get("num_lanes", 4))

        params = {
            "port_number": port_number,
            "duration_s": duration_s,
            "num_lanes": num_lanes,
        }

        # --- Step 1: Prepare UTP test ---
        step = "Prepare UTP test"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            phy = PhyMonitor(dev, dev_key, port_number)
            pattern = UserTestPattern(data=_DEFAULT_PATTERN)
            phy.prepare_utp_test(pattern)
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message="UTP test prepared",
                criticality=StepCriticality.MEDIUM,
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"UTP preparation failed: {exc}",
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

        # --- Step 2: Soak ---
        step = f"Soak for {duration_s}s"
        yield self._make_running(step)
        t0 = time.monotonic()

        # Sleep in short intervals to allow cancellation checks
        elapsed = 0.0
        while elapsed < duration_s:
            if self._is_cancelled(cancel):
                break
            chunk = min(1.0, duration_s - elapsed)
            time.sleep(chunk)
            elapsed += chunk

        dur = round((time.monotonic() - t0) * 1000, 2)
        result = self._make_result(
            step,
            StepStatus.PASS,
            message=f"Soaked for {elapsed:.1f}s",
            criticality=StepCriticality.INFO,
            measured_values={"actual_duration_s": round(elapsed, 1)},
            duration_ms=dur,
            port_number=port_number,
        )
        yield result
        steps.append(result)

        if self._is_cancelled(cancel):
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return self._make_summary(steps, start_time, params)

        # --- Step 3: Collect results ---
        step = "Collect results"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            utp_results = phy.collect_utp_results(num_lanes=num_lanes)
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message=f"Collected results for {len(utp_results)} lane(s)",
                criticality=StepCriticality.MEDIUM,
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Result collection failed: {exc}",
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if result.status == StepStatus.ERROR:
            return self._make_summary(steps, start_time, params)

        # --- Step 4: Analyze BER per lane ---
        step = "Analyze BER per lane"
        yield self._make_running(step)
        t0 = time.monotonic()

        worst_status = StepStatus.PASS
        lane_details: list[dict[str, object]] = []

        for utp in utp_results:
            lane_info: dict[str, object] = {
                "lane": utp.lane,
                "synced": utp.synced,
                "error_count": utp.error_count,
            }

            if not utp.synced:
                worst_status = StepStatus.FAIL
                lane_info["status"] = "no_sync"
            elif utp.error_count == 0:
                lane_info["status"] = "pass"
            else:
                # Estimate BER from error count and soak duration
                # Rough estimate: bits_tested ~ duration_s * link_rate_bps
                # Use error_count as proxy since we lack exact bit count
                lane_info["status"] = "errors_detected"
                if worst_status != StepStatus.FAIL:
                    worst_status = StepStatus.WARN

            lane_details.append(lane_info)

        total_errors = sum(utp.error_count for utp in utp_results)
        all_synced = all(utp.synced for utp in utp_results)

        if not all_synced:
            msg = "Some lanes failed to sync during BER soak"
            worst_status = StepStatus.FAIL
        elif total_errors > 0:
            msg = f"BER soak completed with {total_errors} total error(s)"
        else:
            msg = "BER soak completed with zero errors on all lanes"

        dur = round((time.monotonic() - t0) * 1000, 2)
        result = self._make_result(
            step,
            worst_status,
            message=msg,
            criticality=StepCriticality.CRITICAL,
            measured_values={
                "total_errors": total_errors,
                "all_synced": all_synced,
                "lanes": lane_details,
            },
            duration_ms=dur,
            port_number=port_number,
        )
        yield result
        steps.append(result)

        return self._make_summary(steps, start_time, params)
