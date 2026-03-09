"""SerDes diagnostics recipe -- read TX/RX coefficients and error counts per lane."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.core.pcie_config import PcieConfigReader
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
        return "Read SerDes TX/RX coefficients, EQ settings, and error counts per lane"

    @property
    def category(self) -> RecipeCategory:
        return RecipeCategory.SIGNAL_INTEGRITY

    @property
    def requires_link_up(self) -> bool:
        return True

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
            RecipeParameter(
                name="num_lanes",
                label="Number of Lanes",
                description="Number of lanes to read EQ settings for",
                param_type="int",
                default=16,
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
        num_lanes: int = int(kwargs.get("num_lanes", 16))
        device_id: str = str(kwargs.get("device_id", ""))
        params = {"port_number": port_number, "num_lanes": num_lanes}

        # --- Step 1: Read SerDes diagnostics ---
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

        if result.status == StepStatus.ERROR or self._is_cancelled(cancel):
            return self._make_summary(steps, start_time, params, device_id)

        # --- Step 2: Read TX EQ coefficients ---
        step = "Read TX EQ coefficients"
        yield self._make_running(step)
        t0 = time.monotonic()

        try:
            eq_settings = phy.get_lane_eq_settings_16gt(num_lanes)
            dur = round((time.monotonic() - t0) * 1000, 2)

            eq_data: list[dict[str, object]] = []
            for idx, eq in enumerate(eq_settings):
                eq_data.append(
                    {
                        "lane": idx,
                        "upstream_tx_preset": getattr(eq, "upstream_tx_preset", None),
                        "downstream_tx_preset": getattr(eq, "downstream_tx_preset", None),
                        "upstream_rx_preset_hint": getattr(eq, "upstream_rx_preset_hint", None),
                        "downstream_rx_preset_hint": getattr(eq, "downstream_rx_preset_hint", None),
                    }
                )

            result = self._make_result(
                step,
                StepStatus.PASS,
                message=f"Read EQ settings for {len(eq_settings)} lane(s)",
                criticality=StepCriticality.MEDIUM,
                measured_values={
                    "lanes_read": len(eq_settings),
                    "eq_settings": eq_data,
                },
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.WARN,
                message=f"EQ coefficient read failed: {exc}",
                criticality=StepCriticality.LOW,
                duration_ms=dur,
                port_number=port_number,
            )

        yield result
        steps.append(result)

        if self._is_cancelled(cancel):
            return self._make_summary(steps, start_time, params, device_id)

        # --- Step 3: Read FBER lane counters (Gen6 only) ---
        if self._is_gen6_flit(dev, dev_key):
            step = "Read FBER lane counters"
            yield self._make_running(step)
            t0 = time.monotonic()

            try:
                reader = PcieConfigReader(dev, dev_key)
                fber = reader.get_fber_status()
                dur = round((time.monotonic() - t0) * 1000, 2)

                if fber is None:
                    result = self._make_result(
                        step,
                        StepStatus.SKIP,
                        message="FBER not available",
                        criticality=StepCriticality.LOW,
                        duration_ms=dur,
                        port_number=port_number,
                    )
                else:
                    total_fber = sum(fber.lane_counters)
                    if total_fber > 0:
                        fber_status = StepStatus.WARN
                        msg = f"FBER errors detected: {total_fber} total"
                    else:
                        fber_status = StepStatus.PASS
                        msg = "No FBER errors"

                    result = self._make_result(
                        step,
                        fber_status,
                        message=msg,
                        criticality=StepCriticality.HIGH,
                        measured_values={
                            "fber_total": total_fber,
                            "flit_counter": fber.flit_counter,
                            "lane_counters": fber.lane_counters,
                        },
                        duration_ms=dur,
                        port_number=port_number,
                    )
            except Exception as exc:
                dur = round((time.monotonic() - t0) * 1000, 2)
                result = self._make_result(
                    step,
                    StepStatus.WARN,
                    message=f"FBER read failed: {exc}",
                    criticality=StepCriticality.LOW,
                    duration_ms=dur,
                    port_number=port_number,
                )

            yield result
            steps.append(result)

        return self._make_summary(steps, start_time, params, device_id)
