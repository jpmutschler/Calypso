"""BER soak recipe -- run UTP or FBER (Gen6) and measure bit error rate per lane."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.core.pcie_config import PcieConfigReader
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

# Approximate per-lane bit rates for BER estimation
_LANE_RATE_BPS: dict[str, float] = {
    "2.5": 2.5e9,
    "5.0": 5.0e9,
    "8.0": 8.0e9,
    "16.0": 16.0e9,
    "32.0": 32.0e9,
    "64.0": 64.0e9,
}

# Map PcieConfigReader.get_link_status().current_speed (e.g. "Gen4") to _LANE_RATE_BPS keys
_SPEED_TO_RATE_KEY: dict[str, str] = {
    "Gen1": "2.5",
    "Gen2": "5.0",
    "Gen3": "8.0",
    "Gen4": "16.0",
    "Gen5": "32.0",
    "Gen6": "64.0",
}


class BerSoakRecipe(Recipe):
    """Soak a port with UTP (legacy) or FBER (Gen6 Flit) and measure BER per lane."""

    @property
    def recipe_id(self) -> str:
        return "ber_soak"

    @property
    def name(self) -> str:
        return "BER Soak Test"

    @property
    def description(self) -> str:
        return "Run UTP or FBER (Gen6) BER soak test and measure per-lane bit error rates"

    @property
    def category(self) -> RecipeCategory:
        return RecipeCategory.SIGNAL_INTEGRITY

    @property
    def requires_link_up(self) -> bool:
        return True

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
            RecipeParameter(
                name="granularity",
                label="FBER Granularity",
                description="FBER measurement granularity (Gen6 only, 0-3)",
                param_type="int",
                default=0,
                min_value=0,
                max_value=3,
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
        granularity: int = int(kwargs.get("granularity", 0))
        device_id: str = str(kwargs.get("device_id", ""))

        params = {
            "port_number": port_number,
            "duration_s": duration_s,
            "num_lanes": num_lanes,
            "granularity": granularity,
        }

        # Detect Gen6 Flit mode
        is_gen6 = self._is_gen6_flit(dev, dev_key)

        if is_gen6:
            yield from self._run_fber_path(
                dev,
                dev_key,
                cancel,
                steps,
                port_number,
                duration_s,
                granularity,
                device_id,
                params,
                start_time,
            )
        else:
            yield from self._run_utp_path(
                dev,
                dev_key,
                cancel,
                steps,
                port_number,
                duration_s,
                num_lanes,
                device_id,
                params,
                start_time,
            )

        return self._make_summary(steps, start_time, params, device_id)

    def _run_fber_path(
        self,
        dev: PLX_DEVICE_OBJECT,
        dev_key: PLX_DEVICE_KEY,
        cancel: dict[str, bool],
        steps: list[RecipeResult],
        port_number: int,
        duration_s: float,
        granularity: int,
        device_id: str,
        params: dict[str, object],
        start_time: float,
    ) -> Generator[RecipeResult, None, None]:
        """Gen6 FBER-based BER measurement path."""
        reader = PcieConfigReader(dev, dev_key)

        # --- Step 1: Clear FBER counters ---
        step = "Clear FBER counters"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            reader.clear_fber_counters()
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message="FBER counters cleared",
                criticality=StepCriticality.MEDIUM,
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Failed to clear FBER counters: {exc}",
                criticality=StepCriticality.CRITICAL,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)
        if result.status == StepStatus.ERROR:
            return

        if self._is_cancelled(cancel):
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return

        # --- Step 2: Start FBER measurement ---
        step = "Start FBER measurement"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            reader.start_fber_measurement(granularity)
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message=f"FBER measurement started (granularity={granularity})",
                criticality=StepCriticality.MEDIUM,
                measured_values={"mode": "fber", "granularity": granularity},
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Failed to start FBER: {exc}",
                criticality=StepCriticality.CRITICAL,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)
        if result.status == StepStatus.ERROR:
            return

        if self._is_cancelled(cancel):
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return

        # --- Step 3: Soak ---
        step = f"FBER soak for {duration_s}s"
        yield self._make_running(step)
        t0 = time.monotonic()
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
            try:
                reader.stop_fber_measurement()
            except Exception:
                logger.warning("fber_stop_failed_on_cancel", port=port_number)
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return

        # --- Step 4: Stop FBER measurement ---
        step = "Stop FBER measurement"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            reader.stop_fber_measurement()
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message="FBER measurement stopped",
                criticality=StepCriticality.MEDIUM,
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Failed to stop FBER: {exc}",
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        # --- Step 5: Read and analyze FBER results ---
        step = "Analyze FBER results"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            fber = reader.get_fber_status()
            dur = round((time.monotonic() - t0) * 1000, 2)

            if fber is None:
                result = self._make_result(
                    step,
                    StepStatus.ERROR,
                    message="FBER capability not present",
                    criticality=StepCriticality.CRITICAL,
                    duration_ms=dur,
                    port_number=port_number,
                )
            else:
                lane_counters = fber.lane_counters
                total_errors = sum(lane_counters)
                lane_details: list[dict[str, object]] = []

                # Compute per-lane BER estimate using actual negotiated speed
                link = reader.get_link_status()
                speed_str = _SPEED_TO_RATE_KEY.get(link.current_speed, "")
                lane_rate = _LANE_RATE_BPS.get(speed_str, 64.0e9)
                bits_tested = elapsed * lane_rate

                worst_status = StepStatus.PASS
                for idx, count in enumerate(lane_counters):
                    ber = count / bits_tested if bits_tested > 0 else 0.0
                    lane_info: dict[str, object] = {
                        "lane": idx,
                        "error_count": count,
                        "estimated_ber": ber,
                    }
                    if ber > _BER_WARN_THRESHOLD:
                        lane_info["status"] = "fail"
                        worst_status = StepStatus.FAIL
                    elif ber > _BER_PASS_THRESHOLD:
                        lane_info["status"] = "warn"
                        if worst_status != StepStatus.FAIL:
                            worst_status = StepStatus.WARN
                    elif count > 0:
                        lane_info["status"] = "marginal"
                        if worst_status == StepStatus.PASS:
                            worst_status = StepStatus.WARN
                    else:
                        lane_info["status"] = "pass"
                    lane_details.append(lane_info)

                if total_errors == 0:
                    msg = "FBER soak completed with zero errors on all lanes"
                else:
                    msg = f"FBER soak completed with {total_errors} total error(s)"

                result = self._make_result(
                    step,
                    worst_status,
                    message=msg,
                    criticality=StepCriticality.CRITICAL,
                    measured_values={
                        "mode": "fber",
                        "total_errors": total_errors,
                        "flit_counter": fber.flit_counter,
                        "lanes": lane_details,
                    },
                    duration_ms=dur,
                    port_number=port_number,
                )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"FBER result read failed: {exc}",
                criticality=StepCriticality.CRITICAL,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

    def _run_utp_path(
        self,
        dev: PLX_DEVICE_OBJECT,
        dev_key: PLX_DEVICE_KEY,
        cancel: dict[str, bool],
        steps: list[RecipeResult],
        port_number: int,
        duration_s: float,
        num_lanes: int,
        device_id: str,
        params: dict[str, object],
        start_time: float,
    ) -> Generator[RecipeResult, None, None]:
        """Legacy UTP-based BER measurement path."""
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
            return

        if self._is_cancelled(cancel):
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return

        # --- Step 2: Soak ---
        step = f"Soak for {duration_s}s"
        yield self._make_running(step)
        t0 = time.monotonic()
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
            return

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
            return

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
                "mode": "utp",
                "total_errors": total_errors,
                "all_synced": all_synced,
                "lanes": lane_details,
            },
            duration_ms=dur,
            port_number=port_number,
        )
        yield result
        steps.append(result)
