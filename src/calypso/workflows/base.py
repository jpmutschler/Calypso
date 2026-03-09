"""Abstract base class for recipes.

All recipes implement the generator protocol: yield RecipeResult per step,
return RecipeSummary via StopIteration.value.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.workflows.models import (
    RecipeCategory,
    RecipeParameter,
    RecipeResult,
    RecipeSummary,
    StepCriticality,
    StepStatus,
)


class Recipe(ABC):
    """Abstract base class for all recipes.

    Subclasses implement ``run()`` as a generator that yields
    ``RecipeResult`` for each step.  The final ``RecipeSummary`` is
    returned via ``StopIteration.value`` (i.e. ``return summary``
    at the end of the generator).
    """

    @property
    @abstractmethod
    def recipe_id(self) -> str:
        """Unique identifier for this recipe."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable recipe name."""

    @property
    @abstractmethod
    def description(self) -> str:
        """One-line description of what this recipe does."""

    @property
    @abstractmethod
    def category(self) -> RecipeCategory:
        """Category grouping for the recipe."""

    @property
    def requires_link_up(self) -> bool:
        """Whether this recipe requires the target port link to be active.

        Recipes that perform measurements on live links (signal integrity,
        performance) should override this to return ``True``.  The API layer
        can then reject requests when the port link is down, unless forced.
        """
        return False

    @property
    def estimated_duration_s(self) -> int:
        """Estimated duration in seconds."""
        return 30

    @property
    def parameters(self) -> list[RecipeParameter]:
        """Configurable parameters for this recipe."""
        return []

    @abstractmethod
    def run(
        self,
        dev: PLX_DEVICE_OBJECT,
        dev_key: PLX_DEVICE_KEY,
        cancel: dict[str, bool],
        **kwargs: Any,
    ) -> Generator[RecipeResult, None, RecipeSummary]:
        """Execute the recipe as a generator.

        Yields ``RecipeResult`` for each step (with ``StepStatus.RUNNING``
        before work starts, then the final status after completion).

        Returns ``RecipeSummary`` via the generator return value.

        Args:
            dev: Open PLX device object.
            dev_key: PLX device key with port/bus info.
            cancel: Mutable dict with ``"cancelled"`` bool flag.
            **kwargs: Recipe-specific parameters matching ``self.parameters``.
        """

    # --- Helper methods ---

    def _is_gen6_flit(self, dev: PLX_DEVICE_OBJECT, dev_key: PLX_DEVICE_KEY) -> bool:
        """Check if link is operating at 64 GT/s (Gen6 Flit mode).

        Matches PLX SDK speed string formats: "Gen6", "64 GT/s", "64.0 GT/s".
        """
        from calypso.core.pcie_config import PcieConfigReader

        reader = PcieConfigReader(dev, dev_key)
        link = reader.get_link_status()
        speed = link.current_speed or ""
        return speed == "Gen6" or "64 GT/s" in speed or "64.0" in speed

    def _is_cancelled(self, cancel: dict[str, bool]) -> bool:
        """Check the cancellation flag."""
        return cancel.get("cancelled", False)

    def _make_running(self, step_name: str) -> RecipeResult:
        """Create a RUNNING result to yield before work begins."""
        return RecipeResult(
            step_name=step_name,
            status=StepStatus.RUNNING,
            message=f"Running: {step_name}",
        )

    def _make_result(
        self,
        step_name: str,
        status: StepStatus,
        message: str = "",
        criticality: StepCriticality = StepCriticality.MEDIUM,
        measured_values: dict[str, object] | None = None,
        duration_ms: float = 0.0,
        details: str = "",
        port_number: int | None = None,
        lane: int | None = None,
    ) -> RecipeResult:
        """Create a completed step result."""
        return RecipeResult(
            step_name=step_name,
            status=status,
            message=message,
            criticality=criticality,
            measured_values=measured_values or {},
            duration_ms=duration_ms,
            details=details,
            port_number=port_number,
            lane=lane,
            timestamp=datetime.now(tz=timezone.utc).isoformat(),
        )

    def _make_summary(
        self,
        steps: list[RecipeResult],
        start_time: float,
        parameters: dict[str, object] | None = None,
        device_id: str = "",
    ) -> RecipeSummary:
        """Build a RecipeSummary from collected step results."""
        # Filter out RUNNING status entries (those are progress markers)
        completed = [s for s in steps if s.status != StepStatus.RUNNING]
        duration_ms = round((time.monotonic() - start_time) * 1000, 2)

        total_pass = sum(1 for s in completed if s.status == StepStatus.PASS)
        total_fail = sum(1 for s in completed if s.status == StepStatus.FAIL)
        total_warn = sum(1 for s in completed if s.status == StepStatus.WARN)
        total_skip = sum(1 for s in completed if s.status == StepStatus.SKIP)
        total_error = sum(1 for s in completed if s.status == StepStatus.ERROR)

        if total_fail > 0 or total_error > 0:
            overall = StepStatus.FAIL
        elif total_warn > 0:
            overall = StepStatus.WARN
        elif total_skip == len(completed):
            overall = StepStatus.SKIP
        else:
            overall = StepStatus.PASS

        now = datetime.now(tz=timezone.utc).isoformat()

        return RecipeSummary(
            recipe_id=self.recipe_id,
            recipe_name=self.name,
            category=self.category,
            status=overall,
            steps=completed,
            total_pass=total_pass,
            total_fail=total_fail,
            total_warn=total_warn,
            total_skip=total_skip,
            total_error=total_error,
            duration_ms=duration_ms,
            started_at=datetime.fromtimestamp(
                time.time() - (time.monotonic() - start_time), tz=timezone.utc
            ).isoformat(),
            completed_at=now,
            parameters=parameters or {},
            device_id=device_id,
        )
