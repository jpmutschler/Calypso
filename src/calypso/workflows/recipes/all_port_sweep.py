"""All Port Sweep recipe -- enumerates every port and reports link state."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.core.port_manager import PortManager
from calypso.models.port import PortRole
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


class AllPortSweep(Recipe):
    """Sweep all switch ports and report link state for each one."""

    @property
    def recipe_id(self) -> str:
        return "all_port_sweep"

    @property
    def name(self) -> str:
        return "All Port Sweep"

    @property
    def description(self) -> str:
        return "Enumerate all ports and report link status, width, and speed"

    @property
    def category(self) -> RecipeCategory:
        return RecipeCategory.LINK_HEALTH

    @property
    def estimated_duration_s(self) -> int:
        return 15

    @property
    def parameters(self) -> list[RecipeParameter]:
        return [
            RecipeParameter(
                name="min_link_width",
                label="Minimum Link Width",
                description="Minimum expected negotiated link width for PASS",
                param_type="int",
                default=1,
                min_value=1,
                max_value=16,
                unit="lanes",
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
        min_link_width: int = int(kwargs.get("min_link_width", 1))
        device_id: str = str(kwargs.get("device_id", ""))

        # Step 1: Enumerate ports
        step_name = "Enumerate ports"
        yield self._make_running(step_name)
        t0 = time.monotonic()

        try:
            pm = PortManager(dev, dev_key)
            port_statuses = pm.get_all_port_statuses()
        except Exception as exc:
            logger.error("all_port_sweep_enumerate_failed", error=str(exc))
            result = self._make_result(
                step_name,
                StepStatus.ERROR,
                message=f"Port enumeration failed: {exc}",
                criticality=StepCriticality.CRITICAL,
                duration_ms=_elapsed_ms(t0),
            )
            steps.append(result)
            yield result
            return self._make_summary(steps, start_time, kwargs, device_id)

        result = self._make_result(
            step_name,
            StepStatus.PASS,
            message=f"Discovered {len(port_statuses)} ports",
            criticality=StepCriticality.HIGH,
            measured_values={"port_count": len(port_statuses)},
            duration_ms=_elapsed_ms(t0),
        )
        steps.append(result)
        yield result

        # Step per port
        for port in port_statuses:
            if self._is_cancelled(cancel):
                skip = self._make_result(
                    f"Port {port.port_number}",
                    StepStatus.SKIP,
                    message="Cancelled",
                    criticality=StepCriticality.LOW,
                )
                steps.append(skip)
                yield skip
                break

            port_step = f"Port {port.port_number}"
            yield self._make_running(port_step)
            t1 = time.monotonic()

            measured: dict[str, object] = {
                "is_link_up": port.is_link_up,
                "link_width": port.link_width,
                "link_speed": str(port.link_speed),
                "role": str(port.role),
            }

            if port.role == PortRole.MANAGEMENT:
                status = StepStatus.PASS
                criticality = StepCriticality.INFO
                message = f"Management port (width={port.link_width})"
            elif port.is_link_up:
                if port.link_width >= min_link_width:
                    status = StepStatus.PASS
                    criticality = StepCriticality.MEDIUM
                    message = f"UP x{port.link_width} @ {port.link_speed}"
                else:
                    status = StepStatus.WARN
                    criticality = StepCriticality.HIGH
                    message = f"UP but width {port.link_width} < min {min_link_width}"
            else:
                status = StepStatus.WARN
                criticality = StepCriticality.LOW
                message = f"DOWN (role={port.role})"

            port_result = self._make_result(
                port_step,
                status,
                message=message,
                criticality=criticality,
                measured_values=measured,
                duration_ms=_elapsed_ms(t1),
                port_number=port.port_number,
            )
            steps.append(port_result)
            yield port_result

        return self._make_summary(steps, start_time, kwargs, device_id)


def _elapsed_ms(t0: float) -> float:
    """Compute elapsed milliseconds since *t0*."""
    return round((time.monotonic() - t0) * 1000, 2)
