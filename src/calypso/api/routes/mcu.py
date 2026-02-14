"""API routes for MCU-level Atlas3 features."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from calypso.mcu import pool
from calypso.mcu.models import (
    I2cReadRequest,
    I2cReadResponse,
    I2cScanResult,
    I2cWriteRequest,
    I3cEntdaaResult,
    I3cReadRequest,
    I3cReadResponse,
    I3cWriteRequest,
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


# --- I2C Endpoints ---


@router.post("/i2c/read")
async def i2c_read(req: I2cReadRequest, port: str = Query(...)) -> I2cReadResponse:
    """Read bytes from an I2C device."""
    client = _get_client(port)
    data = client.i2c_read(
        address=req.address,
        connector=req.connector,
        channel=req.channel,
        read_bytes=req.count,
        register=req.reg_offset,
    )
    return I2cReadResponse(
        connector=req.connector,
        channel=req.channel,
        address=req.address,
        reg_offset=req.reg_offset,
        data=data,
    )


@router.post("/i2c/write")
async def i2c_write(req: I2cWriteRequest, port: str = Query(...)) -> dict:
    """Write bytes to an I2C device."""
    client = _get_client(port)
    success = client.i2c_write(
        address=req.address,
        connector=req.connector,
        channel=req.channel,
        data=req.data,
    )
    return {"success": success}


@router.post("/i2c/scan")
async def i2c_scan(
    port: str = Query(...),
    connector: int = Query(..., ge=0, le=5),
    channel: str = Query(..., pattern=r"^[ab]$"),
) -> I2cScanResult:
    """Scan an I2C bus for responding devices."""
    return _get_client(port).i2c_scan(connector=connector, channel=channel)


# --- I3C Endpoints ---


@router.post("/i3c/read")
async def i3c_read(req: I3cReadRequest, port: str = Query(...)) -> I3cReadResponse:
    """Read bytes from an I3C target device."""
    client = _get_client(port)
    return client.i3c_read(
        address=req.address,
        connector=req.connector,
        channel=req.channel,
        read_bytes=req.count,
        register=req.reg_offset,
    )


@router.post("/i3c/write")
async def i3c_write(req: I3cWriteRequest, port: str = Query(...)) -> dict:
    """Write bytes to an I3C target device."""
    client = _get_client(port)
    success = client.i3c_write(
        address=req.address,
        connector=req.connector,
        channel=req.channel,
        data=req.data,
        register=req.reg_offset,
    )
    return {"success": success}


@router.post("/i3c/entdaa")
async def i3c_entdaa(
    port: str = Query(...),
    connector: int = Query(..., ge=0, le=5),
    channel: str = Query(..., pattern=r"^[ab]$"),
) -> I3cEntdaaResult:
    """Run I3C ENTDAA to discover and assign dynamic addresses."""
    return _get_client(port).i3c_entdaa(connector=connector, channel=channel)
