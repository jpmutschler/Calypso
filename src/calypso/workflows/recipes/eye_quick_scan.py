"""Eye quick scan recipe -- sweep lane margining on multiple lanes."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.core.lane_margining import LaneMarginingEngine
from calypso.core.pcie_config import PcieConfigReader
from calypso.utils.logging import get_logger
from calypso.workflows.base import Recipe
from calypso.workflows.thresholds import get_eye_thresholds
from calypso.workflows.models import (
    RecipeCategory,
    RecipeParameter,
    RecipeResult,
    RecipeSummary,
    StepCriticality,
    StepStatus,
)

logger = get_logger(__name__)


class EyeQuickScanRecipe(Recipe):
    """Sweep lane margining per lane and assess signal eye quality."""

    @property
    def recipe_id(self) -> str:
        return "eye_quick_scan"

    @property
    def name(self) -> str:
        return "Eye Quick Scan"

    @property
    def description(self) -> str:
        return "Sweep lane margining on each lane and assess eye width/height"

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
                description="Target port for eye scan",
                param_type="int",
                default=0,
                min_value=0,
                max_value=143,
            ),
            RecipeParameter(
                name="num_lanes",
                label="Number of Lanes",
                description="How many lanes to sweep",
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
        num_lanes: int = int(kwargs.get("num_lanes", 4))

        device_id: str = str(kwargs.get("device_id", ""))
        params = {"port_number": port_number, "num_lanes": num_lanes}

        try:
            engine = LaneMarginingEngine(dev, dev_key, port_number)
        except Exception as exc:
            step = "Sweep lane 0"
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Failed to initialise margining engine: {exc}",
                criticality=StepCriticality.CRITICAL,
                port_number=port_number,
            )
            yield self._make_running(step)
            yield result
            steps.append(result)
            return self._make_summary(steps, start_time, params, device_id)

        # Read link operating conditions before sweep
        try:
            eye_reader = PcieConfigReader(dev, dev_key)
            eye_link = eye_reader.get_link_status()
            eye_link_speed = eye_link.current_speed
            eye_link_width = eye_link.current_width
        except Exception:
            eye_link_speed = "Unknown"
            eye_link_width = 0

        is_pam4 = self._is_gen6_flit(dev, dev_key)
        thresholds = get_eye_thresholds(is_pam4=is_pam4)

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
                    dur = round((time.monotonic() - t0) * 1000, 2)

                    eye_width = sweep.eye_width_ui
                    eye_height = sweep.eye_height_mv

                    if eye_width >= thresholds.pass_ui:
                        status = StepStatus.PASS
                        msg = f"Eye OK: width={eye_width:.4f} UI, height={eye_height:.2f} mV"
                    elif eye_width >= thresholds.warn_ui:
                        status = StepStatus.WARN
                        msg = f"Marginal eye: width={eye_width:.4f} UI, height={eye_height:.2f} mV"
                    else:
                        status = StepStatus.FAIL
                        msg = f"Poor eye: width={eye_width:.4f} UI, height={eye_height:.2f} mV"

                    result = self._make_result(
                        step,
                        status,
                        message=msg,
                        criticality=StepCriticality.HIGH,
                        measured_values={
                            "eye_width_ui": eye_width,
                            "eye_height_mv": eye_height,
                            "margin_right_ui": sweep.margin_right_ui,
                            "margin_left_ui": sweep.margin_left_ui,
                            "margin_up_mv": sweep.margin_up_mv,
                            "margin_down_mv": sweep.margin_down_mv,
                            "link_speed": eye_link_speed,
                            "link_width": eye_link_width,
                        },
                        duration_ms=dur,
                        port_number=port_number,
                        lane=lane_idx,
                    )
                except Exception as exc:
                    dur = round((time.monotonic() - t0) * 1000, 2)
                    result = self._make_result(
                        step,
                        StepStatus.ERROR,
                        message=f"Lane {lane_idx} sweep failed: {exc}",
                        criticality=StepCriticality.HIGH,
                        duration_ms=dur,
                        port_number=port_number,
                        lane=lane_idx,
                    )

                yield result
                steps.append(result)
        finally:
            try:
                engine.close()
            except Exception:
                logger.warning("margining_engine_close_failed", port=port_number)

        return self._make_summary(steps, start_time, params, device_id)
