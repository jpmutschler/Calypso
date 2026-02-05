"""API routes for MCU-level Atlas3 features."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from calypso.mcu import pool
from calypso.mcu.models import (
    McuBistResult,
    McuClockStatus,
    McuDeviceInfo,
    McuErrorSnapshot,
    McuFlitStatus,
    McuPortStatus,
    McuSpreadStatus,
    McuThermalStatus,
    McuVersionInfo,
)

router = APIRouter(prefix="/api/mcu", tags=["mcu"])


def _get_client(port: str):
    """Get an MCU client, raising HTTPException on failure."""
    try:
        return pool.get_client(port)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/discover")
async def discover_devices() -> list[str]:
    """Scan for available Atlas3 serial devices."""
    from calypso.mcu.client import McuClient

    return McuClient.find_devices()


@router.post("/connect")
async def connect(port: str = Query(..., description="Serial port path")) -> dict:
    """Connect to an Atlas3 MCU."""
    client = _get_client(port)
    return {"port": port, "connected": client.is_connected}


@router.post("/disconnect")
async def disconnect(port: str = Query(..., description="Serial port path")) -> dict:
    """Disconnect from an Atlas3 MCU."""
    pool.disconnect(port)
    return {"port": port, "connected": False}


@router.get("/version")
async def get_version(port: str = Query(...)) -> McuVersionInfo:
    """Get firmware and hardware version info."""
    return _get_client(port).get_version()


@router.get("/info")
async def get_device_info(port: str = Query(...)) -> McuDeviceInfo:
    """Get combined device information."""
    return _get_client(port).get_device_info()


@router.get("/health")
async def get_health(port: str = Query(...)) -> McuThermalStatus:
    """Get thermal, fan, voltage, and power status."""
    return _get_client(port).get_thermal_status()


@router.get("/ports")
async def get_ports(port: str = Query(...)) -> McuPortStatus:
    """Get port status for all stations."""
    return _get_client(port).get_port_status()


@router.get("/errors")
async def get_errors(port: str = Query(...)) -> McuErrorSnapshot:
    """Get error counters for all ports."""
    return _get_client(port).get_error_counters()


@router.post("/errors/clear")
async def clear_errors(port: str = Query(...)) -> dict:
    """Clear error counters."""
    result = _get_client(port).clear_error_counters()
    return {"cleared": result}


@router.get("/config/clock")
async def get_clock(port: str = Query(...)) -> McuClockStatus:
    """Get clock output status."""
    return _get_client(port).get_clock_status()


@router.get("/config/spread")
async def get_spread(port: str = Query(...)) -> McuSpreadStatus:
    """Get spread spectrum status."""
    return _get_client(port).get_spread_status()


@router.get("/config/flit")
async def get_flit(port: str = Query(...)) -> McuFlitStatus:
    """Get FLIT mode status."""
    return _get_client(port).get_flit_status()


@router.post("/config/mode")
async def set_mode(
    port: str = Query(...),
    mode: int = Query(..., ge=1, le=4),
) -> dict:
    """Set operation mode (1-4)."""
    result = _get_client(port).set_mode(mode)
    return {"mode": mode, "success": result}


@router.post("/bist")
async def run_bist(port: str = Query(...)) -> McuBistResult:
    """Run Built-In Self Test."""
    return _get_client(port).run_bist()
