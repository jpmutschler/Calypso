"""API routes for NVMe-MI drive discovery and health monitoring."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from calypso.mcu import pool
from calypso.nvme_mi.models import NVMeDiscoveryResult, NVMeDriveInfo, NVMeHealthStatus

router = APIRouter(prefix="/api/mcu/nvme", tags=["nvme-mi"])


def _get_client(port: str):
    """Get an MCU client, raising HTTPException on failure."""
    try:
        return pool.get_client(port)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/discover")
async def discover_drives(port: str = Query(...)) -> NVMeDiscoveryResult:
    """Scan all connectors for NVMe drives via NVMe-MI over MCTP."""
    from calypso.nvme_mi.discovery import discover_nvme_drives

    client = _get_client(port)
    return discover_nvme_drives(client)


@router.get("/health")
async def health_poll(
    port: str = Query(...),
    connector: int = Query(..., ge=0, le=5),
    channel: str = Query(..., pattern=r"^[ab]$"),
    address: int = Query(0x6A, ge=0x03, le=0x77),
) -> NVMeHealthStatus:
    """Poll health status from a specific NVMe drive."""
    from calypso.mctp.transport import MCTPOverI2C
    from calypso.mcu.bus import I2cBus
    from calypso.nvme_mi.client import NVMeMIClient

    client = _get_client(port)
    bus = I2cBus(client, connector, channel)
    transport = MCTPOverI2C(bus)
    nvme = NVMeMIClient(transport)
    return nvme.health_poll(slave_addr=address)


@router.get("/drive")
async def drive_info(
    port: str = Query(...),
    connector: int = Query(..., ge=0, le=5),
    channel: str = Query(..., pattern=r"^[ab]$"),
    address: int = Query(0x6A, ge=0x03, le=0x77),
) -> NVMeDriveInfo:
    """Get combined identity and health info for a specific NVMe drive."""
    from calypso.mctp.transport import MCTPOverI2C
    from calypso.mcu.bus import I2cBus
    from calypso.nvme_mi.client import NVMeMIClient

    client = _get_client(port)
    bus = I2cBus(client, connector, channel)
    transport = MCTPOverI2C(bus)
    nvme = NVMeMIClient(transport)
    return nvme.get_drive_info(
        connector=connector,
        channel=channel,
        slave_addr=address,
    )
