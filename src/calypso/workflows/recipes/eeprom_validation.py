"""EEPROM Validation recipe -- verify presence, status, CRC, and header."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.core.eeprom_manager import EepromManager
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


class EepromValidation(Recipe):
    """Validate EEPROM presence, status, CRC integrity, and header contents."""

    @property
    def recipe_id(self) -> str:
        return "eeprom_validation"

    @property
    def name(self) -> str:
        return "EEPROM Validation"

    @property
    def description(self) -> str:
        return "Validate EEPROM presence, status, CRC, and read header data"

    @property
    def category(self) -> RecipeCategory:
        return RecipeCategory.CONFIGURATION

    @property
    def estimated_duration_s(self) -> int:
        return 10

    @property
    def parameters(self) -> list[RecipeParameter]:
        return [
            RecipeParameter(
                name="read_size",
                label="Read Size",
                description="Number of 32-bit DWORDs to read from EEPROM header",
                param_type="int",
                default=16,
                min_value=1,
                max_value=256,
                unit="DWORDs",
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
        read_size: int = int(kwargs.get("read_size", 16))
        device_id: str = str(kwargs.get("device_id", ""))

        eeprom = EepromManager(dev)

        # Step 1: Check EEPROM presence
        step_name = "Check EEPROM presence"
        yield self._make_running(step_name)
        t0 = time.monotonic()

        try:
            info = eeprom.get_info()
        except Exception as exc:
            logger.error("eeprom_validation_info_failed", error=str(exc))
            result = self._make_result(
                step_name,
                StepStatus.ERROR,
                message=f"Failed to probe EEPROM: {exc}",
                criticality=StepCriticality.CRITICAL,
                duration_ms=_elapsed_ms(t0),
            )
            steps.append(result)
            yield result
            return self._make_summary(steps, start_time, kwargs, device_id)

        measured: dict[str, object] = {"present": info.present}

        if not info.present:
            result = self._make_result(
                step_name,
                StepStatus.FAIL,
                message="EEPROM not present",
                criticality=StepCriticality.CRITICAL,
                measured_values=measured,
                duration_ms=_elapsed_ms(t0),
            )
            steps.append(result)
            yield result
            # Skip remaining steps -- no EEPROM to validate
            for remaining in ["Validate status", "Verify CRC", "Read header"]:
                skip = self._make_result(
                    remaining,
                    StepStatus.SKIP,
                    message="EEPROM not present",
                    criticality=StepCriticality.LOW,
                )
                steps.append(skip)
                yield skip
            return self._make_summary(steps, start_time, kwargs, device_id)

        result = self._make_result(
            step_name,
            StepStatus.PASS,
            message="EEPROM present",
            criticality=StepCriticality.CRITICAL,
            measured_values=measured,
            duration_ms=_elapsed_ms(t0),
        )
        steps.append(result)
        yield result

        if self._is_cancelled(cancel):
            return self._make_summary(steps, start_time, kwargs, device_id)

        # Step 2: Validate status
        step_name = "Validate status"
        yield self._make_running(step_name)
        t0 = time.monotonic()

        measured = {"status": info.status}

        if info.status == "valid":
            status = StepStatus.PASS
            message = "EEPROM status: valid"
            criticality = StepCriticality.HIGH
        elif info.status == "none":
            status = StepStatus.WARN
            message = "EEPROM status: none (blank or uninitialized)"
            criticality = StepCriticality.HIGH
        else:
            status = StepStatus.FAIL
            message = f"EEPROM status: {info.status}"
            criticality = StepCriticality.CRITICAL

        result = self._make_result(
            step_name,
            status,
            message=message,
            criticality=criticality,
            measured_values=measured,
            duration_ms=_elapsed_ms(t0),
        )
        steps.append(result)
        yield result

        if self._is_cancelled(cancel):
            return self._make_summary(steps, start_time, kwargs, device_id)

        # Step 3: Verify CRC
        step_name = "Verify CRC"
        yield self._make_running(step_name)
        t0 = time.monotonic()

        measured = {
            "crc_value": info.crc_value,
            "crc_status": info.crc_status,
        }

        if info.crc_status == "valid":
            status = StepStatus.PASS
            message = f"CRC valid (0x{info.crc_value:08X})"
            criticality = StepCriticality.CRITICAL
        elif info.crc_status == "unsupported":
            status = StepStatus.SKIP
            message = "CRC check not supported by device"
            criticality = StepCriticality.LOW
        elif info.crc_status == "unknown":
            status = StepStatus.WARN
            message = "CRC status unknown"
            criticality = StepCriticality.MEDIUM
        else:
            status = StepStatus.FAIL
            message = f"CRC invalid (0x{info.crc_value:08X})"
            criticality = StepCriticality.CRITICAL

        result = self._make_result(
            step_name,
            status,
            message=message,
            criticality=criticality,
            measured_values=measured,
            duration_ms=_elapsed_ms(t0),
        )
        steps.append(result)
        yield result

        if self._is_cancelled(cancel):
            return self._make_summary(steps, start_time, kwargs, device_id)

        # Step 4: Read header
        step_name = "Read header"
        yield self._make_running(step_name)
        t0 = time.monotonic()

        try:
            data = eeprom.read_range(offset=0, count=read_size)
        except Exception as exc:
            logger.error("eeprom_validation_read_failed", error=str(exc))
            result = self._make_result(
                step_name,
                StepStatus.ERROR,
                message=f"Failed to read EEPROM header: {exc}",
                criticality=StepCriticality.MEDIUM,
                duration_ms=_elapsed_ms(t0),
            )
            steps.append(result)
            yield result
            return self._make_summary(steps, start_time, kwargs, device_id)

        # Format values as hex strings for readability
        hex_values = [f"0x{v:08X}" for v in data.values]
        all_zero = all(v == 0 for v in data.values)
        all_ff = all(v == 0xFFFFFFFF for v in data.values)

        measured = {
            "read_count": len(data.values),
            "header_values": hex_values[:8],  # First 8 for summary
            "all_zero": all_zero,
            "all_0xff": all_ff,
        }

        if all_zero or all_ff:
            status = StepStatus.WARN
            pattern = "0x00" if all_zero else "0xFF"
            message = f"Header contains all {pattern} (blank/erased)"
            criticality = StepCriticality.HIGH
        else:
            status = StepStatus.PASS
            message = f"Read {len(data.values)} DWORDs from header"
            criticality = StepCriticality.MEDIUM

        details = " ".join(hex_values)

        result = self._make_result(
            step_name,
            status,
            message=message,
            criticality=criticality,
            measured_values=measured,
            duration_ms=_elapsed_ms(t0),
            details=details,
        )
        steps.append(result)
        yield result

        return self._make_summary(steps, start_time, kwargs, device_id)


def _elapsed_ms(t0: float) -> float:
    """Compute elapsed milliseconds since *t0*."""
    return round((time.monotonic() - t0) * 1000, 2)
