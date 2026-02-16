"""Switch topology API endpoints."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from calypso.exceptions import CalypsoError
from calypso.models.topology import TopologyMap

router = APIRouter(tags=["topology"])


def _get_switch(device_id: str):
    from calypso.api.app import get_device_registry
    registry = get_device_registry()
    sw = registry.get(device_id)
    if sw is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return sw


@router.get("/devices/{device_id}/topology", response_model=TopologyMap)
async def get_topology(device_id: str) -> TopologyMap:
    """Get switch fabric topology map."""
    from calypso.core.topology import TopologyMapper
    sw = _get_switch(device_id)
    mapper = TopologyMapper(sw._device_obj, sw._device_key)
    try:
        return await asyncio.to_thread(mapper.build_topology)
    except CalypsoError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to build topology map: {exc}",
        ) from exc
