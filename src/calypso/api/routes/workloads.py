"""Workload generation API endpoints."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from calypso.workloads.exceptions import (
    WorkloadAlreadyRunning,
    WorkloadBackendUnavailable,
    WorkloadError,
    WorkloadNotFoundError,
)
from calypso.workloads.models import (
    CombinedPerfView,
    WorkloadConfig,
    WorkloadStatus,
)

router = APIRouter(tags=["workloads"])

# Module-level singleton; created on first use
_manager = None


def _get_manager():
    """Lazy-initialize the WorkloadManager singleton."""
    global _manager
    if _manager is None:
        from calypso.workloads.manager import WorkloadManager
        _manager = WorkloadManager()
    return _manager


class BackendsResponse(BaseModel):
    """Available workload backends."""
    available: list[str]


@router.get("/workloads/backends", response_model=BackendsResponse)
async def list_backends() -> BackendsResponse:
    """List available workload backends (always works, even with none installed)."""
    mgr = _get_manager()
    return BackendsResponse(
        available=[b.value for b in mgr.available_backends],
    )


@router.post("/workloads/start", response_model=WorkloadStatus)
async def start_workload(config: WorkloadConfig) -> WorkloadStatus:
    """Start a new workload."""
    mgr = _get_manager()
    try:
        return await asyncio.to_thread(mgr.start_workload, config)
    except WorkloadBackendUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except WorkloadAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WorkloadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/workloads/{workload_id}/stop", response_model=WorkloadStatus)
async def stop_workload(workload_id: str) -> WorkloadStatus:
    """Stop a running workload."""
    mgr = _get_manager()
    try:
        return await asyncio.to_thread(mgr.stop_workload, workload_id)
    except WorkloadNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkloadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/workloads/{workload_id}", response_model=WorkloadStatus)
async def get_workload(workload_id: str) -> WorkloadStatus:
    """Get the status of a workload."""
    mgr = _get_manager()
    try:
        return await asyncio.to_thread(mgr.get_status, workload_id)
    except WorkloadNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/workloads", response_model=list[WorkloadStatus])
async def list_workloads() -> list[WorkloadStatus]:
    """List all workloads."""
    mgr = _get_manager()
    return await asyncio.to_thread(mgr.list_workloads)


@router.get(
    "/workloads/{workload_id}/combined/{device_id}",
    response_model=CombinedPerfView,
)
async def combined_view(workload_id: str, device_id: str) -> CombinedPerfView:
    """Get host workload stats combined with switch-side performance snapshot."""
    mgr = _get_manager()
    try:
        status = await asyncio.to_thread(mgr.get_status, workload_id)
    except WorkloadNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    workload_stats = None
    if status.result is not None:
        workload_stats = status.result.stats

    # Fetch switch-side snapshot if perf monitoring is active
    switch_snapshot = None
    try:
        from calypso.api.routes.performance import _monitors
        monitor = _monitors.get(device_id)
        if monitor is not None and hasattr(monitor, "read_snapshot"):
            snapshot = await asyncio.to_thread(monitor.read_snapshot)
            switch_snapshot = snapshot.model_dump()
    except ImportError:
        pass

    return CombinedPerfView(
        workload_id=workload_id,
        workload_stats=workload_stats,
        workload_state=status.state,
        switch_snapshot=switch_snapshot,
    )


@router.websocket("/workloads/{workload_id}/stream")
async def workload_stream(websocket: WebSocket, workload_id: str) -> None:
    """Stream live workload progress over WebSocket."""
    await websocket.accept()

    mgr = _get_manager()
    try:
        await asyncio.to_thread(mgr.get_status, workload_id)
    except WorkloadNotFoundError:
        await websocket.send_json({"error": f"Workload {workload_id} not found"})
        await websocket.close()
        return

    try:
        while True:
            await asyncio.sleep(1.0)
            try:
                status = await asyncio.to_thread(mgr.get_status, workload_id)
            except WorkloadNotFoundError:
                await websocket.send_json({"error": "Workload no longer exists"})
                break

            payload = status.model_dump()
            await websocket.send_json(payload)

            # Stop streaming once workload is no longer running
            if status.state.value not in ("pending", "running"):
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
