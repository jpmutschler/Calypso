"""EEPROM access API endpoints."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from calypso.exceptions import CalypsoError, UnsupportedError
from calypso.models.eeprom import EepromData, EepromInfo

router = APIRouter(tags=["eeprom"])


def _get_switch(device_id: str):
    from calypso.api.app import get_device_registry
    registry = get_device_registry()
    sw = registry.get(device_id)
    if sw is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return sw


def _get_eeprom_manager(device_id: str):
    from calypso.core.eeprom_manager import EepromManager
    sw = _get_switch(device_id)
    return EepromManager(sw._device_obj)


@router.get("/devices/{device_id}/eeprom/info", response_model=EepromInfo)
async def get_eeprom_info(device_id: str) -> EepromInfo:
    """Get EEPROM presence and status info."""
    mgr = _get_eeprom_manager(device_id)
    try:
        return await asyncio.to_thread(mgr.get_info)
    except UnsupportedError:
        raise HTTPException(
            status_code=501, detail="EEPROM is not supported on this device"
        ) from None
    except CalypsoError as exc:
        raise HTTPException(
            status_code=500, detail=f"EEPROM not accessible: {exc}"
        ) from exc


@router.get("/devices/{device_id}/eeprom/read", response_model=EepromData)
async def read_eeprom(
    device_id: str, offset: int = 0, count: int = 16
) -> EepromData:
    """Read a range of 32-bit EEPROM values."""
    mgr = _get_eeprom_manager(device_id)
    try:
        return await asyncio.to_thread(mgr.read_range, offset=offset, count=count)
    except UnsupportedError:
        raise HTTPException(
            status_code=501, detail="EEPROM is not supported on this device"
        ) from None
    except CalypsoError as exc:
        raise HTTPException(
            status_code=500, detail=f"EEPROM not accessible: {exc}"
        ) from exc


class EepromWriteRequest(BaseModel):
    offset: int
    value: int


@router.post("/devices/{device_id}/eeprom/write")
async def write_eeprom(device_id: str, body: EepromWriteRequest) -> dict[str, str]:
    """Write a 32-bit value to EEPROM."""
    mgr = _get_eeprom_manager(device_id)
    try:
        await asyncio.to_thread(mgr.write_value, offset=body.offset, value=body.value)
    except UnsupportedError:
        raise HTTPException(
            status_code=501, detail="EEPROM is not supported on this device"
        ) from None
    except CalypsoError as exc:
        raise HTTPException(
            status_code=500, detail=f"EEPROM write failed: {exc}"
        ) from exc
    return {"status": "written"}


@router.get("/devices/{device_id}/eeprom/crc")
async def get_eeprom_crc(device_id: str) -> dict[str, object]:
    """Verify EEPROM CRC."""
    mgr = _get_eeprom_manager(device_id)
    try:
        crc_value, status = await asyncio.to_thread(mgr.verify_crc)
    except UnsupportedError:
        raise HTTPException(
            status_code=501, detail="EEPROM is not supported on this device"
        ) from None
    except CalypsoError as exc:
        raise HTTPException(
            status_code=500, detail=f"EEPROM not accessible: {exc}"
        ) from exc
    return {"crc_value": crc_value, "status": status}


@router.post("/devices/{device_id}/eeprom/crc/update")
async def update_eeprom_crc(device_id: str) -> dict[str, int]:
    """Recalculate and write EEPROM CRC."""
    mgr = _get_eeprom_manager(device_id)
    try:
        crc_value = await asyncio.to_thread(mgr.update_crc)
    except UnsupportedError:
        raise HTTPException(
            status_code=501, detail="EEPROM is not supported on this device"
        ) from None
    except CalypsoError as exc:
        raise HTTPException(
            status_code=500, detail=f"EEPROM CRC update failed: {exc}"
        ) from exc
    return {"crc_value": crc_value}
