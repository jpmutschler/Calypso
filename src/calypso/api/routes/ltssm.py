"""LTSSM trace and Ptrace capture API endpoints."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from calypso.models.ltssm import (
    PortLtssmSnapshot,
    PtraceConfig,
    PtraceCaptureResult,
    PtraceStatusResponse,
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
    port_select: int = Query(0, ge=0, le=15),
) -> PortLtssmSnapshot:
    """Read current LTSSM state, recovery count, and link status."""
    tracer = _get_tracer(device_id, port_number)
    return await asyncio.to_thread(tracer.get_snapshot, port_select)


class ClearCountersRequest(BaseModel):
    port_number: int = Field(0, ge=0, le=143)
    port_select: int = Field(0, ge=0, le=15)


@router.post("/devices/{device_id}/ltssm/clear-counters")
async def clear_ltssm_counters(
    device_id: str,
    body: ClearCountersRequest,
) -> dict[str, str]:
    """Clear recovery count for a port."""
    tracer = _get_tracer(device_id, body.port_number)
    await asyncio.to_thread(tracer.clear_recovery_count, body.port_select)
    return {"status": "cleared", "port_number": str(body.port_number)}


# ---------------------------------------------------------------------------
# Retrain-and-Watch
# ---------------------------------------------------------------------------


class RetrainRequest(BaseModel):
    port_number: int = Field(0, ge=0, le=143)
    port_select: int = Field(0, ge=0, le=15)
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
            tracer.retrain_and_watch(body.port_select, device_id, body.timeout_s)
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
    port_select: int = Query(0, ge=0, le=15),
) -> RetrainWatchProgress:
    """Poll the progress of a running retrain-and-watch."""
    from calypso.core.ltssm_trace import get_retrain_progress
    return get_retrain_progress(device_id, port_number, port_select)


@router.get(
    "/devices/{device_id}/ltssm/retrain/result",
    response_model=RetrainWatchResult,
)
async def get_retrain_watch_result(
    device_id: str,
    port_number: int = Query(0, ge=0, le=143),
    port_select: int = Query(0, ge=0, le=15),
) -> RetrainWatchResult:
    """Get the completed retrain-watch result."""
    from calypso.core.ltssm_trace import get_retrain_result
    result = get_retrain_result(device_id, port_number, port_select)
    if result is None:
        raise HTTPException(status_code=404, detail="No retrain result available")
    return result


# ---------------------------------------------------------------------------
# Phase 2: Ptrace Capture
# ---------------------------------------------------------------------------


class PtraceConfigRequest(BaseModel):
    port_number: int = Field(0, ge=0, le=143)
    port_select: int = Field(0, ge=0, le=15)
    trace_point: int = Field(0, ge=0, le=15)
    lane_select: int = Field(0, ge=0, le=15)
    trigger_on_ltssm: bool = False
    ltssm_trigger_state: int | None = Field(None, ge=0, le=0x1A)


@router.post("/devices/{device_id}/ltssm/ptrace/configure")
async def configure_ptrace(
    device_id: str,
    body: PtraceConfigRequest,
) -> dict[str, str]:
    """Configure Ptrace capture parameters."""
    tracer = _get_tracer(device_id, body.port_number)
    config = PtraceConfig(
        port_select=body.port_select,
        trace_point=body.trace_point,
        lane_select=body.lane_select,
        trigger_on_ltssm=body.trigger_on_ltssm,
        ltssm_trigger_state=body.ltssm_trigger_state,
    )
    await asyncio.to_thread(tracer.configure_ptrace, config)
    return {"status": "configured"}


class PtracePortRequest(BaseModel):
    port_number: int = Field(0, ge=0, le=143)


@router.post("/devices/{device_id}/ltssm/ptrace/start")
async def start_ptrace(
    device_id: str,
    body: PtracePortRequest,
) -> dict[str, str]:
    """Start Ptrace capture."""
    tracer = _get_tracer(device_id, body.port_number)
    await asyncio.to_thread(tracer.start_ptrace)
    return {"status": "started"}


@router.post("/devices/{device_id}/ltssm/ptrace/stop")
async def stop_ptrace(
    device_id: str,
    body: PtracePortRequest,
) -> dict[str, str]:
    """Stop Ptrace capture."""
    tracer = _get_tracer(device_id, body.port_number)
    await asyncio.to_thread(tracer.stop_ptrace)
    return {"status": "stopped"}


@router.get(
    "/devices/{device_id}/ltssm/ptrace/status",
    response_model=PtraceStatusResponse,
)
async def get_ptrace_status(
    device_id: str,
    port_number: int = Query(0, ge=0, le=143),
) -> PtraceStatusResponse:
    """Read current Ptrace capture status."""
    tracer = _get_tracer(device_id, port_number)
    return await asyncio.to_thread(tracer.read_ptrace_status)


@router.get(
    "/devices/{device_id}/ltssm/ptrace/buffer",
    response_model=PtraceCaptureResult,
)
async def get_ptrace_buffer(
    device_id: str,
    port_number: int = Query(0, ge=0, le=143),
    max_entries: int = Query(256, ge=1, le=4096),
) -> PtraceCaptureResult:
    """Read captured data from the Ptrace buffer.

    Runs in executor to avoid blocking the event loop on large reads.
    """
    tracer = _get_tracer(device_id, port_number)
    return await asyncio.to_thread(tracer.read_ptrace_buffer, max_entries)
