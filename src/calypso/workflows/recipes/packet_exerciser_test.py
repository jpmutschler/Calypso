"""Packet exerciser test recipe -- send TLPs and verify completion status."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.core.packet_exerciser import PacketExerciserEngine
from calypso.core.pcie_config import PcieConfigReader
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

_TLP_TYPE_MAP: dict[str, TlpType] = {
    "MR32": TlpType.MR32,
    "MR64": TlpType.MR64,
    "MW32": TlpType.MW32,
    "MW64": TlpType.MW64,
}


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
            RecipeParameter(
                name="tlp_type",
                label="TLP Type",
                description="Type of TLP to send",
                param_type="choice",
                default="MR32",
                choices=["MR32", "MR64", "MW32", "MW64"],
            ),
            RecipeParameter(
                name="address",
                label="Address",
                description="Target address for TLPs",
                param_type="int",
                default=0,
                min_value=0,
                max_value=0xFFFFFFFF,
            ),
            RecipeParameter(
                name="length_dw",
                label="Length (DW)",
                description="TLP payload length in DWORDs",
                param_type="int",
                default=1,
                min_value=1,
                max_value=256,
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
        tlp_type_str: str = str(kwargs.get("tlp_type", "MR32"))
        address: int = int(kwargs.get("address", 0))
        length_dw: int = int(kwargs.get("length_dw", 1))
        device_id: str = str(kwargs.get("device_id", ""))
        params = {
            "port_number": port_number,
            "packet_count": packet_count,
            "tlp_type": tlp_type_str,
            "address": address,
            "length_dw": length_dw,
        }

        tlp_type = _TLP_TYPE_MAP.get(tlp_type_str, TlpType.MR32)
        config = PcieConfigReader(dev, dev_key)

        # --- Step 1: Pre-test AER clear ---
        step = "Clear AER errors"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            config.clear_aer_errors()
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message="AER errors cleared before test",
                criticality=StepCriticality.MEDIUM,
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.WARN,
                message=f"AER clear failed: {exc}",
                criticality=StepCriticality.LOW,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        # --- Step 2: Configure exerciser ---
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
            return self._make_summary(steps, start_time, params, device_id)

        if self._is_cancelled(cancel):
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return self._make_summary(steps, start_time, params, device_id)

        # --- Step 3: Send TLPs ---
        step = "Send TLPs"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            tlp_configs = [
                TlpConfig(
                    tlp_type=tlp_type,
                    address=address,
                    length_dw=length_dw,
                )
                for _ in range(min(packet_count, 256))
            ]
            engine.send_tlps(tlp_configs)
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message=f"Sent {len(tlp_configs)} {tlp_type_str} TLP(s)",
                criticality=StepCriticality.MEDIUM,
                measured_values={
                    "tlps_sent": len(tlp_configs),
                    "tlp_type": tlp_type_str,
                    "address": address,
                    "length_dw": length_dw,
                },
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
            return self._make_summary(steps, start_time, params, device_id)

        if self._is_cancelled(cancel):
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return self._make_summary(steps, start_time, params, device_id)

        # --- Step 4: Read status ---
        step = "Read status"
        yield self._make_running(step)
        t0 = time.monotonic()
        final_status = None
        try:
            deadline = time.monotonic() + _COMPLETION_TIMEOUT_S
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
            return self._make_summary(steps, start_time, params, device_id)

        # --- Step 5: Verify completion ---
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

        # --- Step 6: Post-test AER check ---
        step = "Post-test AER check"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            aer = config.get_aer_status()
            dur = round((time.monotonic() - t0) * 1000, 2)
            if aer is None:
                result = self._make_result(
                    step,
                    StepStatus.SKIP,
                    message="AER not present",
                    criticality=StepCriticality.LOW,
                    duration_ms=dur,
                    port_number=port_number,
                )
            else:
                has_uncorr = aer.uncorrectable.raw_value != 0
                has_corr = aer.correctable.raw_value != 0
                if has_uncorr:
                    aer_status = StepStatus.FAIL
                    aer_msg = "Uncorrectable AER errors after exerciser test"
                elif has_corr:
                    aer_status = StepStatus.WARN
                    aer_msg = "Correctable AER errors after exerciser test"
                else:
                    aer_status = StepStatus.PASS
                    aer_msg = "No AER errors after exerciser test"
                result = self._make_result(
                    step,
                    aer_status,
                    message=aer_msg,
                    criticality=StepCriticality.HIGH,
                    measured_values={
                        "uncorrectable_raw": aer.uncorrectable.raw_value,
                        "correctable_raw": aer.correctable.raw_value,
                    },
                    duration_ms=dur,
                    port_number=port_number,
                )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.WARN,
                message=f"Post-test AER check failed: {exc}",
                criticality=StepCriticality.LOW,
                duration_ms=dur,
                port_number=port_number,
            )
        yield result
        steps.append(result)

        return self._make_summary(steps, start_time, params, device_id)
