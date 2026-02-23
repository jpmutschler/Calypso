"""LTSSM trace API endpoints (state polling, retrain-and-watch).

PTrace (Protocol Trace) capture endpoints have been moved to
``calypso.api.routes.ptrace``.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from calypso.exceptions import CalypsoError
from calypso.models.ltssm import (
    PortLtssmSnapshot,
    RetrainWatchProgress,
    RetrainWatchResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ltssm"])


def _get_switch(device_id: str):
    from calypso.api.app import get_device_registry

    registry = get_device_registry()
    sw = registry.get(device_id)
    if sw is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return sw


def _get_tracer(device_id: str, port_number: int):
    from calypso.core.ltssm_trace import LtssmTracer

    sw = _get_switch(device_id)
    return LtssmTracer(sw._device_obj, sw._device_key, port_number)


# ---------------------------------------------------------------------------
# Phase 1: LTSSM State Polling
# ---------------------------------------------------------------------------


@router.get(
    "/devices/{device_id}/ltssm/snapshot",
    response_model=PortLtssmSnapshot,
)
async def get_ltssm_snapshot(
    device_id: str,
    port_number: int = Query(0, ge=0, le=143),
) -> PortLtssmSnapshot:
    """Read current LTSSM state, recovery count, and link status."""
    tracer = _get_tracer(device_id, port_number)
    try:
        return await asyncio.to_thread(tracer.get_snapshot)
    except CalypsoError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read LTSSM state for port {port_number}: {exc}",
        ) from exc


class ClearCountersRequest(BaseModel):
    port_number: int = Field(0, ge=0, le=143)


@router.post("/devices/{device_id}/ltssm/clear-counters")
async def clear_ltssm_counters(
    device_id: str,
    body: ClearCountersRequest,
) -> dict[str, str]:
    """Clear recovery count for a port."""
    tracer = _get_tracer(device_id, body.port_number)
    try:
        await asyncio.to_thread(tracer.clear_recovery_count)
    except CalypsoError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to clear counters for port {body.port_number}: {exc}",
        ) from exc
    return {"status": "cleared", "port_number": str(body.port_number)}


# ---------------------------------------------------------------------------
# Retrain-and-Watch
# ---------------------------------------------------------------------------


class RetrainRequest(BaseModel):
    port_number: int = Field(0, ge=0, le=143)
    timeout_s: float = Field(10.0, ge=1.0, le=60.0)


@router.post("/devices/{device_id}/ltssm/retrain")
async def start_retrain_watch(
    device_id: str,
    body: RetrainRequest,
) -> dict[str, str]:
    """Start a background retrain-and-watch operation.

    The atomic check-and-set inside retrain_and_watch() prevents concurrent
    retrains on the same port (which could corrupt hardware state).
    """
    tracer = _get_tracer(device_id, body.port_number)

    def _run_retrain():
        try:
            tracer.retrain_and_watch(device_id, body.timeout_s)
        except RuntimeError as exc:
            # Atomic guard rejected: already running
            logger.warning("Retrain rejected: %s", exc)
        except Exception:
            logger.exception(
                "Background retrain-watch failed for port %d",
                body.port_number,
            )

    asyncio.get_running_loop().run_in_executor(None, _run_retrain)

    return {"status": "started", "port_number": str(body.port_number)}


@router.get(
    "/devices/{device_id}/ltssm/retrain/progress",
    response_model=RetrainWatchProgress,
)
async def get_retrain_watch_progress(
    device_id: str,
    port_number: int = Query(0, ge=0, le=143),
) -> RetrainWatchProgress:
    """Poll the progress of a running retrain-and-watch."""
    from calypso.core.ltssm_trace import get_retrain_progress

    return get_retrain_progress(device_id, port_number)


@router.get(
    "/devices/{device_id}/ltssm/retrain/result",
    response_model=RetrainWatchResult,
)
async def get_retrain_watch_result(
    device_id: str,
    port_number: int = Query(0, ge=0, le=143),
) -> RetrainWatchResult:
    """Get the completed retrain-watch result."""
    from calypso.core.ltssm_trace import get_retrain_result

    result = get_retrain_result(device_id, port_number)
    if result is None:
        raise HTTPException(status_code=404, detail="No retrain result available")
    return result


