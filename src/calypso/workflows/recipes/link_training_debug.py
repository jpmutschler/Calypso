"""Link training debug recipe -- retrain a port and observe LTSSM/AER behaviour."""

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

_POLL_INTERVAL_MS = 50


class LinkTrainingDebugRecipe(Recipe):
    """Force a link retrain and capture LTSSM transitions with AER checks."""

    @property
    def recipe_id(self) -> str:
        return "link_training_debug"

    @property
    def name(self) -> str:
        return "Link Training Debug"

    @property
    def description(self) -> str:
        return "Retrain a port link and monitor LTSSM transitions with AER error checks"

    @property
    def category(self) -> RecipeCategory:
        return RecipeCategory.LINK_HEALTH

    @property
    def estimated_duration_s(self) -> int:
        return 60

    @property
    def parameters(self) -> list[RecipeParameter]:
        return [
            RecipeParameter(
                name="port_number",
                label="Port Number",
                description="Target port to retrain",
                param_type="int",
                default=0,
                min_value=0,
                max_value=143,
            ),
            RecipeParameter(
                name="timeout_s",
                label="Timeout",
                description="Maximum time to monitor LTSSM after retrain",
                param_type="float",
                default=10.0,
                min_value=2.0,
                max_value=60.0,
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
        timeout_s: float = float(kwargs.get("timeout_s", 10.0))
        device_id: str = str(kwargs.get("device_id", ""))

        # --- Step 1: Read initial LTSSM ---
        step = "Read initial LTSSM"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            tracer = LtssmTracer(dev, dev_key, port_number)
            snapshot = tracer.get_snapshot()
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message=f"LTSSM state: {snapshot.ltssm_state_name}",
                criticality=StepCriticality.INFO,
                measured_values={
                    "ltssm_state": snapshot.ltssm_state_name,
                    "recovery_count": snapshot.recovery_count,
                },
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Failed to read LTSSM: {exc}",
                criticality=StepCriticality.CRITICAL,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if result.status == StepStatus.ERROR:
            return self._make_summary(
                steps,
                start_time,
                {"port_number": port_number, "timeout_s": timeout_s},
                device_id,
            )

        if self._is_cancelled(cancel):
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return self._make_summary(
                steps,
                start_time,
                {"port_number": port_number, "timeout_s": timeout_s},
                device_id,
            )

        # --- Step 2: Clear AER errors ---
        step = "Clear AER errors"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            config = PcieConfigReader(dev, dev_key)
            config.clear_aer_errors()
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message="AER errors cleared",
                criticality=StepCriticality.MEDIUM,
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.WARN,
                message=f"Could not clear AER: {exc}",
                criticality=StepCriticality.MEDIUM,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if self._is_cancelled(cancel):
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return self._make_summary(
                steps,
                start_time,
                {"port_number": port_number, "timeout_s": timeout_s},
                device_id,
            )

        # --- Step 3: Retrain link ---
        step = "Retrain link"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            config.retrain_link()
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message="Link retrain initiated",
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Retrain failed: {exc}",
                criticality=StepCriticality.CRITICAL,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if result.status == StepStatus.ERROR:
            return self._make_summary(
                steps,
                start_time,
                {"port_number": port_number, "timeout_s": timeout_s},
                device_id,
            )

        if self._is_cancelled(cancel):
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return self._make_summary(
                steps,
                start_time,
                {"port_number": port_number, "timeout_s": timeout_s},
                device_id,
            )

        # --- Step 4: Monitor LTSSM transitions ---
        step = "Monitor LTSSM transitions"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            transitions: list[dict[str, object]] = []
            prev_state = ""
            deadline = time.monotonic() + timeout_s

            while time.monotonic() < deadline:
                if self._is_cancelled(cancel):
                    break
                snap = tracer.get_snapshot()
                if snap.ltssm_state_name != prev_state:
                    transitions.append(
                        {
                            "state": snap.ltssm_state_name,
                            "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
                            "recovery_count": snap.recovery_count,
                        }
                    )
                    prev_state = snap.ltssm_state_name
                time.sleep(_POLL_INTERVAL_MS / 1000)

            dur = round((time.monotonic() - t0) * 1000, 2)
            status = StepStatus.PASS if transitions else StepStatus.WARN
            result = self._make_result(
                step,
                status,
                message=f"Observed {len(transitions)} LTSSM transition(s)",
                criticality=StepCriticality.HIGH,
                measured_values={
                    "transition_count": len(transitions),
                    "final_state": prev_state,
                    "transitions": transitions,
                },
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Monitoring failed: {exc}",
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if self._is_cancelled(cancel):
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return self._make_summary(
                steps,
                start_time,
                {"port_number": port_number, "timeout_s": timeout_s},
                device_id,
            )

        # --- Step 5: Check post-retrain AER ---
        step = "Check post-retrain AER"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            aer = config.get_aer_status()
            dur = round((time.monotonic() - t0) * 1000, 2)
            if aer is None:
                result = self._make_result(
                    step,
                    StepStatus.WARN,
                    message="AER capability not found",
                    criticality=StepCriticality.MEDIUM,
                    duration_ms=dur,
                    port_number=port_number,
                )
            else:
                has_uncorr = aer.uncorrectable.raw_value != 0
                has_corr = aer.correctable.raw_value != 0
                if has_uncorr:
                    status = StepStatus.FAIL
                    msg = "Uncorrectable AER errors detected after retrain"
                elif has_corr:
                    status = StepStatus.WARN
                    msg = "Correctable AER errors detected after retrain"
                else:
                    status = StepStatus.PASS
                    msg = "No AER errors after retrain"

                result = self._make_result(
                    step,
                    status,
                    message=msg,
                    criticality=StepCriticality.HIGH,
                    measured_values={
                        "uncorrectable_raw": aer.uncorrectable.raw_value,
                        "correctable_raw": aer.correctable.raw_value,
                        "first_error_pointer": aer.first_error_pointer,
                    },
                    duration_ms=dur,
                    port_number=port_number,
                )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"AER check failed: {exc}",
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if self._is_cancelled(cancel):
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return self._make_summary(
                steps,
                start_time,
                {"port_number": port_number, "timeout_s": timeout_s},
                device_id,
            )

        # --- Step 6: Check post-retrain equalization ---
        step = "Check post-retrain equalization"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            phy = PhyMonitor(dev, dev_key, port_number)
            eq_16gt = phy.get_eq_status_16gt()
            eq_32gt = phy.get_eq_status_32gt()
            eq_64gt = phy.get_eq_status_64gt()
            dur = round((time.monotonic() - t0) * 1000, 2)

            eq_values: dict[str, object] = {}
            eq_messages: list[str] = []

            if eq_16gt is not None:
                eq_values["eq_16gt_complete"] = eq_16gt.complete
                eq_values["eq_16gt_phase1"] = eq_16gt.phase1_success
                eq_values["eq_16gt_phase2"] = eq_16gt.phase2_success
                eq_values["eq_16gt_phase3"] = eq_16gt.phase3_success
                eq_values["eq_16gt_raw"] = eq_16gt.raw_value
                eq_messages.append(
                    f"16GT: complete={eq_16gt.complete}, "
                    f"phases={eq_16gt.phase1_success}/{eq_16gt.phase2_success}/{eq_16gt.phase3_success}"
                )

            if eq_32gt is not None:
                eq_values["eq_32gt_complete"] = eq_32gt.complete
                eq_values["eq_32gt_phase1"] = eq_32gt.phase1_success
                eq_values["eq_32gt_phase2"] = eq_32gt.phase2_success
                eq_values["eq_32gt_phase3"] = eq_32gt.phase3_success
                eq_values["eq_32gt_no_eq_needed"] = eq_32gt.no_eq_needed
                eq_values["eq_32gt_raw_status"] = eq_32gt.raw_status
                eq_messages.append(
                    f"32GT: complete={eq_32gt.complete}, "
                    f"phases={eq_32gt.phase1_success}/{eq_32gt.phase2_success}/{eq_32gt.phase3_success}"
                )

            if eq_64gt is not None:
                eq_values["eq_64gt_complete"] = eq_64gt.complete
                eq_values["eq_64gt_phase1"] = eq_64gt.phase1_success
                eq_values["eq_64gt_phase2"] = eq_64gt.phase2_success
                eq_values["eq_64gt_phase3"] = eq_64gt.phase3_success
                eq_values["eq_64gt_flit_mode_supported"] = eq_64gt.flit_mode_supported
                eq_values["eq_64gt_no_eq_needed"] = eq_64gt.no_eq_needed
                eq_values["eq_64gt_raw_status"] = eq_64gt.raw_status
                eq_messages.append(
                    f"64GT: complete={eq_64gt.complete}, "
                    f"phases={eq_64gt.phase1_success}/{eq_64gt.phase2_success}/{eq_64gt.phase3_success}, "
                    f"flit={eq_64gt.flit_mode_supported}"
                )

            if not eq_messages:
                msg = "No EQ capabilities found"
                status = StepStatus.WARN
            else:
                msg = "; ".join(eq_messages)
                status = StepStatus.PASS

            result = self._make_result(
                step,
                status,
                message=msg,
                criticality=StepCriticality.MEDIUM,
                measured_values=eq_values,
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"EQ status check failed: {exc}",
                criticality=StepCriticality.MEDIUM,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if self._is_cancelled(cancel):
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return self._make_summary(
                steps,
                start_time,
                {"port_number": port_number, "timeout_s": timeout_s},
                device_id,
            )

        # --- Step 7: Check post-retrain link status ---
        step = "Check post-retrain link status"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            link_status = config.get_link_status()
            dur = round((time.monotonic() - t0) * 1000, 2)

            # Compare to pre-retrain snapshot if available
            pre_state = (
                steps[0].measured_values.get("ltssm_state", "unknown")
                if steps[0].measured_values
                else "unknown"
            )

            msg = (
                f"Speed: {link_status.current_speed}, "
                f"Width: x{link_status.current_width}, "
                f"Training: {link_status.link_training}, "
                f"DLL Active: {link_status.dll_link_active}, "
                f"Pre-retrain LTSSM: {pre_state}"
            )

            if link_status.link_training:
                status = StepStatus.WARN
            elif not link_status.dll_link_active:
                status = StepStatus.FAIL
            else:
                status = StepStatus.PASS

            result = self._make_result(
                step,
                status,
                message=msg,
                criticality=StepCriticality.HIGH,
                measured_values={
                    "current_speed": link_status.current_speed,
                    "current_width": link_status.current_width,
                    "target_speed": link_status.target_speed,
                    "link_training": link_status.link_training,
                    "dll_link_active": link_status.dll_link_active,
                    "pre_retrain_ltssm": pre_state,
                },
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Link status check failed: {exc}",
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if self._is_cancelled(cancel):
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return self._make_summary(
                steps,
                start_time,
                {"port_number": port_number, "timeout_s": timeout_s},
                device_id,
            )

        # --- Step 7b: Verify Flit mode negotiation (Gen6 only) ---
        step = "Verify Flit negotiation"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            is_gen6 = self._is_gen6_flit(dev, dev_key)
            dur = round((time.monotonic() - t0) * 1000, 2)
            if not is_gen6:
                result = self._make_result(
                    step,
                    StepStatus.SKIP,
                    message="Link not at 64GT/s — Flit negotiation check skipped",
                    criticality=StepCriticality.INFO,
                    duration_ms=dur,
                    port_number=port_number,
                )
            else:
                # Read EQ 64GT status for Flit mode flags
                try:
                    phy = PhyMonitor(dev, dev_key, port_number)
                    eq_64gt = phy.get_eq_status_64gt()
                except Exception:
                    eq_64gt = None

                flit_supported = eq_64gt.flit_mode_supported if eq_64gt else None
                eq_complete = eq_64gt.complete if eq_64gt else None

                flit_values: dict[str, object] = {
                    "flit_mode_supported": flit_supported,
                    "eq_64gt_complete": eq_complete,
                }

                if flit_supported is True and eq_complete is True:
                    flit_status = StepStatus.PASS
                    flit_msg = "Flit mode negotiated and active at 64GT/s"
                elif flit_supported is False:
                    flit_status = StepStatus.WARN
                    flit_msg = "64GT/s active but Flit mode not supported by endpoint"
                elif eq_complete is False:
                    flit_status = StepStatus.FAIL
                    flit_msg = "64GT/s EQ not complete — Flit mode negotiation may be incomplete"
                else:
                    flit_status = StepStatus.WARN
                    flit_msg = "Flit mode status could not be fully determined"

                result = self._make_result(
                    step,
                    flit_status,
                    message=flit_msg,
                    criticality=StepCriticality.HIGH,
                    measured_values=flit_values,
                    duration_ms=dur,
                    port_number=port_number,
                )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.WARN,
                message=f"Flit negotiation check failed: {exc}",
                criticality=StepCriticality.MEDIUM,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if self._is_cancelled(cancel):
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return self._make_summary(
                steps,
                start_time,
                {"port_number": port_number, "timeout_s": timeout_s},
                device_id,
            )

        # --- Step 8 (Gen6 only): Check Flit Error Log post-retrain ---
        step = "Check Flit Error Log post-retrain"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            flit_status = config.get_flit_logging_status()
            dur = round((time.monotonic() - t0) * 1000, 2)

            if flit_status is None:
                result = self._make_result(
                    step,
                    StepStatus.SKIP,
                    message="Flit Logging capability not present (non-Gen6 link)",
                    criticality=StepCriticality.INFO,
                    duration_ms=dur,
                    port_number=port_number,
                )
            else:
                entries = flit_status.error_log_entries
                valid_entries = [e for e in entries if e.valid]
                uncorrectable_count = sum(1 for e in valid_entries if e.fec_uncorrectable)

                flit_values: dict[str, object] = {
                    "cap_offset": flit_status.cap_offset,
                    "total_entries": len(entries),
                    "valid_entries": len(valid_entries),
                    "uncorrectable_count": uncorrectable_count,
                    "error_counter_enabled": flit_status.error_counter.enable,
                    "flit_counter": flit_status.error_counter.counter,
                }

                if valid_entries:
                    flit_values["entries"] = [
                        {
                            "link_width": e.link_width,
                            "flit_offset": e.flit_offset,
                            "consecutive_errors": e.consecutive_errors,
                            "unrecognized_flit": e.unrecognized_flit,
                            "fec_uncorrectable": e.fec_uncorrectable,
                            "syndrome_0": e.syndrome_0,
                            "syndrome_1": e.syndrome_1,
                            "syndrome_2": e.syndrome_2,
                        }
                        for e in valid_entries
                    ]

                if uncorrectable_count > 0:
                    status = StepStatus.FAIL
                    msg = (
                        f"{uncorrectable_count} FEC uncorrectable flit error(s) "
                        f"in {len(valid_entries)} log entries"
                    )
                elif valid_entries:
                    status = StepStatus.WARN
                    msg = f"{len(valid_entries)} flit error log entries (all correctable)"
                else:
                    status = StepStatus.PASS
                    msg = "No flit error log entries after retrain"

                result = self._make_result(
                    step,
                    status,
                    message=msg,
                    criticality=StepCriticality.HIGH,
                    measured_values=flit_values,
                    duration_ms=dur,
                    port_number=port_number,
                )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Flit error log check failed: {exc}",
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        return self._make_summary(
            steps,
            start_time,
            {"port_number": port_number, "timeout_s": timeout_s},
            device_id,
        )
