"""Multi-speed BER recipe -- set link speed then run BER soak at each PCIe gen."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.core.pcie_config import PcieConfigReader
from calypso.core.phy_monitor import PhyMonitor
from calypso.hardware.atlas3_phy import UserTestPattern
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

_BER_PASS_THRESHOLD = 1e-12
_BER_WARN_THRESHOLD = 1e-9

# (label, link_speed_code)
_ALL_SPEEDS: list[tuple[str, int]] = [
    ("8GT", 3),
    ("16GT", 4),
    ("32GT", 5),
    ("64GT", 6),
]

_SPEED_SETS: dict[str, list[tuple[str, int]]] = {
    "all": _ALL_SPEEDS,
    "gen3_gen4": [("8GT", 3), ("16GT", 4)],
    "gen5_gen6": [("32GT", 5), ("64GT", 6)],
}

# Default 16-byte UTP pattern
_DEFAULT_PATTERN = bytes([0xAA, 0x55] * 8)

# Time to wait for link to retrain at new speed
_SPEED_CHANGE_SETTLE_S = 2.0


class MultiSpeedBerRecipe(Recipe):
    """Run BER soak at multiple PCIe link speeds to validate signal integrity."""

    @property
    def recipe_id(self) -> str:
        return "multi_speed_ber"

    @property
    def name(self) -> str:
        return "Multi-Speed BER Test"

    @property
    def description(self) -> str:
        return "Set link speed then run BER soak at each PCIe generation"

    @property
    def category(self) -> RecipeCategory:
        return RecipeCategory.ERROR_TESTING

    @property
    def estimated_duration_s(self) -> int:
        return 180

    @property
    def parameters(self) -> list[RecipeParameter]:
        return [
            RecipeParameter(
                name="port_number",
                label="Port Number",
                description="Target port for multi-speed BER",
                param_type="int",
                default=0,
                min_value=0,
                max_value=143,
            ),
            RecipeParameter(
                name="ber_duration_s",
                label="BER Duration per Speed",
                description="Soak duration at each speed",
                param_type="float",
                default=10.0,
                min_value=5.0,
                max_value=120.0,
                unit="s",
            ),
            RecipeParameter(
                name="speeds",
                label="Speed Set",
                description="Which link speeds to test",
                param_type="choice",
                default="all",
                choices=["all", "gen3_gen4", "gen5_gen6"],
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
        ber_duration_s: float = float(kwargs.get("ber_duration_s", 10.0))
        speeds_key: str = str(kwargs.get("speeds", "all"))

        params = {
            "port_number": port_number,
            "ber_duration_s": ber_duration_s,
            "speeds": speeds_key,
        }

        speed_list = _SPEED_SETS.get(speeds_key, _ALL_SPEEDS)

        # Initialise hardware helpers
        try:
            config = PcieConfigReader(dev, dev_key)
            phy = PhyMonitor(dev, dev_key, port_number)
        except Exception as exc:
            step = f"BER at Gen{speed_list[0][1]}"
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Hardware init failed: {exc}",
                criticality=StepCriticality.CRITICAL,
                port_number=port_number,
            )
            yield self._make_running(step)
            yield result
            steps.append(result)
            return self._make_summary(steps, start_time, params)

        pattern = UserTestPattern(data=_DEFAULT_PATTERN)

        for speed_label, speed_code in speed_list:
            if self._is_cancelled(cancel):
                skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
                yield skip
                steps.append(skip)
                break

            step = f"BER at {speed_label} (Gen{speed_code})"
            yield self._make_running(step)
            t0 = time.monotonic()

            try:
                # Set target link speed and retrain
                config.set_target_link_speed(speed_code)
                config.retrain_link()
                time.sleep(_SPEED_CHANGE_SETTLE_S)

                # Prepare UTP
                phy.prepare_utp_test(pattern)

                # Soak
                elapsed = 0.0
                while elapsed < ber_duration_s:
                    if self._is_cancelled(cancel):
                        break
                    chunk = min(1.0, ber_duration_s - elapsed)
                    time.sleep(chunk)
                    elapsed += chunk

                # Collect results
                utp_results = phy.collect_utp_results()
                dur = round((time.monotonic() - t0) * 1000, 2)

                total_errors = sum(r.error_count for r in utp_results)
                all_synced = all(r.synced for r in utp_results)

                if not all_synced:
                    status = StepStatus.FAIL
                    msg = f"{speed_label}: sync failure on some lanes"
                elif total_errors == 0:
                    status = StepStatus.PASS
                    msg = f"{speed_label}: zero errors across all lanes"
                else:
                    status = StepStatus.WARN
                    msg = f"{speed_label}: {total_errors} error(s) detected"

                result = self._make_result(
                    step,
                    status,
                    message=msg,
                    criticality=StepCriticality.CRITICAL,
                    measured_values={
                        "speed": speed_label,
                        "speed_code": speed_code,
                        "total_errors": total_errors,
                        "all_synced": all_synced,
                        "soak_duration_s": round(elapsed, 1),
                        "lanes_tested": len(utp_results),
                    },
                    duration_ms=dur,
                    port_number=port_number,
                )
            except Exception as exc:
                dur = round((time.monotonic() - t0) * 1000, 2)
                result = self._make_result(
                    step,
                    StepStatus.ERROR,
                    message=f"{speed_label} BER test failed: {exc}",
                    criticality=StepCriticality.HIGH,
                    duration_ms=dur,
                    port_number=port_number,
                )

            yield result
            steps.append(result)

        return self._make_summary(steps, start_time, params)
