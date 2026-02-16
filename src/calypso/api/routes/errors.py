"""Combined error overview API endpoints."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query

from calypso.models.errors import ErrorOverview
from calypso.models.port import PortRole
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["errors"])


def _get_switch(device_id: str):
    from calypso.api.app import get_device_registry
    registry = get_device_registry()
    sw = registry.get(device_id)
    if sw is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return sw


def _active_downstream_ports(sw: object) -> list[int]:
    """Find downstream port numbers with link-up from topology."""
    try:
        from calypso.core.port_manager import PortManager
        pm = PortManager(sw._device_obj, sw._device_key)
        statuses = pm.get_all_port_statuses()
        return [
            ps.port_number for ps in statuses
            if ps.role == PortRole.DOWNSTREAM and ps.is_link_up
        ]
    except Exception:
        return []


@router.get(
    "/devices/{device_id}/errors/overview",
    response_model=ErrorOverview,
)
async def get_error_overview(
    device_id: str,
    mcu_port: str | None = Query(default=None, description="MCU serial port"),
) -> ErrorOverview:
    """Get combined error overview from AER, MCU, and LTSSM sources."""
    from calypso.core.error_aggregator import ErrorAggregator

    sw = _get_switch(device_id)

    def _read() -> ErrorOverview:
        active_ports = _active_downstream_ports(sw)
        aggregator = ErrorAggregator(sw._device_obj, sw._device_key)
        return aggregator.get_overview(
            mcu_port=mcu_port,
            active_ports=active_ports,
        )

    return await asyncio.to_thread(_read)


@router.post("/devices/{device_id}/errors/clear-aer")
async def clear_aer_errors(device_id: str) -> dict[str, str]:
    """Clear AER error status registers."""
    from calypso.core.pcie_config import PcieConfigReader

    sw = _get_switch(device_id)
    reader = PcieConfigReader(sw._device_obj, sw._device_key)
    await asyncio.to_thread(reader.clear_aer_errors)
    return {"status": "cleared"}


@router.post("/devices/{device_id}/errors/clear-mcu")
async def clear_mcu_errors(
    device_id: str,
    mcu_port: str | None = Query(default=None, description="MCU serial port"),
) -> dict[str, str]:
    """Clear MCU error counters."""
    if not mcu_port:
        raise HTTPException(status_code=400, detail="mcu_port parameter required")

    from calypso.mcu import pool
    try:
        client = pool.get_client(mcu_port)
        await asyncio.to_thread(client.clear_error_counters)
        return {"status": "cleared"}
    except Exception:
        logger.exception("clear_mcu_failed", extra={"mcu_port": mcu_port})
        raise HTTPException(status_code=500, detail="Failed to clear MCU error counters")
