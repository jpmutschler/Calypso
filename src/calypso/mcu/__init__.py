"""MCU interface layer using serialcables-atlas3 package."""

from calypso.mcu import pool
from calypso.mcu.bus import Bus, I2cBus, I3cBus
from calypso.mcu.client import McuClient
from calypso.mcu.models import (
    I2cReadResponse,
    I2cScanResult,
    I3cEntdaaResult,
    I3cReadResponse,
    McuDeviceInfo,
    McuErrorSnapshot,
    McuPortStatus,
    McuThermalStatus,
)

__all__ = [
    "Bus",
    "I2cBus",
    "I2cReadResponse",
    "I2cScanResult",
    "I3cBus",
    "I3cEntdaaResult",
    "I3cReadResponse",
    "McuClient",
    "McuDeviceInfo",
    "McuErrorSnapshot",
    "McuPortStatus",
    "McuThermalStatus",
    "pool",
]
