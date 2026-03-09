"""Ordered set audit recipe -- capture and analyze SKP/EIEOS patterns at Gen6."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.core.ptrace import PTraceEngine
from calypso.models.ptrace import (
    PTraceCaptureCfg,
    PTraceDirection,
    PTracePostTriggerCfg,
    PTraceTriggerCfg,
)
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

# SKP ordered set expected insertion rate: ~1 per 370 symbols (PCIe 6.1 §4.2.7)
_SKP_RATE_MIN = 0.001  # minimum fraction of trace entries that should be SKP
_SKP_RATE_MAX = 0.05  # upper bound for reasonable SKP rate


class OrderedSetAuditRecipe(Recipe):
    """Capture PTrace traffic and analyze ordered set (SKP/EIEOS) patterns."""

    @property
    def recipe_id(self) -> str:
        return "ordered_set_audit"

    @property
    def name(self) -> str:
        return "Ordered Set Audit"

    @property
    def description(self) -> str:
        return "Capture and analyze SKP/EIEOS ordered set patterns for Gen6 compliance"

    @property
    def category(self) -> RecipeCategory:
        return RecipeCategory.SIGNAL_INTEGRITY

    @property
    def requires_link_up(self) -> bool:
        return True

    @property
    def estimated_duration_s(self) -> int:
        return 20

    @property
    def parameters(self) -> list[RecipeParameter]:
        return [
            RecipeParameter(
                name="port_number",
                label="Port Number",
                description="Target port for ordered set audit",
                param_type="int",
                default=0,
                min_value=0,
                max_value=143,
            ),
            RecipeParameter(
                name="capture_duration_s",
                label="Capture Duration",
                description="How long to capture PTrace traffic per direction",
                param_type="float",
                default=5.0,
                min_value=1.0,
                max_value=30.0,
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
        capture_duration_s: float = float(kwargs.get("capture_duration_s", 5.0))
        device_id: str = str(kwargs.get("device_id", ""))

        params = {
            "port_number": port_number,
            "capture_duration_s": capture_duration_s,
        }

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
                    message="Link is not at Gen6 64GT/s — ordered set audit targets Flit mode",
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

        # --- Step 2: Capture ingress PTrace ---
        ingress_result = yield from self._capture_direction(
            dev,
            dev_key,
            port_number,
            capture_duration_s,
            cancel,
            PTraceDirection.INGRESS,
            "ingress",
            steps,
        )

        if ingress_result is None or ingress_result.status == StepStatus.ERROR:
            return self._make_summary(steps, start_time, params, device_id)

        if self._is_cancelled(cancel):
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return self._make_summary(steps, start_time, params, device_id)

        # --- Step 3: Capture egress PTrace ---
        egress_result = yield from self._capture_direction(
            dev,
            dev_key,
            port_number,
            capture_duration_s,
            cancel,
            PTraceDirection.EGRESS,
            "egress",
            steps,
        )

        if egress_result is None or egress_result.status == StepStatus.ERROR:
            return self._make_summary(steps, start_time, params, device_id)

        # --- Step 4: Analyze SKP patterns ---
        step = "Analyze SKP patterns"
        yield self._make_running(step)
        t0 = time.monotonic()

        ingress_mv = ingress_result.measured_values
        egress_mv = egress_result.measured_values

        ingress_total = int(ingress_mv.get("entry_count", 0))
        egress_total = int(egress_mv.get("entry_count", 0))
        ingress_skp = int(ingress_mv.get("skp_count", 0))
        egress_skp = int(egress_mv.get("skp_count", 0))

        total_entries = ingress_total + egress_total
        total_skp = ingress_skp + egress_skp
        skp_rate = total_skp / total_entries if total_entries > 0 else 0.0

        if total_entries == 0:
            skp_status = StepStatus.WARN
            skp_msg = "No trace entries captured — cannot assess SKP rate"
        elif skp_rate < _SKP_RATE_MIN:
            skp_status = StepStatus.WARN
            skp_msg = f"SKP rate {skp_rate:.4f} below minimum {_SKP_RATE_MIN}"
        elif skp_rate > _SKP_RATE_MAX:
            skp_status = StepStatus.WARN
            skp_msg = f"SKP rate {skp_rate:.4f} above expected maximum {_SKP_RATE_MAX}"
        else:
            skp_status = StepStatus.PASS
            skp_msg = f"SKP insertion rate {skp_rate:.4f} within expected range"

        dur = _elapsed_ms(t0)
        result = self._make_result(
            step,
            skp_status,
            message=skp_msg,
            criticality=StepCriticality.HIGH,
            measured_values={
                "total_entries": total_entries,
                "total_skp": total_skp,
                "skp_rate": round(skp_rate, 6),
                "ingress_skp": ingress_skp,
                "egress_skp": egress_skp,
            },
            duration_ms=dur,
            port_number=port_number,
        )
        yield result
        steps.append(result)

        # --- Step 5: Analyze EIEOS patterns ---
        step = "Analyze EIEOS patterns"
        yield self._make_running(step)
        t0 = time.monotonic()

        ingress_eieos = int(ingress_mv.get("eieos_count", 0))
        egress_eieos = int(egress_mv.get("eieos_count", 0))
        total_eieos = ingress_eieos + egress_eieos

        if total_eieos > 0:
            eieos_status = StepStatus.PASS
            eieos_msg = (
                f"EIEOS detected: {total_eieos} total "
                f"(ingress={ingress_eieos}, egress={egress_eieos})"
            )
        else:
            eieos_status = StepStatus.PASS
            eieos_msg = "No EIEOS ordered sets detected (normal for stable L0 link)"

        dur = _elapsed_ms(t0)
        result = self._make_result(
            step,
            eieos_status,
            message=eieos_msg,
            criticality=StepCriticality.MEDIUM,
            measured_values={
                "total_eieos": total_eieos,
                "ingress_eieos": ingress_eieos,
                "egress_eieos": egress_eieos,
            },
            duration_ms=dur,
            port_number=port_number,
        )
        yield result
        steps.append(result)

        # --- Step 6: Summary ---
        step = "Summary"
        yield self._make_running(step)
        t0 = time.monotonic()

        has_issues = any(s.status in (StepStatus.FAIL, StepStatus.WARN) for s in steps)
        if any(s.status == StepStatus.FAIL for s in steps):
            summary_status = StepStatus.FAIL
            summary_msg = "Ordered set audit found failures"
        elif has_issues:
            summary_status = StepStatus.WARN
            summary_msg = "Ordered set audit completed with warnings"
        else:
            summary_status = StepStatus.PASS
            summary_msg = "Ordered set audit passed — SKP/EIEOS patterns nominal"

        dur = _elapsed_ms(t0)
        result = self._make_result(
            step,
            summary_status,
            message=summary_msg,
            criticality=StepCriticality.HIGH,
            measured_values={
                "skp_rate": round(skp_rate, 6),
                "total_skp": total_skp,
                "total_eieos": total_eieos,
                "total_entries": total_entries,
            },
            duration_ms=dur,
            port_number=port_number,
        )
        yield result
        steps.append(result)

        return self._make_summary(steps, start_time, params, device_id)

    def _capture_direction(
        self,
        dev: PLX_DEVICE_OBJECT,
        dev_key: PLX_DEVICE_KEY,
        port_number: int,
        capture_duration_s: float,
        cancel: dict[str, bool],
        direction: PTraceDirection,
        direction_label: str,
        steps: list[RecipeResult],
    ) -> Generator[RecipeResult, None, RecipeResult | None]:
        """Capture PTrace in one direction and return analyzed result."""
        step = f"Capture {direction_label} PTrace"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            engine = PTraceEngine(dev, dev_key, port_number)
            capture_cfg = PTraceCaptureCfg(
                direction=direction,
                port_number=port_number,
            )
            trigger_cfg = PTraceTriggerCfg()
            post_cfg = PTracePostTriggerCfg()

            engine.full_configure(
                direction=direction,
                capture=capture_cfg,
                trigger=trigger_cfg,
                post_trigger=post_cfg,
            )

            engine.start_capture(direction)

            elapsed = 0.0
            while elapsed < capture_duration_s:
                if self._is_cancelled(cancel):
                    break
                chunk = min(0.5, capture_duration_s - elapsed)
                time.sleep(chunk)
                elapsed += chunk

            engine.stop_capture(direction)

            buffer_result = engine.read_buffer(direction)
            entries = buffer_result.entries if hasattr(buffer_result, "entries") else []

            # Count ordered sets by inspecting DW occupancy patterns
            skp_count = 0
            eieos_count = 0
            for entry in entries:
                dw = getattr(entry, "dw_occupancy", 0)
                # SKP ordered sets typically have specific DW patterns
                if dw in (1, 2):
                    skp_count += 1
                elif dw == 3:
                    eieos_count += 1

            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message=f"Captured {buffer_result.total_rows_read} {direction_label} entries",
                criticality=StepCriticality.MEDIUM,
                measured_values={
                    "entry_count": buffer_result.total_rows_read,
                    "skp_count": skp_count,
                    "eieos_count": eieos_count,
                    "triggered": buffer_result.triggered,
                    "wrapped": buffer_result.tbuf_wrapped,
                },
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = _elapsed_ms(t0)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"{direction_label.title()} capture failed: {exc}",
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)
        return result


def _elapsed_ms(t0: float) -> float:
    return round((time.monotonic() - t0) * 1000, 2)
