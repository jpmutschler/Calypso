"""Device discovery and management API endpoints."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from calypso.models.device_info import DeviceInfo, TransportMode

router = APIRouter(tags=["devices"])


class ScanRequest(BaseModel):
    transport: TransportMode = TransportMode.PCIE_BUS
    port: int = 0
    baud_rate: int = 115200


class ScanResponse(BaseModel):
    devices: list[DeviceInfo]
    transport: TransportMode


class ConnectRequest(BaseModel):
    transport: TransportMode = TransportMode.PCIE_BUS
    device_index: int = 0
    port: int = 0


class ConnectResponse(BaseModel):
    device_id: str
    device_info: DeviceInfo


@router.post("/devices/scan", response_model=ScanResponse)
async def scan_devices(request: ScanRequest) -> ScanResponse:
    """Scan for Atlas3 devices on the specified transport."""
    from calypso.bindings.functions import initialize
    from calypso.bindings.library import load_library
    from calypso.core.discovery import scan_devices as do_scan
    from calypso.transport import (
        PcieConfig, PcieTransport,
        SdbConfig, SdbTransport,
        UartConfig, UartTransport,
    )

    def _scan() -> list:
        load_library()
        initialize()

        if request.transport == TransportMode.UART_MCU:
            t = UartTransport(UartConfig(port=request.port))
        elif request.transport == TransportMode.SDB_USB:
            t = SdbTransport(SdbConfig(port=request.port))
        else:
            t = PcieTransport(PcieConfig())

        return do_scan(t)

    devices = await asyncio.to_thread(_scan)
    return ScanResponse(devices=devices, transport=request.transport)


@router.get("/devices", response_model=list[str])
async def list_devices() -> list[str]:
    """List currently connected device IDs."""
    from calypso.api.app import get_device_registry
    return list(get_device_registry().keys())


@router.post("/devices/connect", response_model=ConnectResponse)
async def connect_device(request: ConnectRequest) -> ConnectResponse:
    """Connect to a specific device."""
    from calypso.api.app import get_device_registry
    from calypso.bindings.functions import initialize
    from calypso.bindings.library import load_library
    from calypso.core.switch import SwitchDevice
    from calypso.transport import (
        PcieConfig, PcieTransport,
        SdbConfig, SdbTransport,
        UartConfig, UartTransport,
    )

    def _connect() -> SwitchDevice:
        load_library()
        initialize()

        if request.transport == TransportMode.UART_MCU:
            t = UartTransport(UartConfig(port=request.port))
        elif request.transport == TransportMode.SDB_USB:
            t = SdbTransport(SdbConfig(port=request.port))
        else:
            t = PcieTransport(PcieConfig())

        sw = SwitchDevice(t)
        sw.open(request.device_index)
        return sw

    try:
        sw = await asyncio.to_thread(_connect)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    device_id = f"dev_{sw.device_info.bus:02x}_{sw.device_info.slot:02x}"
    registry = get_device_registry()
    registry[device_id] = sw

    return ConnectResponse(device_id=device_id, device_info=sw.device_info)


@router.post("/devices/{device_id}/disconnect")
async def disconnect_device(device_id: str) -> dict[str, str]:
    """Disconnect from a device."""
    from calypso.api.app import get_device_registry
    registry = get_device_registry()
    sw = registry.pop(device_id, None)
    if sw is None:
        raise HTTPException(status_code=404, detail="Device not found")
    if hasattr(sw, "close"):
        await asyncio.to_thread(sw.close)
    return {"status": "disconnected", "device_id": device_id}


@router.get("/devices/{device_id}", response_model=DeviceInfo)
async def get_device_info(device_id: str) -> DeviceInfo:
    """Get device information."""
    from calypso.api.app import get_device_registry
    registry = get_device_registry()
    sw = registry.get(device_id)
    if sw is None:
        raise HTTPException(status_code=404, detail="Device not found")
    if not hasattr(sw, "device_info") or sw.device_info is None:
        raise HTTPException(status_code=500, detail="Device info not available")
    return sw.device_info


@router.post("/devices/{device_id}/reset")
async def reset_device(device_id: str) -> dict[str, str]:
    """Reset the device."""
    from calypso.api.app import get_device_registry
    registry = get_device_registry()
    sw = registry.get(device_id)
    if sw is None:
        raise HTTPException(status_code=404, detail="Device not found")
    try:
        await asyncio.to_thread(sw.reset)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "reset", "device_id": device_id}
