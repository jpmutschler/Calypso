"""Packet exerciser test recipe -- send TLPs and verify completion status."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.core.packet_exerciser import PacketExerciserEngine
from calypso.hardware.pktexer_regs import TlpType
from calypso.models.packet_exerciser import TlpConfig
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

_POLL_INTERVAL_S = 0.5
_COMPLETION_TIMEOUT_S = 10.0


class PacketExerciserTestRecipe(Recipe):
    """Send TLPs via the packet exerciser and verify clean completion."""

    @property
    def recipe_id(self) -> str:
        return "packet_exerciser_test"

    @property
    def name(self) -> str:
        return "Packet Exerciser Test"

    @property
    def description(self) -> str:
        return "Configure the packet exerciser, send TLPs, and verify completion"

    @property
    def category(self) -> RecipeCategory:
        return RecipeCategory.DEBUG

    @property
    def estimated_duration_s(self) -> int:
        return 20

    @property
    def parameters(self) -> list[RecipeParameter]:
        return [
            RecipeParameter(
                name="port_number",
                label="Port Number",
                description="Port for packet exerciser",
                param_type="int",
                default=0,
                min_value=0,
                max_value=143,
            ),
            RecipeParameter(
                name="packet_count",
                label="Packet Count",
                description="Number of TLPs to send",
                param_type="int",
                default=100,
                min_value=1,
                max_value=10000,
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
        packet_count: int = int(kwargs.get("packet_count", 100))
        params = {"port_number": port_number, "packet_count": packet_count}

        # --- Step 1: Configure exerciser ---
        step = "Configure exerciser"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            engine = PacketExerciserEngine(dev, dev_key, port_number)
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message="Packet exerciser initialised",
                criticality=StepCriticality.MEDIUM,
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Exerciser init failed: {exc}",
                criticality=StepCriticality.CRITICAL,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if result.status == StepStatus.ERROR:
            return self._make_summary(steps, start_time, params)

        if self._is_cancelled(cancel):
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return self._make_summary(steps, start_time, params)

        # --- Step 2: Send TLPs ---
        step = "Send TLPs"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            # Build a list of simple MRd TLP configs
            tlp_configs = [
                TlpConfig(
                    tlp_type=TlpType.MR32,
                    address=0x0,
                    length_dw=1,
                )
                for _ in range(min(packet_count, 256))  # HW RAM limit per thread
            ]
            engine.send_tlps(tlp_configs)
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message=f"Sent {len(tlp_configs)} TLP(s)",
                criticality=StepCriticality.MEDIUM,
                measured_values={"tlps_sent": len(tlp_configs)},
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"TLP send failed: {exc}",
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if result.status == StepStatus.ERROR:
            return self._make_summary(steps, start_time, params)

        if self._is_cancelled(cancel):
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return self._make_summary(steps, start_time, params)

        # --- Step 3: Read status ---
        step = "Read status"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            # Wait for threads to finish
            deadline = time.monotonic() + _COMPLETION_TIMEOUT_S
            final_status = None
            while time.monotonic() < deadline:
                if self._is_cancelled(cancel):
                    break
                final_status = engine.read_status()
                all_done = all(t.done for t in final_status.threads if t.running or t.done)
                if all_done and not any(t.running for t in final_status.threads):
                    break
                time.sleep(_POLL_INTERVAL_S)

            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message="Exerciser status read",
                criticality=StepCriticality.MEDIUM,
                measured_values={
                    "completion_received": final_status.completion_received
                    if final_status
                    else False,
                    "ecrc_error": final_status.completion_ecrc_error if final_status else False,
                },
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Status read failed: {exc}",
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        if result.status == StepStatus.ERROR:
            return self._make_summary(steps, start_time, params)

        # --- Step 4: Verify completion ---
        step = "Verify completion"
        yield self._make_running(step)
        t0 = time.monotonic()

        has_errors = False
        if final_status:
            has_errors = final_status.completion_ecrc_error or final_status.completion_ep

        dur = round((time.monotonic() - t0) * 1000, 2)
        if has_errors:
            result = self._make_result(
                step,
                StepStatus.FAIL,
                message="Packet exerciser completed with errors",
                criticality=StepCriticality.CRITICAL,
                measured_values={
                    "ecrc_error": final_status.completion_ecrc_error if final_status else False,
                    "error_poisoned": final_status.completion_ep if final_status else False,
                },
                duration_ms=dur,
                port_number=port_number,
            )
        else:
            result = self._make_result(
                step,
                StepStatus.PASS,
                message="Packet exerciser completed cleanly",
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        # Stop the exerciser
        try:
            engine.stop()
        except Exception:
            logger.warning("exerciser_stop_failed", port=port_number)

        return self._make_summary(steps, start_time, params)
