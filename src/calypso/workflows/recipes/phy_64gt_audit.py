"""PHY 64GT Audit recipe -- verify 64GT/s link capability and EQ status."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.core.pcie_config import PcieConfigReader
from calypso.core.phy_monitor import PhyMonitor
from calypso.utils.logging import get_logger
from calypso.models.phy import TX_PRESETS_8GT, TxPreset
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


class Phy64gtAuditRecipe(Recipe):
    """Verify 64GT/s link capability, current operating speed, and EQ status."""

    @property
    def recipe_id(self) -> str:
        return "phy_64gt_audit"

    @property
    def name(self) -> str:
        return "PHY 64GT Audit"

    @property
    def description(self) -> str:
        return "Verify 64GT/s capability, operating speed, and EQ completion"

    @property
    def category(self) -> RecipeCategory:
        return RecipeCategory.SIGNAL_INTEGRITY

    @property
    def requires_link_up(self) -> bool:
        return True

    @property
    def estimated_duration_s(self) -> int:
        return 10

    @property
    def parameters(self) -> list[RecipeParameter]:
        return [
            RecipeParameter(
                name="port_number",
                label="Port Number",
                description="Target port for 64GT audit",
                param_type="int",
                default=0,
                min_value=0,
                max_value=143,
            ),
            RecipeParameter(
                name="expect_64gt",
                label="Expect 64GT",
                description="Fail if 64GT/s is not supported",
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
        expect_64gt: bool = bool(kwargs.get("expect_64gt", True))
        device_id: str = str(kwargs.get("device_id", ""))
        params = {"port_number": port_number, "expect_64gt": expect_64gt}

        reader = PcieConfigReader(dev, dev_key)
        phy = PhyMonitor(dev, dev_key, port_number)

        # --- Step 1: Read link capabilities ---
        step = "Read link capabilities"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            link_caps = reader.get_link_capabilities()
            speeds = phy.get_supported_speeds()
            dur = _elapsed_ms(t0)
            measured: dict[str, object] = {}
            if link_caps is not None:
                measured["max_link_speed"] = link_caps.max_link_speed
                measured["max_link_width"] = link_caps.max_link_width
            measured["gen6_supported"] = speeds.gen6
            measured["gen5_supported"] = speeds.gen5
            measured["gen4_supported"] = speeds.gen4
            measured["gen3_supported"] = speeds.gen3

            result = self._make_result(
                step,
                StepStatus.PASS,
                message=f"Capabilities read (Gen6={speeds.gen6})",
                criticality=StepCriticality.MEDIUM,
                measured_values=measured,
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Capability read failed: {exc}",
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

        # --- Step 2: Verify 64GT support ---
        step = "Verify 64GT support"
        yield self._make_running(step)
        t0 = time.monotonic()
        dur = _elapsed_ms(t0)

        if speeds.gen6:
            result = self._make_result(
                step,
                StepStatus.PASS,
                message="64GT/s (Gen6) is supported",
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
                port_number=port_number,
            )
        elif expect_64gt:
            result = self._make_result(
                step,
                StepStatus.FAIL,
                message="64GT/s not supported but expected",
                criticality=StepCriticality.CRITICAL,
                duration_ms=dur,
                port_number=port_number,
            )
        else:
            result = self._make_result(
                step,
                StepStatus.WARN,
                message="64GT/s not supported",
                criticality=StepCriticality.MEDIUM,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if self._is_cancelled(cancel):
            return self._make_summary(steps, start_time, params, device_id)

        # --- Step 3: Read current link status ---
        step = "Read current link status"
        yield self._make_running(step)
        t0 = time.monotonic()
        is_at_64gt = False
        negotiated_width: int | None = None
        try:
            link = reader.get_link_status()
            negotiated_width = link.current_width
            dur = _elapsed_ms(t0)
            current_speed = link.current_speed or ""
            is_at_64gt = "64" in current_speed

            if is_at_64gt:
                link_status = StepStatus.PASS
                msg = f"Operating at 64GT/s (x{link.current_width})"
            elif speeds.gen6:
                link_status = StepStatus.WARN
                msg = f"Capable of 64GT/s but operating at {current_speed}"
            else:
                link_status = StepStatus.PASS
                msg = f"Operating at {current_speed} (Gen6 not supported)"

            result = self._make_result(
                step,
                link_status,
                message=msg,
                criticality=StepCriticality.HIGH,
                measured_values={
                    "current_speed": current_speed,
                    "current_width": link.current_width,
                    "is_at_64gt": is_at_64gt,
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
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if self._is_cancelled(cancel):
            return self._make_summary(steps, start_time, params, device_id)

        # --- Step 4: Read 64GT EQ status ---
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
                    criticality=StepCriticality.MEDIUM,
                    duration_ms=dur,
                    port_number=port_number,
                )
            else:
                flit_supported = getattr(eq_64, "flit_mode_supported", None)
                if eq_64.complete:
                    eq_status = StepStatus.PASS
                    msg = f"64GT EQ complete (flit_mode_supported={flit_supported})"
                else:
                    eq_status = StepStatus.FAIL if is_at_64gt else StepStatus.WARN
                    msg = f"64GT EQ incomplete (flit_mode_supported={flit_supported})"

                result = self._make_result(
                    step,
                    eq_status,
                    message=msg,
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

        if self._is_cancelled(cancel):
            return self._make_summary(steps, start_time, params, device_id)

        # --- Step 5: Read comparison EQ (16GT + 32GT) ---
        step = "Read comparison EQ"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            eq_16 = phy.get_eq_status_16gt()
            eq_32 = phy.get_eq_status_32gt()
            dur = _elapsed_ms(t0)
            measured = {}
            if eq_16 is not None:
                measured["eq_16gt_complete"] = eq_16.complete
            if eq_32 is not None:
                measured["eq_32gt_complete"] = eq_32.complete
            result = self._make_result(
                step,
                StepStatus.PASS,
                message="Comparison EQ statuses read",
                criticality=StepCriticality.INFO,
                measured_values=measured,
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.WARN,
                message=f"Comparison EQ read failed: {exc}",
                criticality=StepCriticality.LOW,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if self._is_cancelled(cancel):
            return self._make_summary(steps, start_time, params, device_id)

        # --- Step 6: Read per-lane TX EQ presets and coefficients ---
        step = "Read TX EQ coefficients"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            # Determine lane count from negotiated width (fallback to 16)
            num_lanes = 16
            if negotiated_width is not None:
                try:
                    num_lanes = int(negotiated_width)
                except (ValueError, TypeError):
                    pass

            eq_settings = phy.get_lane_eq_settings_16gt(num_lanes)
            dur = _elapsed_ms(t0)

            if not eq_settings:
                result = self._make_result(
                    step,
                    StepStatus.SKIP,
                    message="16 GT/s PHY capability not present (no EQ settings)",
                    criticality=StepCriticality.MEDIUM,
                    duration_ms=dur,
                    port_number=port_number,
                )
            else:
                tx_eq_lanes: list[dict[str, object]] = []
                for lane_eq in eq_settings:
                    lane_data: dict[str, object] = {
                        "lane": lane_eq.lane,
                        "downstream_tx_preset": lane_eq.downstream_tx_preset.value,
                        "upstream_tx_preset": lane_eq.upstream_tx_preset.value,
                        "downstream_rx_hint": lane_eq.downstream_rx_hint.value,
                        "upstream_rx_hint": lane_eq.upstream_rx_hint.value,
                    }

                    ds_preset = lane_eq.downstream_tx_preset
                    us_preset = lane_eq.upstream_tx_preset

                    if isinstance(ds_preset, TxPreset) and ds_preset in TX_PRESETS_8GT:
                        ds_coeff = TX_PRESETS_8GT[ds_preset]
                        lane_data["downstream_pre_cursor"] = ds_coeff.pre_cursor
                        lane_data["downstream_cursor"] = ds_coeff.cursor
                        lane_data["downstream_post_cursor"] = ds_coeff.post_cursor

                    if isinstance(us_preset, TxPreset) and us_preset in TX_PRESETS_8GT:
                        us_coeff = TX_PRESETS_8GT[us_preset]
                        lane_data["upstream_pre_cursor"] = us_coeff.pre_cursor
                        lane_data["upstream_cursor"] = us_coeff.cursor
                        lane_data["upstream_post_cursor"] = us_coeff.post_cursor

                    tx_eq_lanes.append(lane_data)

                result = self._make_result(
                    step,
                    StepStatus.PASS,
                    message=f"TX EQ read for {len(eq_settings)} lanes",
                    criticality=StepCriticality.MEDIUM,
                    measured_values={"tx_eq_lanes": tx_eq_lanes},
                    duration_ms=dur,
                    port_number=port_number,
                )
        except Exception as exc:
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.WARN,
                message=f"TX EQ read failed: {exc}",
                criticality=StepCriticality.MEDIUM,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        # --- Step 7: Summary ---
        step = "Summary"
        yield self._make_running(step)
        t0 = time.monotonic()

        if is_at_64gt and eq_64 is not None and eq_64.complete:
            final_status = StepStatus.PASS
            msg = "64GT/s operating with EQ complete"
        elif speeds.gen6 and not is_at_64gt:
            final_status = StepStatus.WARN
            msg = "64GT/s capable but not operating at 64GT/s"
        elif eq_64 is not None and not eq_64.complete and is_at_64gt:
            final_status = StepStatus.FAIL
            msg = "At 64GT/s but EQ incomplete"
        else:
            final_status = StepStatus.PASS
            msg = "PHY audit complete"

        dur = _elapsed_ms(t0)
        result = self._make_result(
            step,
            final_status,
            message=msg,
            criticality=StepCriticality.CRITICAL,
            measured_values={
                "is_at_64gt": is_at_64gt,
                "gen6_supported": speeds.gen6,
            },
            duration_ms=dur,
            port_number=port_number,
        )
        yield result
        steps.append(result)

        return self._make_summary(steps, start_time, params, device_id)


def _elapsed_ms(t0: float) -> float:
    return round((time.monotonic() - t0) * 1000, 2)
