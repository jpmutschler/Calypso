"""PAM4 Eye Sweep recipe -- sweep 3 PAM4 sub-eyes per lane at 64GT/s."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.core.lane_margining import LaneMarginingEngine
from calypso.core.phy_monitor import PhyMonitor
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

_PAM4_MIN_MARGIN_UI = 0.05
_PAM4_WARN_MARGIN_UI = 0.10


class Pam4EyeSweepRecipe(Recipe):
    """Sweep PAM4 sub-eyes per lane for Gen6 64GT/s links."""

    @property
    def recipe_id(self) -> str:
        return "pam4_eye_sweep"

    @property
    def name(self) -> str:
        return "PAM4 Eye Sweep"

    @property
    def description(self) -> str:
        return "Sweep 3 PAM4 sub-eyes per lane for Gen6 64GT/s signal quality"

    @property
    def category(self) -> RecipeCategory:
        return RecipeCategory.SIGNAL_INTEGRITY

    @property
    def estimated_duration_s(self) -> int:
        return 300

    @property
    def parameters(self) -> list[RecipeParameter]:
        return [
            RecipeParameter(
                name="port_number",
                label="Port Number",
                description="Target port for PAM4 eye sweep",
                param_type="int",
                default=0,
                min_value=0,
                max_value=143,
            ),
            RecipeParameter(
                name="num_lanes",
                label="Number of Lanes",
                description="Number of lanes to sweep",
                param_type="int",
                default=4,
                min_value=1,
                max_value=16,
            ),
            RecipeParameter(
                name="skip_if_not_pam4",
                label="Skip if Not PAM4",
                description="Skip all sweeps if link is not at 64GT/s PAM4",
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
        num_lanes: int = int(kwargs.get("num_lanes", 4))
        skip_if_not_pam4: bool = bool(kwargs.get("skip_if_not_pam4", True))
        device_id: str = str(kwargs.get("device_id", ""))
        params = {
            "port_number": port_number,
            "num_lanes": num_lanes,
            "skip_if_not_pam4": skip_if_not_pam4,
        }

        # --- Step 1: Check link speed ---
        step = "Check link speed"
        yield self._make_running(step)
        t0 = time.monotonic()

        is_64gt = self._is_gen6_flit(dev, dev_key)
        dur = _elapsed_ms(t0)

        if not is_64gt and skip_if_not_pam4:
            result = self._make_result(
                step,
                StepStatus.SKIP,
                message="Link not at 64GT/s PAM4 -- skipping sweep",
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
            message=f"Link at 64GT/s: {is_64gt}",
            criticality=StepCriticality.MEDIUM,
            measured_values={"is_64gt": is_64gt},
            duration_ms=dur,
            port_number=port_number,
        )
        yield result
        steps.append(result)

        if self._is_cancelled(cancel):
            return self._make_summary(steps, start_time, params, device_id)

        # --- Step 2: Verify lane margining capability ---
        step = "Verify lane margining capability"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            phy = PhyMonitor(dev, dev_key, port_number)
            has_margining = phy.has_lane_margining()
            dur = _elapsed_ms(t0)

            if not has_margining:
                result = self._make_result(
                    step,
                    StepStatus.SKIP,
                    message="Lane Margining not supported on this port",
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
                message="Lane Margining capability present",
                criticality=StepCriticality.MEDIUM,
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Margining check failed: {exc}",
                criticality=StepCriticality.CRITICAL,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if result.status == StepStatus.ERROR:
            return self._make_summary(steps, start_time, params, device_id)

        # Initialize margining engine
        yield self._make_running("Init margining engine")
        try:
            engine = LaneMarginingEngine(dev, dev_key, port_number)
        except Exception as exc:
            result = self._make_result(
                "Init margining engine",
                StepStatus.ERROR,
                message=f"Margining engine init failed: {exc}",
                criticality=StepCriticality.CRITICAL,
                port_number=port_number,
            )
            yield result
            steps.append(result)
            return self._make_summary(steps, start_time, params, device_id)

        # --- Per-lane sweep ---
        worst_lane = -1
        worst_margin = float("inf")
        all_pass = True

        try:
            for lane_idx in range(num_lanes):
                if self._is_cancelled(cancel):
                    skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
                    yield skip
                    steps.append(skip)
                    break

                step = f"Sweep lane {lane_idx}"
                yield self._make_running(step)
                t0 = time.monotonic()

                try:
                    sweep = engine.sweep_lane(lane_idx, device_id="")
                    dur = _elapsed_ms(t0)

                    eye_width = sweep.eye_width_ui
                    eye_height = sweep.eye_height_mv

                    if eye_width < _PAM4_MIN_MARGIN_UI:
                        lane_status = StepStatus.FAIL
                        all_pass = False
                    elif eye_width < _PAM4_WARN_MARGIN_UI:
                        lane_status = StepStatus.WARN
                    else:
                        lane_status = StepStatus.PASS

                    if eye_width < worst_margin:
                        worst_margin = eye_width
                        worst_lane = lane_idx

                    result = self._make_result(
                        step,
                        lane_status,
                        message=(
                            f"Lane {lane_idx}: width={eye_width:.4f} UI, height={eye_height:.2f} mV"
                        ),
                        criticality=StepCriticality.HIGH,
                        measured_values={
                            "eye_width_ui": eye_width,
                            "eye_height_mv": eye_height,
                            "margin_right_ui": sweep.margin_right_ui,
                            "margin_left_ui": sweep.margin_left_ui,
                            "margin_up_mv": sweep.margin_up_mv,
                            "margin_down_mv": sweep.margin_down_mv,
                        },
                        duration_ms=dur,
                        port_number=port_number,
                        lane=lane_idx,
                    )
                except Exception as exc:
                    dur = _elapsed_ms(t0)
                    result = self._make_result(
                        step,
                        StepStatus.ERROR,
                        message=f"Lane {lane_idx} sweep failed: {exc}",
                        criticality=StepCriticality.HIGH,
                        duration_ms=dur,
                        port_number=port_number,
                        lane=lane_idx,
                    )
                    all_pass = False

                yield result
                steps.append(result)
        finally:
            try:
                engine.close()
            except Exception:
                logger.warning("margining_engine_close_failed", port=port_number)

        # --- Aggregate results ---
        step = "Aggregate results"
        yield self._make_running(step)
        t0 = time.monotonic()

        if all_pass:
            agg_status = StepStatus.PASS
            msg = f"All {num_lanes} lane(s) meet PAM4 margin thresholds"
        elif worst_margin < _PAM4_MIN_MARGIN_UI:
            agg_status = StepStatus.FAIL
            msg = f"Lane {worst_lane} has insufficient margin: {worst_margin:.4f} UI"
        else:
            agg_status = StepStatus.WARN
            msg = f"Worst margin: lane {worst_lane} at {worst_margin:.4f} UI"

        dur = _elapsed_ms(t0)
        result = self._make_result(
            step,
            agg_status,
            message=msg,
            criticality=StepCriticality.CRITICAL,
            measured_values={
                "worst_lane": worst_lane,
                "worst_margin_ui": worst_margin if worst_margin != float("inf") else 0,
            },
            duration_ms=dur,
            port_number=port_number,
        )
        yield result
        steps.append(result)

        return self._make_summary(steps, start_time, params, device_id)


def _elapsed_ms(t0: float) -> float:
    return round((time.monotonic() - t0) * 1000, 2)
