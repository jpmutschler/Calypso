"""EEPROM status and data models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EepromInfo(BaseModel):
    """EEPROM presence and validity status."""

    present: bool
    status: str
    crc_value: int = 0
    crc_status: str = "unknown"


class EepromData(BaseModel):
    """A range of EEPROM data values."""

    offset: int
    values: list[int] = Field(default_factory=list)
    format: str = "hex"
