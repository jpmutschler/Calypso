"""Topology snapshot recipe -- build and analyze the switch fabric topology."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.core.topology import TopologyMapper
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


class TopologySnapshotRecipe(Recipe):
    """Build a topology map and report station/port/link-up counts."""

    @property
    def recipe_id(self) -> str:
        return "topology_snapshot"

    @property
    def name(self) -> str:
        return "Topology Snapshot"

    @property
    def description(self) -> str:
        return "Build the switch fabric topology map and analyze structure"

    @property
    def category(self) -> RecipeCategory:
        return RecipeCategory.CONFIGURATION

    @property
    def estimated_duration_s(self) -> int:
        return 10

    @property
    def parameters(self) -> list[RecipeParameter]:
        return []

    def run(
        self,
        dev: PLX_DEVICE_OBJECT,
        dev_key: PLX_DEVICE_KEY,
        cancel: dict[str, bool],
        **kwargs: Any,
    ) -> Generator[RecipeResult, None, RecipeSummary]:
        start_time = time.monotonic()
        steps: list[RecipeResult] = []

        # --- Step 1: Build topology map ---
        step = "Build topology map"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            mapper = TopologyMapper(dev, dev_key)
            topo = mapper.build_topology()
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message=(
                    f"Topology built: {topo.station_count} station(s), {topo.total_ports} port(s)"
                ),
                criticality=StepCriticality.MEDIUM,
                measured_values={
                    "station_count": topo.station_count,
                    "total_ports": topo.total_ports,
                    "chip_id": topo.chip_id,
                    "real_chip_id": topo.real_chip_id,
                    "chip_family": topo.chip_family,
                },
                duration_ms=dur,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Failed to build topology: {exc}",
                criticality=StepCriticality.CRITICAL,
                duration_ms=dur,
            )
        yield result
        steps.append(result)

        if result.status == StepStatus.ERROR:
            return self._make_summary(steps, start_time)

        if self._is_cancelled(cancel):
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return self._make_summary(steps, start_time)

        # --- Step 2: Analyze structure ---
        step = "Analyze structure"
        yield self._make_running(step)
        t0 = time.monotonic()

        link_up_count = 0
        link_down_count = 0
        station_details: list[dict[str, object]] = []

        for station in topo.stations:
            up = 0
            down = 0
            for port in station.ports:
                if port.status and port.status.is_link_up:
                    up += 1
                else:
                    down += 1
            link_up_count += up
            link_down_count += down
            station_details.append(
                {
                    "station_index": station.station_index,
                    "port_count": len(station.ports),
                    "link_up": up,
                    "link_down": down,
                }
            )

        dur = round((time.monotonic() - t0) * 1000, 2)
        result = self._make_result(
            step,
            StepStatus.PASS,
            message=(
                f"Structure: {link_up_count} link(s) up, "
                f"{link_down_count} link(s) down across "
                f"{topo.station_count} station(s)"
            ),
            criticality=StepCriticality.INFO,
            measured_values={
                "link_up_count": link_up_count,
                "link_down_count": link_down_count,
                "stations": station_details,
            },
            duration_ms=dur,
        )
        yield result
        steps.append(result)

        return self._make_summary(steps, start_time)
