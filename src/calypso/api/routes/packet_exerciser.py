"""PCIe Packet Exerciser API endpoints."""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from calypso.exceptions import CalypsoError
from calypso.models.packet_exerciser import (
    CaptureAndSendRequest,
    DpBistRequest,
    DpBistStatus,
    ExerciserSendRequest,
    ExerciserStatus,
)
from calypso.models.ptrace import (
    PTraceBufferResult,
    PTraceCaptureCfg,
    PTraceDirection,
    PTracePostTriggerCfg,
    PTraceStatus,
    PTraceTriggerCfg,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["packet-exerciser"])


def _get_switch(device_id: str):
    from calypso.api.app import get_device_registry

    registry = get_device_registry()
    sw = registry.get(device_id)
    if sw is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return sw


def _get_engine(device_id: str, port_number: int):
    from calypso.core.packet_exerciser import PacketExerciserEngine

    sw = _get_switch(device_id)
    return PacketExerciserEngine(sw._device_obj, sw._device_key, port_number)


def _get_ptrace_engine(device_id: str, port_number: int):
    from calypso.core.ptrace import PTraceEngine

    sw = _get_switch(device_id)
    return PTraceEngine(sw._device_obj, sw._device_key, port_number)


# ---------------------------------------------------------------------------
# Send TLPs
# ---------------------------------------------------------------------------


@router.post("/devices/{device_id}/exerciser/send")
async def send_tlps(
    device_id: str,
    body: ExerciserSendRequest,
) -> dict[str, str]:
    """Send TLPs via the packet exerciser."""
    engine = _get_engine(device_id, body.port_number)
    try:
        await asyncio.to_thread(
            engine.send_tlps,
            body.tlps,
            infinite_loop=body.infinite_loop,
            max_outstanding_np=body.max_outstanding_np,
        )
    except CalypsoError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "started"}


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------


@router.post("/devices/{device_id}/exerciser/stop")
async def stop_exerciser(
    device_id: str,
    port_number: int = Query(0, ge=0, le=143),
) -> dict[str, str]:
    """Stop all exerciser threads."""
    engine = _get_engine(device_id, port_number)
    try:
        await asyncio.to_thread(engine.stop)
    except CalypsoError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "stopped"}


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


@router.get(
    "/devices/{device_id}/exerciser/status",
    response_model=ExerciserStatus,
)
async def get_exerciser_status(
    device_id: str,
    port_number: int = Query(0, ge=0, le=143),
) -> ExerciserStatus:
    """Read exerciser + completion status."""
    engine = _get_engine(device_id, port_number)
    try:
        return await asyncio.to_thread(engine.read_status)
    except CalypsoError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Composite: PTrace + Send
# ---------------------------------------------------------------------------


class CaptureAndSendResponse(BaseModel):
    """Response from the composite capture-and-send workflow."""

    exerciser_status: ExerciserStatus
    ptrace_status: PTraceStatus | None = None
    ptrace_buffer: PTraceBufferResult | None = None


@router.post(
    "/devices/{device_id}/exerciser/capture-and-send",
    response_model=CaptureAndSendResponse,
)
async def capture_and_send(
    device_id: str,
    body: CaptureAndSendRequest,
) -> CaptureAndSendResponse:
    """Composite workflow: configure PTrace -> start capture -> send TLPs -> read buffer.

    Orchestrates the full sequence server-side for tight timing:
    1. Configure PTrace for egress capture on the port
    2. Start PTrace capture
    3. Send exerciser TLPs
    4. Wait for capture to complete
    5. Read back the PTrace buffer
    """
    pkt_engine = _get_engine(device_id, body.port_number)
    ptrace_engine = _get_ptrace_engine(device_id, body.port_number)
    direction = PTraceDirection(body.ptrace_direction)

    def _run():
        # 1. Configure PTrace with defaults for exerciser capture
        capture_cfg = PTraceCaptureCfg(
            direction=direction,
            port_number=body.port_number,
            idle_filt=True,
            nop_filt=True,
        )
        trigger_cfg = PTraceTriggerCfg(trigger_src=0)  # manual trigger
        post_trigger_cfg = PTracePostTriggerCfg()

        ptrace_engine.full_configure(
            direction,
            capture_cfg,
            trigger_cfg,
            post_trigger_cfg,
        )

        # 2. Start PTrace capture
        ptrace_engine.start_capture(direction)

        # 3. Send exerciser TLPs
        exer = body.exerciser
        pkt_engine.send_tlps(
            exer.tlps,
            infinite_loop=exer.infinite_loop,
            max_outstanding_np=exer.max_outstanding_np,
        )

        # 4. Wait for exerciser to complete and PTrace to capture
        time.sleep(body.post_trigger_wait_ms / 1000.0)

        # 5. Manual trigger PTrace and stop capture
        ptrace_engine.manual_trigger(direction)
        time.sleep(0.01)
        ptrace_engine.stop_capture(direction)

        # 6. Read results
        exer_status = pkt_engine.read_status()
        ptrace_status = ptrace_engine.read_status(direction)

        ptrace_buffer = None
        if body.read_buffer:
            ptrace_buffer = ptrace_engine.read_buffer(direction, max_rows=256)

        # 7. Stop exerciser
        pkt_engine.stop()

        return CaptureAndSendResponse(
            exerciser_status=exer_status,
            ptrace_status=ptrace_status,
            ptrace_buffer=ptrace_buffer,
        )

    try:
        return await asyncio.to_thread(_run)
    except CalypsoError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# DP BIST
# ---------------------------------------------------------------------------


@router.post("/devices/{device_id}/exerciser/dp-bist/start")
async def start_dp_bist(
    device_id: str,
    body: DpBistRequest,
    port_number: int = Query(0, ge=0, le=143),
) -> dict[str, str]:
    """Start DP BIST TLP generation."""
    engine = _get_engine(device_id, port_number)
    try:
        await asyncio.to_thread(
            engine.start_dp_bist,
            loop_count=body.loop_count,
            inner_loop_count=body.inner_loop_count,
            delay=body.delay_count,
            infinite=body.infinite,
        )
    except CalypsoError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "started"}


@router.post("/devices/{device_id}/exerciser/dp-bist/stop")
async def stop_dp_bist(
    device_id: str,
    port_number: int = Query(0, ge=0, le=143),
) -> dict[str, str]:
    """Stop DP BIST."""
    engine = _get_engine(device_id, port_number)
    try:
        await asyncio.to_thread(engine.stop_dp_bist)
    except CalypsoError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "stopped"}


@router.get(
    "/devices/{device_id}/exerciser/dp-bist/status",
    response_model=DpBistStatus,
)
async def get_dp_bist_status(
    device_id: str,
    port_number: int = Query(0, ge=0, le=143),
) -> DpBistStatus:
    """Read DP BIST status."""
    engine = _get_engine(device_id, port_number)
    try:
        return await asyncio.to_thread(engine.read_dp_bist_status)
    except CalypsoError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
