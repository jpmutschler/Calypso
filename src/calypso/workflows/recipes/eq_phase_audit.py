"""EQ Phase Audit recipe -- read and analyze equalization status across all speeds."""

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


class EqPhaseAuditRecipe(Recipe):
    """Audit equalization phase completion and per-lane EQ settings."""

    @property
    def recipe_id(self) -> str:
        return "eq_phase_audit"

    @property
    def name(self) -> str:
        return "EQ Phase Audit"

    @property
    def description(self) -> str:
        return "Read and analyze equalization status across 16GT/32GT/64GT speeds"

    @property
    def category(self) -> RecipeCategory:
        return RecipeCategory.LINK_HEALTH

    @property
    def estimated_duration_s(self) -> int:
        return 10

    @property
    def parameters(self) -> list[RecipeParameter]:
        return [
            RecipeParameter(
                name="port_number",
                label="Port Number",
                description="Target port for EQ audit",
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

        phy = PhyMonitor(dev, dev_key, port_number)
        reader = PcieConfigReader(dev, dev_key)

        # --- Step 1: Read link status ---
        step = "Read link status"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            link = reader.get_link_status()
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message=f"Link: x{link.current_width} @ {link.current_speed}",
                criticality=StepCriticality.INFO,
                measured_values={
                    "current_speed": link.current_speed,
                    "current_width": link.current_width,
                },
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Link status read failed: {exc}",
                criticality=StepCriticality.CRITICAL,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)
        if result.status == StepStatus.ERROR:
            return self._make_summary(steps, start_time, params, device_id)

        if self._is_cancelled(cancel):
            return self._make_summary(steps, start_time, params, device_id)

        eq_incomplete = False

        # --- Step 2: Read 16GT EQ status ---
        step = "Read 16GT EQ status"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            eq_16 = phy.get_eq_status_16gt()
            dur = _elapsed_ms(t0)
            if eq_16 is None:
                result = self._make_result(
                    step,
                    StepStatus.SKIP,
                    message="16GT EQ capability not present",
                    criticality=StepCriticality.LOW,
                    duration_ms=dur,
                    port_number=port_number,
                )
            else:
                if not eq_16.complete:
                    eq_incomplete = True
                result = self._make_result(
                    step,
                    StepStatus.PASS if eq_16.complete else StepStatus.WARN,
                    message=(
                        f"16GT EQ: complete={eq_16.complete}, "
                        f"ph1={eq_16.phase1_success}, "
                        f"ph2={eq_16.phase2_success}, "
                        f"ph3={eq_16.phase3_success}"
                    ),
                    criticality=StepCriticality.MEDIUM,
                    measured_values={
                        "eq_complete": eq_16.complete,
                        "phase1_ok": eq_16.phase1_success,
                        "phase2_ok": eq_16.phase2_success,
                        "phase3_ok": eq_16.phase3_success,
                    },
                    duration_ms=dur,
                    port_number=port_number,
                )
        except Exception as exc:
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.WARN,
                message=f"16GT EQ read failed: {exc}",
                criticality=StepCriticality.LOW,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if self._is_cancelled(cancel):
            return self._make_summary(steps, start_time, params, device_id)

        # --- Step 3: Read 16GT per-lane EQ settings ---
        step = "Read 16GT per-lane EQ settings"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            eq_lanes = phy.get_lane_eq_settings_16gt(num_lanes)
            dur = _elapsed_ms(t0)

            lane_data: list[dict[str, object]] = []
            for idx, eq in enumerate(eq_lanes):
                lane_data.append(
                    {
                        "lane": idx,
                        "upstream_tx_preset": getattr(eq, "upstream_tx_preset", None),
                        "downstream_tx_preset": getattr(eq, "downstream_tx_preset", None),
                        "upstream_rx_preset_hint": getattr(eq, "upstream_rx_preset_hint", None),
                        "downstream_rx_preset_hint": getattr(eq, "downstream_rx_preset_hint", None),
                    }
                )

            # Check for unusual presets (all same vs varying)
            tx_presets = [getattr(eq, "downstream_tx_preset", 0) for eq in eq_lanes]
            unique_presets = set(tx_presets)

            result = self._make_result(
                step,
                StepStatus.PASS,
                message=f"Read EQ for {len(eq_lanes)} lanes, {len(unique_presets)} unique TX presets",
                criticality=StepCriticality.MEDIUM,
                measured_values={
                    "lanes_read": len(eq_lanes),
                    "unique_tx_presets": len(unique_presets),
                    "eq_settings": lane_data,
                },
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.WARN,
                message=f"Per-lane EQ read failed: {exc}",
                criticality=StepCriticality.LOW,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if self._is_cancelled(cancel):
            return self._make_summary(steps, start_time, params, device_id)

        # --- Step 4: Read 32GT EQ status ---
        step = "Read 32GT EQ status"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            eq_32 = phy.get_eq_status_32gt()
            dur = _elapsed_ms(t0)
            if eq_32 is None:
                result = self._make_result(
                    step,
                    StepStatus.SKIP,
                    message="32GT EQ capability not present",
                    criticality=StepCriticality.LOW,
                    duration_ms=dur,
                    port_number=port_number,
                )
            else:
                if not eq_32.complete:
                    eq_incomplete = True
                result = self._make_result(
                    step,
                    StepStatus.PASS if eq_32.complete else StepStatus.WARN,
                    message=(
                        f"32GT EQ: complete={eq_32.complete}, "
                        f"ph1={eq_32.phase1_success}, "
                        f"ph2={eq_32.phase2_success}, "
                        f"ph3={eq_32.phase3_success}"
                    ),
                    criticality=StepCriticality.MEDIUM,
                    measured_values={
                        "eq_complete": eq_32.complete,
                        "phase1_ok": eq_32.phase1_success,
                        "phase2_ok": eq_32.phase2_success,
                        "phase3_ok": eq_32.phase3_success,
                    },
                    duration_ms=dur,
                    port_number=port_number,
                )
        except Exception as exc:
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.WARN,
                message=f"32GT EQ read failed: {exc}",
                criticality=StepCriticality.LOW,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if self._is_cancelled(cancel):
            return self._make_summary(steps, start_time, params, device_id)

        # --- Step 5: Read 64GT EQ status ---
        step = "Read 64GT EQ status"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            eq_64 = phy.get_eq_status_64gt()
            dur = _elapsed_ms(t0)
            if eq_64 is None:
                result = self._make_result(
                    step,
                    StepStatus.SKIP,
                    message="64GT EQ capability not present",
                    criticality=StepCriticality.LOW,
                    duration_ms=dur,
                    port_number=port_number,
                )
            else:
                if not eq_64.complete:
                    eq_incomplete = True
                flit_supported = getattr(eq_64, "flit_mode_supported", None)
                result = self._make_result(
                    step,
                    StepStatus.PASS if eq_64.complete else StepStatus.WARN,
                    message=(
                        f"64GT EQ: complete={eq_64.complete}, flit_mode_supported={flit_supported}"
                    ),
                    criticality=StepCriticality.HIGH,
                    measured_values={
                        "eq_complete": eq_64.complete,
                        "phase1_ok": eq_64.phase1_success,
                        "phase2_ok": eq_64.phase2_success,
                        "phase3_ok": eq_64.phase3_success,
                        "flit_mode_supported": flit_supported,
                    },
                    duration_ms=dur,
                    port_number=port_number,
                )
        except Exception as exc:
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.WARN,
                message=f"64GT EQ read failed: {exc}",
                criticality=StepCriticality.LOW,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        # --- Step 6: Analyze EQ consistency ---
        step = "Analyze EQ consistency"
        yield self._make_running(step)
        t0 = time.monotonic()

        if eq_incomplete:
            status = StepStatus.FAIL
            msg = "One or more EQ phases incomplete on active link"
        else:
            status = StepStatus.PASS
            msg = "All applicable EQ phases complete"

        dur = _elapsed_ms(t0)
        result = self._make_result(
            step,
            status,
            message=msg,
            criticality=StepCriticality.CRITICAL,
            measured_values={"eq_incomplete": eq_incomplete},
            duration_ms=dur,
            port_number=port_number,
        )
        yield result
        steps.append(result)

        return self._make_summary(steps, start_time, params, device_id)


def _elapsed_ms(t0: float) -> float:
    return round((time.monotonic() - t0) * 1000, 2)
