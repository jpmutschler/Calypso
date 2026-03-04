"""SerDes diagnostics recipe -- read TX/RX coefficients and error counts per lane."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
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


class SerDesDiagnosticsRecipe(Recipe):
    """Read SerDes diagnostic data for all lanes on a port."""

    @property
    def recipe_id(self) -> str:
        return "serdes_diagnostics"

    @property
    def name(self) -> str:
        return "SerDes Diagnostics"

    @property
    def description(self) -> str:
        return "Read SerDes TX/RX coefficients and error counts per lane"

    @property
    def category(self) -> RecipeCategory:
        return RecipeCategory.SIGNAL_INTEGRITY

    @property
    def estimated_duration_s(self) -> int:
        return 15

    @property
    def parameters(self) -> list[RecipeParameter]:
        return [
            RecipeParameter(
                name="port_number",
                label="Port Number",
                description="Target port for SerDes diagnostics",
                param_type="int",
                default=0,
                min_value=0,
                max_value=143,
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
        params = {"port_number": port_number}

        step = "Read SerDes diagnostics"
        yield self._make_running(step)
        t0 = time.monotonic()

        try:
            phy = PhyMonitor(dev, dev_key, port_number)
            diags = phy.get_all_serdes_diag()
            dur = round((time.monotonic() - t0) * 1000, 2)

            lanes_with_errors = [d for d in diags if d.utp_error_count > 0]
            lane_data: list[dict[str, object]] = []
            for idx, d in enumerate(diags):
                lane_data.append(
                    {
                        "lane": idx,
                        "lane_select": d.lane_select,
                        "utp_sync": d.utp_sync,
                        "utp_error_count": d.utp_error_count,
                        "utp_expected_data": d.utp_expected_data,
                        "utp_actual_data": d.utp_actual_data,
                    }
                )

            if lanes_with_errors:
                status = StepStatus.WARN
                msg = f"SerDes errors on {len(lanes_with_errors)} lane(s) out of {len(diags)}"
            else:
                status = StepStatus.PASS
                msg = f"All {len(diags)} lane(s) clean -- zero errors"

            result = self._make_result(
                step,
                status,
                message=msg,
                criticality=StepCriticality.HIGH,
                measured_values={
                    "lane_count": len(diags),
                    "lanes_with_errors": len(lanes_with_errors),
                    "lanes": lane_data,
                },
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"SerDes diagnostics failed: {exc}",
                criticality=StepCriticality.CRITICAL,
                duration_ms=dur,
                port_number=port_number,
            )

        yield result
        steps.append(result)

        return self._make_summary(steps, start_time, params)
