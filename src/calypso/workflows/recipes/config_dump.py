"""Configuration dump recipe -- walk capabilities, topology, and EEPROM info."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.core.eeprom_manager import EepromManager
from calypso.core.pcie_config import PcieConfigReader
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


class ConfigDumpRecipe(Recipe):
    """Capture PCIe capabilities, topology, and EEPROM configuration data."""

    @property
    def recipe_id(self) -> str:
        return "config_dump"

    @property
    def name(self) -> str:
        return "Configuration Dump"

    @property
    def description(self) -> str:
        return "Walk PCIe capabilities, read topology, and capture EEPROM info"

    @property
    def category(self) -> RecipeCategory:
        return RecipeCategory.CONFIGURATION

    @property
    def estimated_duration_s(self) -> int:
        return 15

    @property
    def parameters(self) -> list[RecipeParameter]:
        return [
            RecipeParameter(
                name="port_number",
                label="Port Number",
                description="Port for capability walking",
                param_type="int",
                default=0,
                min_value=0,
                max_value=143,
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
        params = {"port_number": port_number}

        # --- Step 1: Walk capabilities ---
        step = "Walk capabilities"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            config = PcieConfigReader(dev, dev_key)
            caps = config.walk_capabilities()
            dur = round((time.monotonic() - t0) * 1000, 2)

            cap_names = [c.cap_name for c in caps]
            result = self._make_result(
                step,
                StepStatus.PASS,
                message=f"Found {len(caps)} PCIe capabilit(ies)",
                criticality=StepCriticality.INFO,
                measured_values={
                    "capability_count": len(caps),
                    "capabilities": cap_names,
                },
                duration_ms=dur,
                port_number=port_number,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Capability walk failed: {exc}",
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
            return self._make_summary(steps, start_time, params)

        # --- Step 2: Read topology ---
        step = "Read topology"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            mapper = TopologyMapper(dev, dev_key)
            topo = mapper.build_topology()
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message=f"Topology: {topo.station_count} station(s), {topo.total_ports} port(s)",
                criticality=StepCriticality.INFO,
                measured_values={
                    "station_count": topo.station_count,
                    "total_ports": topo.total_ports,
                    "chip_id": topo.chip_id,
                    "chip_family": topo.chip_family,
                },
                duration_ms=dur,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.ERROR,
                message=f"Topology read failed: {exc}",
                criticality=StepCriticality.HIGH,
                duration_ms=dur,
            )
        yield result
        steps.append(result)

        if self._is_cancelled(cancel):
            skip = self._make_result("Cancelled", StepStatus.SKIP, "Cancelled by user")
            yield skip
            steps.append(skip)
            return self._make_summary(steps, start_time, params)

        # --- Step 3: Read EEPROM info ---
        step = "Read EEPROM info"
        yield self._make_running(step)
        t0 = time.monotonic()
        try:
            eeprom = EepromManager(dev)
            info = eeprom.get_info()
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.PASS,
                message="EEPROM info captured",
                criticality=StepCriticality.INFO,
                measured_values={
                    "eeprom_present": info.present,
                    "eeprom_status": info.status,
                    "eeprom_crc_status": info.crc_status,
                },
                duration_ms=dur,
            )
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 2)
            result = self._make_result(
                step,
                StepStatus.WARN,
                message=f"EEPROM read failed: {exc}",
                criticality=StepCriticality.LOW,
                duration_ms=dur,
            )
        yield result
        steps.append(result)

        return self._make_summary(steps, start_time, params)
