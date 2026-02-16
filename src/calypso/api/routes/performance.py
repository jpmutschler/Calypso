"""Performance monitoring API endpoints."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from calypso.models.performance import PerfSnapshot

router = APIRouter(tags=["performance"])

# Per-device perf monitors
_monitors: dict[str, object] = {}


def _get_switch(device_id: str):
    from calypso.api.app import get_device_registry
    registry = get_device_registry()
    sw = registry.get(device_id)
    if sw is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return sw


@router.post("/devices/{device_id}/perf/start")
async def start_perf(device_id: str) -> dict[str, str]:
    """Start performance monitoring."""
    from calypso.core.perf_monitor import PerfMonitor
    sw = _get_switch(device_id)

    def _start():
        monitor = PerfMonitor(sw._device_obj, sw._device_key)
        monitor.initialize()
        monitor.start()
        return monitor

    monitor = await asyncio.to_thread(_start)
    _monitors[device_id] = monitor
    return {"status": "started", "ports": str(monitor.num_ports)}


@router.post("/devices/{device_id}/perf/stop")
async def stop_perf(device_id: str) -> dict[str, str]:
    """Stop performance monitoring."""
    monitor = _monitors.pop(device_id, None)
    if monitor is not None and hasattr(monitor, "stop"):
        monitor.stop()
    return {"status": "stopped"}


@router.get("/devices/{device_id}/perf/snapshot", response_model=PerfSnapshot)
async def get_perf_snapshot(device_id: str) -> PerfSnapshot:
    """Get current performance snapshot."""
    monitor = _monitors.get(device_id)
    if monitor is None or not hasattr(monitor, "read_snapshot"):
        raise HTTPException(status_code=400, detail="Performance monitoring not started")
    return await asyncio.to_thread(monitor.read_snapshot)


@router.websocket("/devices/{device_id}/perf/stream")
async def perf_stream(websocket: WebSocket, device_id: str) -> None:
    """Stream performance snapshots over WebSocket."""
    from calypso.core.perf_monitor import PerfMonitor

    await websocket.accept()

    sw = None
    try:
        from calypso.api.app import get_device_registry
        registry = get_device_registry()
        sw = registry.get(device_id)
        if sw is None:
            await websocket.send_json({"error": "Device not found"})
            await websocket.close()
            return
    except Exception as exc:
        await websocket.send_json({"error": str(exc)})
        await websocket.close()
        return

    monitor = _monitors.get(device_id)
    if monitor is None:

        def _start():
            m = PerfMonitor(sw._device_obj, sw._device_key)
            m.initialize()
            m.start()
            return m

        monitor = await asyncio.to_thread(_start)
        _monitors[device_id] = monitor

    try:
        while True:
            await asyncio.sleep(1.0)
            snapshot = await asyncio.to_thread(monitor.read_snapshot)
            await websocket.send_json(snapshot.model_dump())
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
