"""PTrace (Protocol Trace) API endpoints."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from calypso.exceptions import CalypsoError
from calypso.models.ptrace import (
    PTraceBufferResult,
    PTraceDirection,
    PTraceErrorTriggerCfg,
    PTraceEventCounterCfg,
    PTraceFilterCfg,
    PTraceFullConfigureRequest,
    PTraceStatus,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ptrace"])


def _get_switch(device_id: str):
    from calypso.api.app import get_device_registry

    registry = get_device_registry()
    sw = registry.get(device_id)
    if sw is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return sw


def _get_engine(device_id: str, port_number: int):
    from calypso.core.ptrace import PTraceEngine

    sw = _get_switch(device_id)
    return PTraceEngine(sw._device_obj, sw._device_key, port_number)


# ---------------------------------------------------------------------------
# Full configure
# ---------------------------------------------------------------------------


@router.post("/devices/{device_id}/ptrace/configure")
async def configure_ptrace(
    device_id: str,
    body: PTraceFullConfigureRequest,
) -> dict[str, str]:
    """Full PTrace configuration: disable, clear, configure, re-enable."""
    engine = _get_engine(device_id, body.port_number)
    try:
        await asyncio.to_thread(
            engine.full_configure,
            body.direction,
            body.capture,
            body.trigger,
            body.post_trigger,
        )
    except CalypsoError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "configured"}


# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------


@router.post("/devices/{device_id}/ptrace/filter")
async def configure_ptrace_filter(
    device_id: str,
    body: PTraceFilterCfg,
    port_number: int = Query(0, ge=0, le=143),
    direction: PTraceDirection = Query(PTraceDirection.INGRESS),
) -> dict[str, str]:
    """Write a 512-bit filter (match + mask)."""
    engine = _get_engine(device_id, port_number)
    try:
        await asyncio.to_thread(
            engine.write_filter,
            direction,
            body.filter_idx,
            body.match_hex,
            body.mask_hex,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CalypsoError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Start / Stop / Clear / Manual Trigger
# ---------------------------------------------------------------------------


class PTracePortDirRequest(BaseModel):
    port_number: int = Field(0, ge=0, le=143)
    direction: PTraceDirection = PTraceDirection.INGRESS


@router.post("/devices/{device_id}/ptrace/start")
async def start_ptrace(
    device_id: str,
    body: PTracePortDirRequest,
) -> dict[str, str]:
    """Start PTrace capture."""
    engine = _get_engine(device_id, body.port_number)
    try:
        await asyncio.to_thread(engine.start_capture, body.direction)
    except CalypsoError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "started"}


@router.post("/devices/{device_id}/ptrace/stop")
async def stop_ptrace(
    device_id: str,
    body: PTracePortDirRequest,
) -> dict[str, str]:
    """Stop PTrace capture."""
    engine = _get_engine(device_id, body.port_number)
    try:
        await asyncio.to_thread(engine.stop_capture, body.direction)
    except CalypsoError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "stopped"}


@router.post("/devices/{device_id}/ptrace/clear")
async def clear_ptrace(
    device_id: str,
    body: PTracePortDirRequest,
) -> dict[str, str]:
    """Clear the triggered flag."""
    engine = _get_engine(device_id, body.port_number)
    try:
        await asyncio.to_thread(engine.clear_triggered, body.direction)
    except CalypsoError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "cleared"}


@router.post("/devices/{device_id}/ptrace/manual-trigger")
async def manual_trigger_ptrace(
    device_id: str,
    body: PTracePortDirRequest,
) -> dict[str, str]:
    """Issue a manual trigger."""
    engine = _get_engine(device_id, body.port_number)
    try:
        await asyncio.to_thread(engine.manual_trigger, body.direction)
    except CalypsoError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "triggered"}


# ---------------------------------------------------------------------------
# Event counter
# ---------------------------------------------------------------------------


class PTraceEventCounterRequest(BaseModel):
    port_number: int = Field(0, ge=0, le=143)
    direction: PTraceDirection = PTraceDirection.INGRESS
    counter_id: int = Field(0, ge=0, le=1)
    event_source: int = Field(0, ge=0, le=63)
    threshold: int = Field(0, ge=0, le=0xFFFF)


@router.post("/devices/{device_id}/ptrace/event-counter")
async def configure_event_counter(
    device_id: str,
    body: PTraceEventCounterRequest,
) -> dict[str, str]:
    """Configure an event counter."""
    engine = _get_engine(device_id, body.port_number)
    cfg = PTraceEventCounterCfg(
        counter_id=body.counter_id,
        event_source=body.event_source,
        threshold=body.threshold,
    )
    try:
        await asyncio.to_thread(engine.configure_event_counter, body.direction, cfg)
    except CalypsoError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "configured"}


# ---------------------------------------------------------------------------
# Error trigger
# ---------------------------------------------------------------------------


class PTraceErrorTriggerRequest(BaseModel):
    port_number: int = Field(0, ge=0, le=143)
    direction: PTraceDirection = PTraceDirection.INGRESS
    error_mask: int = Field(0, ge=0, le=0x0FFFFFFF)


@router.post("/devices/{device_id}/ptrace/error-trigger")
async def configure_error_trigger(
    device_id: str,
    body: PTraceErrorTriggerRequest,
) -> dict[str, str]:
    """Configure error trigger enable mask."""
    engine = _get_engine(device_id, body.port_number)
    cfg = PTraceErrorTriggerCfg(error_mask=body.error_mask)
    try:
        await asyncio.to_thread(engine.configure_error_trigger, body.direction, cfg)
    except CalypsoError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "configured"}


# ---------------------------------------------------------------------------
# Status / Buffer reads
# ---------------------------------------------------------------------------


@router.get(
    "/devices/{device_id}/ptrace/status",
    response_model=PTraceStatus,
)
async def get_ptrace_status(
    device_id: str,
    port_number: int = Query(0, ge=0, le=143),
    direction: PTraceDirection = Query(PTraceDirection.INGRESS),
) -> PTraceStatus:
    """Read full PTrace status including timestamps."""
    engine = _get_engine(device_id, port_number)
    try:
        return await asyncio.to_thread(engine.read_status, direction)
    except CalypsoError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/devices/{device_id}/ptrace/buffer",
    response_model=PTraceBufferResult,
)
async def get_ptrace_buffer(
    device_id: str,
    port_number: int = Query(0, ge=0, le=143),
    direction: PTraceDirection = Query(PTraceDirection.INGRESS),
    max_rows: int = Query(256, ge=1, le=4096),
) -> PTraceBufferResult:
    """Read trace buffer contents."""
    engine = _get_engine(device_id, port_number)
    try:
        return await asyncio.to_thread(engine.read_buffer, direction, max_rows)
    except CalypsoError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
