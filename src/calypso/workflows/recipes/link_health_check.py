"""Link Health Check recipe -- deep health analysis of a single port."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.core.ltssm_trace import LtssmTracer
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


class LinkHealthCheck(Recipe):
    """Deep health check on a single port: link, AER, LTSSM, equalization."""

    @property
    def recipe_id(self) -> str:
        return "link_health_check"

    @property
    def name(self) -> str:
        return "Link Health Check"

    @property
    def description(self) -> str:
        return (
            "Deep health check on a specific port: link status, AER errors, "
            "LTSSM state, recovery counts, and equalization status"
        )

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
                description="Physical port number to check",
                param_type="int",
                default=0,
                min_value=0,
                max_value=143,
            ),
            RecipeParameter(
                name="port_select",
                label="Port Select",
                description="Intra-station port select index (auto-derived if 0)",
                param_type="int",
                default=0,
                min_value=0,
                max_value=15,
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
        device_id: str = str(kwargs.get("device_id", ""))

        # Step 1: Check link status (also captures capabilities)
        result = yield from _step_link_status(self, dev, dev_key, cancel, steps)
        if result is not None and result.status == StepStatus.ERROR:
            return self._make_summary(steps, start_time, kwargs, device_id)

        if self._is_cancelled(cancel):
            return self._make_summary(steps, start_time, kwargs, device_id)

        # Step 2: Check AER errors
        yield from _step_aer_errors(self, dev, dev_key, cancel, steps)

        if self._is_cancelled(cancel):
            return self._make_summary(steps, start_time, kwargs, device_id)

        # Step 3: Read LTSSM state
        yield from _step_ltssm_state(self, dev, dev_key, port_number, cancel, steps)

        if self._is_cancelled(cancel):
            return self._make_summary(steps, start_time, kwargs, device_id)

        # Step 4: Check recovery counts
        yield from _step_recovery_counts(self, dev, dev_key, port_number, cancel, steps)

        if self._is_cancelled(cancel):
            return self._make_summary(steps, start_time, kwargs, device_id)

        # Step 5: Check equalization (including 64GT)
        yield from _step_equalization(self, dev, dev_key, port_number, cancel, steps)

        if self._is_cancelled(cancel):
            return self._make_summary(steps, start_time, kwargs, device_id)

        # Step 6: Check Flit errors (Gen6 only)
        yield from _step_flit_errors(self, dev, dev_key, port_number, cancel, steps)

        return self._make_summary(steps, start_time, kwargs, device_id)


# ---------------------------------------------------------------------------
# Step helpers -- each yields RUNNING + result, appends to steps list
# ---------------------------------------------------------------------------


def _step_link_status(
    recipe: LinkHealthCheck,
    dev: PLX_DEVICE_OBJECT,
    dev_key: PLX_DEVICE_KEY,
    cancel: dict[str, bool],
    steps: list[RecipeResult],
) -> Generator[RecipeResult, None, RecipeResult | None]:
    step_name = "Check link status"
    yield recipe._make_running(step_name)
    t0 = time.monotonic()

    try:
        reader = PcieConfigReader(dev, dev_key)
        link_status = reader.get_link_status()
        link_caps = reader.get_link_capabilities()
    except Exception as exc:
        logger.error("link_health_link_status_failed", error=str(exc))
        result = recipe._make_result(
            step_name,
            StepStatus.ERROR,
            message=f"Failed to read link status: {exc}",
            criticality=StepCriticality.CRITICAL,
            duration_ms=_elapsed_ms(t0),
        )
        steps.append(result)
        yield result
        return result

    is_active = link_status.dll_link_active
    measured: dict[str, object] = {
        "current_speed": link_status.current_speed,
        "current_width": link_status.current_width,
        "target_speed": link_status.target_speed,
        "dll_link_active": is_active,
        "link_training": link_status.link_training,
    }

    # Add capabilities info
    if link_caps is not None:
        measured["max_link_speed"] = link_caps.max_link_speed
        measured["max_link_width"] = link_caps.max_link_width

    if is_active:
        status = StepStatus.PASS
        message = f"Link active: x{link_status.current_width} @ {link_status.current_speed}"

        # Warn if operating below max capability
        if link_caps is not None:
            cap_speed = link_caps.max_link_speed or ""
            cur_speed = link_status.current_speed or ""
            cap_width = link_caps.max_link_width or 0
            cur_width = link_status.current_width or 0
            if cur_width < cap_width:
                status = StepStatus.WARN
                message += f" (width degraded from x{cap_width})"
                measured["width_degraded"] = True
            if _speed_rank(cur_speed) < _speed_rank(cap_speed):
                status = StepStatus.WARN
                message += f" (speed degraded from {cap_speed})"
                measured["speed_degraded"] = True
    else:
        status = StepStatus.FAIL
        message = "DLL link not active"

    result = recipe._make_result(
        step_name,
        status,
        message=message,
        criticality=StepCriticality.CRITICAL,
        measured_values=measured,
        duration_ms=_elapsed_ms(t0),
    )
    steps.append(result)
    yield result
    return result


def _step_aer_errors(
    recipe: LinkHealthCheck,
    dev: PLX_DEVICE_OBJECT,
    dev_key: PLX_DEVICE_KEY,
    cancel: dict[str, bool],
    steps: list[RecipeResult],
) -> Generator[RecipeResult, None, None]:
    step_name = "Check AER errors"
    yield recipe._make_running(step_name)
    t0 = time.monotonic()

    try:
        reader = PcieConfigReader(dev, dev_key)
        aer = reader.get_aer_status()
    except Exception as exc:
        logger.error("link_health_aer_failed", error=str(exc))
        result = recipe._make_result(
            step_name,
            StepStatus.ERROR,
            message=f"Failed to read AER: {exc}",
            criticality=StepCriticality.HIGH,
            duration_ms=_elapsed_ms(t0),
        )
        steps.append(result)
        yield result
        return

    if aer is None:
        result = recipe._make_result(
            step_name,
            StepStatus.SKIP,
            message="AER capability not present",
            criticality=StepCriticality.LOW,
            duration_ms=_elapsed_ms(t0),
        )
        steps.append(result)
        yield result
        return

    uncorr_raw = aer.uncorrectable.raw_value
    corr_raw = aer.correctable.raw_value
    measured: dict[str, object] = {
        "uncorrectable_raw": uncorr_raw,
        "correctable_raw": corr_raw,
        "first_error_pointer": aer.first_error_pointer,
    }

    has_uncorr = uncorr_raw != 0
    has_corr = corr_raw != 0

    if has_uncorr:
        status = StepStatus.FAIL
        message = f"Uncorrectable errors detected (0x{uncorr_raw:08X})"
        criticality = StepCriticality.CRITICAL
    elif has_corr:
        status = StepStatus.WARN
        message = f"Correctable errors detected (0x{corr_raw:08X})"
        criticality = StepCriticality.MEDIUM
    else:
        status = StepStatus.PASS
        message = "No AER errors"
        criticality = StepCriticality.HIGH

    result = recipe._make_result(
        step_name,
        status,
        message=message,
        criticality=criticality,
        measured_values=measured,
        duration_ms=_elapsed_ms(t0),
    )
    steps.append(result)
    yield result


def _step_ltssm_state(
    recipe: LinkHealthCheck,
    dev: PLX_DEVICE_OBJECT,
    dev_key: PLX_DEVICE_KEY,
    port_number: int,
    cancel: dict[str, bool],
    steps: list[RecipeResult],
) -> Generator[RecipeResult, None, None]:
    step_name = "Read LTSSM state"
    yield recipe._make_running(step_name)
    t0 = time.monotonic()

    try:
        tracer = LtssmTracer(dev, dev_key, port_number)
        snapshot = tracer.get_snapshot()
    except Exception as exc:
        logger.error("link_health_ltssm_failed", error=str(exc))
        result = recipe._make_result(
            step_name,
            StepStatus.ERROR,
            message=f"Failed to read LTSSM state: {exc}",
            criticality=StepCriticality.HIGH,
            duration_ms=_elapsed_ms(t0),
            port_number=port_number,
        )
        steps.append(result)
        yield result
        return

    measured: dict[str, object] = {
        "ltssm_state": snapshot.ltssm_state,
        "ltssm_state_name": snapshot.ltssm_state_name,
        "link_speed": snapshot.link_speed,
        "link_speed_name": snapshot.link_speed_name,
        "recovery_count": snapshot.recovery_count,
        "link_down_count": snapshot.link_down_count,
    }

    # L0 is normal operating state (top state 0x3)
    top_state = (snapshot.ltssm_state >> 8) & 0xF
    is_l0 = top_state == 0x3

    if is_l0:
        status = StepStatus.PASS
        message = f"LTSSM in L0 ({snapshot.ltssm_state_name})"
    else:
        status = StepStatus.WARN
        message = f"LTSSM not in L0: {snapshot.ltssm_state_name}"

    result = recipe._make_result(
        step_name,
        status,
        message=message,
        criticality=StepCriticality.HIGH,
        measured_values=measured,
        duration_ms=_elapsed_ms(t0),
        port_number=port_number,
    )
    steps.append(result)
    yield result


def _step_recovery_counts(
    recipe: LinkHealthCheck,
    dev: PLX_DEVICE_OBJECT,
    dev_key: PLX_DEVICE_KEY,
    port_number: int,
    cancel: dict[str, bool],
    steps: list[RecipeResult],
) -> Generator[RecipeResult, None, None]:
    step_name = "Check recovery counts"
    yield recipe._make_running(step_name)
    t0 = time.monotonic()

    try:
        tracer = LtssmTracer(dev, dev_key, port_number)
        recovery_count, rx_eval_count = tracer.read_recovery_count()
    except Exception as exc:
        logger.error("link_health_recovery_failed", error=str(exc))
        result = recipe._make_result(
            step_name,
            StepStatus.ERROR,
            message=f"Failed to read recovery counts: {exc}",
            criticality=StepCriticality.MEDIUM,
            duration_ms=_elapsed_ms(t0),
            port_number=port_number,
        )
        steps.append(result)
        yield result
        return

    measured: dict[str, object] = {
        "recovery_count": recovery_count,
        "rx_eval_count": rx_eval_count,
    }

    if recovery_count > 100:
        status = StepStatus.FAIL
        criticality = StepCriticality.CRITICAL
        message = f"Excessive recoveries: {recovery_count}"
    elif recovery_count > 10:
        status = StepStatus.WARN
        criticality = StepCriticality.HIGH
        message = f"Elevated recovery count: {recovery_count}"
    else:
        status = StepStatus.PASS
        criticality = StepCriticality.MEDIUM
        message = f"Recovery count: {recovery_count}, Rx eval: {rx_eval_count}"

    result = recipe._make_result(
        step_name,
        status,
        message=message,
        criticality=criticality,
        measured_values=measured,
        duration_ms=_elapsed_ms(t0),
        port_number=port_number,
    )
    steps.append(result)
    yield result


def _step_equalization(
    recipe: LinkHealthCheck,
    dev: PLX_DEVICE_OBJECT,
    dev_key: PLX_DEVICE_KEY,
    port_number: int,
    cancel: dict[str, bool],
    steps: list[RecipeResult],
) -> Generator[RecipeResult, None, None]:
    step_name = "Check equalization"
    yield recipe._make_running(step_name)
    t0 = time.monotonic()

    try:
        phy = PhyMonitor(dev, dev_key, port_number)
        eq_16 = phy.get_eq_status_16gt()
        eq_32 = phy.get_eq_status_32gt()
        eq_64 = phy.get_eq_status_64gt()
    except Exception as exc:
        logger.error("link_health_eq_failed", error=str(exc))
        result = recipe._make_result(
            step_name,
            StepStatus.ERROR,
            message=f"Failed to read equalization: {exc}",
            criticality=StepCriticality.MEDIUM,
            duration_ms=_elapsed_ms(t0),
            port_number=port_number,
        )
        steps.append(result)
        yield result
        return

    measured: dict[str, object] = {}
    details_parts: list[str] = []

    if eq_16 is not None:
        measured["eq_16gt_complete"] = eq_16.complete
        measured["eq_16gt_phase1_ok"] = eq_16.phase1_success
        measured["eq_16gt_phase2_ok"] = eq_16.phase2_success
        measured["eq_16gt_phase3_ok"] = eq_16.phase3_success
        details_parts.append(
            f"16GT: complete={eq_16.complete}, "
            f"ph1={eq_16.phase1_success}, "
            f"ph2={eq_16.phase2_success}, "
            f"ph3={eq_16.phase3_success}"
        )
    else:
        details_parts.append("16GT: capability not present")

    if eq_32 is not None:
        measured["eq_32gt_complete"] = eq_32.complete
        measured["eq_32gt_phase1_ok"] = eq_32.phase1_success
        measured["eq_32gt_phase2_ok"] = eq_32.phase2_success
        measured["eq_32gt_phase3_ok"] = eq_32.phase3_success
        details_parts.append(
            f"32GT: complete={eq_32.complete}, "
            f"ph1={eq_32.phase1_success}, "
            f"ph2={eq_32.phase2_success}, "
            f"ph3={eq_32.phase3_success}"
        )
    else:
        details_parts.append("32GT: capability not present")

    if eq_64 is not None:
        measured["eq_64gt_complete"] = eq_64.complete
        measured["eq_64gt_phase1_ok"] = eq_64.phase1_success
        measured["eq_64gt_phase2_ok"] = eq_64.phase2_success
        measured["eq_64gt_phase3_ok"] = eq_64.phase3_success
        measured["eq_64gt_flit_mode_supported"] = getattr(eq_64, "flit_mode_supported", None)
        details_parts.append(
            f"64GT: complete={eq_64.complete}, "
            f"ph1={eq_64.phase1_success}, "
            f"ph2={eq_64.phase2_success}, "
            f"ph3={eq_64.phase3_success}"
        )
    else:
        details_parts.append("64GT: capability not present")

    # Determine status from equalization results
    eq_failed = False
    if eq_16 is not None and not eq_16.complete:
        eq_failed = True
    if eq_32 is not None and not eq_32.complete:
        eq_failed = True
    if eq_64 is not None and not eq_64.complete:
        eq_failed = True

    has_any_eq = eq_16 is not None or eq_32 is not None or eq_64 is not None

    if not has_any_eq:
        status = StepStatus.SKIP
        message = "No equalization capabilities present"
        criticality = StepCriticality.LOW
    elif eq_failed:
        status = StepStatus.WARN
        message = "Equalization incomplete"
        criticality = StepCriticality.HIGH
    else:
        status = StepStatus.PASS
        message = "Equalization complete"
        criticality = StepCriticality.MEDIUM

    result = recipe._make_result(
        step_name,
        status,
        message=message,
        criticality=criticality,
        measured_values=measured,
        duration_ms=_elapsed_ms(t0),
        details="; ".join(details_parts),
        port_number=port_number,
    )
    steps.append(result)
    yield result


def _step_flit_errors(
    recipe: LinkHealthCheck,
    dev: PLX_DEVICE_OBJECT,
    dev_key: PLX_DEVICE_KEY,
    port_number: int,
    cancel: dict[str, bool],
    steps: list[RecipeResult],
) -> Generator[RecipeResult, None, None]:
    """Check Flit Error Log and FBER status (Gen6 only)."""
    # Only run if link is at 64GT/s
    if not recipe._is_gen6_flit(dev, dev_key):
        return

    step_name = "Check Flit errors (Gen6)"
    yield recipe._make_running(step_name)
    t0 = time.monotonic()

    try:
        reader = PcieConfigReader(dev, dev_key)

        # Read Flit Error Log entries
        flit_entries = reader.read_all_flit_error_log_entries()

        # Read FBER status
        fber = reader.get_fber_status()

        dur = _elapsed_ms(t0)

        fec_uncorrectable_count = sum(1 for e in flit_entries if e.fec_uncorrectable)
        fec_correctable_count = len(flit_entries) - fec_uncorrectable_count

        measured: dict[str, object] = {
            "flit_error_log_entries": len(flit_entries),
            "fec_uncorrectable_count": fec_uncorrectable_count,
            "fec_correctable_count": fec_correctable_count,
        }

        if fber is not None:
            fber_total = sum(fber.lane_counters)
            measured["fber_total_errors"] = fber_total
            measured["fber_flit_counter"] = fber.flit_counter
            measured["fber_lane_counters"] = fber.lane_counters
        else:
            fber_total = 0

        if fec_uncorrectable_count > 0:
            status = StepStatus.FAIL
            message = f"FEC uncorrectable errors: {fec_uncorrectable_count}"
        elif len(flit_entries) > 0 or fber_total > 0:
            status = StepStatus.WARN
            message = f"Flit errors: {len(flit_entries)} log entries, {fber_total} FBER lane errors"
        else:
            status = StepStatus.PASS
            message = "No Flit errors detected"

        result = recipe._make_result(
            step_name,
            status,
            message=message,
            criticality=StepCriticality.CRITICAL,
            measured_values=measured,
            duration_ms=dur,
            port_number=port_number,
        )
    except Exception as exc:
        logger.error("link_health_flit_errors_failed", error=str(exc))
        result = recipe._make_result(
            step_name,
            StepStatus.ERROR,
            message=f"Failed to read Flit errors: {exc}",
            criticality=StepCriticality.HIGH,
            duration_ms=_elapsed_ms(t0),
            port_number=port_number,
        )
    steps.append(result)
    yield result


def _elapsed_ms(t0: float) -> float:
    """Compute elapsed milliseconds since *t0*."""
    return round((time.monotonic() - t0) * 1000, 2)


def _speed_rank(speed_str: str) -> int:
    """Return a numeric rank for speed comparison. Higher is faster."""
    if "64" in speed_str:
        return 6
    if "32" in speed_str:
        return 5
    if "16" in speed_str:
        return 4
    if "8.0" in speed_str:
        return 3
    if "5.0" in speed_str:
        return 2
    if "2.5" in speed_str:
        return 1
    return 0
