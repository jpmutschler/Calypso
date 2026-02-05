"""Port status API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from calypso.models.port import PortStatus

router = APIRouter(tags=["ports"])


def _get_switch(device_id: str):
    from calypso.api.app import get_device_registry
    registry = get_device_registry()
    sw = registry.get(device_id)
    if sw is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return sw


@router.get("/devices/{device_id}/ports", response_model=list[PortStatus])
async def get_all_ports(device_id: str) -> list[PortStatus]:
    """Get status of all ports on the switch."""
    from calypso.core.port_manager import PortManager
    sw = _get_switch(device_id)
    pm = PortManager(sw._device_obj, sw._device_key)
    return pm.get_all_port_statuses()


@router.get("/devices/{device_id}/ports/{port_number}", response_model=PortStatus)
async def get_port(device_id: str, port_number: int) -> PortStatus:
    """Get status of a specific port."""
    from calypso.core.port_manager import PortManager
    sw = _get_switch(device_id)
    pm = PortManager(sw._device_obj, sw._device_key)
    status = pm.get_port_status(port_number)
    if status is None:
        raise HTTPException(status_code=404, detail=f"Port {port_number} not found")
    return status
