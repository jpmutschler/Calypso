"""PCIe config space, AER, link control, and device control API endpoints."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from calypso.hardware.pcie_registers import PCIeLinkSpeed, SPEED_STRINGS
from calypso.models.pcie_config import (
    AerStatus,
    ConfigSpaceDump,
    DeviceControlStatus,
    LinkCapabilities,
    LinkControlStatus,
    PcieCapabilityInfo,
)
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["registers"])


def _get_switch(device_id: str):
    from calypso.api.app import get_device_registry

    registry = get_device_registry()
    sw = registry.get(device_id)
    if sw is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return sw


def _get_config_reader_for_port(
    device_id: str, port_number: int | None = None
) -> tuple[object, Callable[[], None]]:
    """Return a (PcieConfigReader, cleanup_fn) tuple for the given port.

    When port_number is None or matches the management port, uses the
    existing device handle (cleanup is no-op). Otherwise, opens a new
    device handle for the target port via find_port_key().
    """
    from calypso.core.pcie_config import PcieConfigReader
    from calypso.core.port_utils import find_port_key
    from calypso.sdk import device as sdk_device

    sw = _get_switch(device_id)
    mgmt_key = sw._device_key

    if port_number is None:
        return PcieConfigReader(sw._device_obj, mgmt_key), lambda: None

    mgmt_port = sdk_device.get_port_properties(sw._device_obj).PortNumber
    if port_number == mgmt_port:
        return PcieConfigReader(sw._device_obj, mgmt_key), lambda: None

    target_key = find_port_key(mgmt_key, port_number)
    if target_key is None:
        raise HTTPException(
            status_code=404,
            detail=f"Port {port_number} not found on this switch",
        )

    dev = sdk_device.open_device(target_key)
    try:
        reader = PcieConfigReader(dev, target_key)
    except Exception:
        sdk_device.close_device(dev)
        raise

    def cleanup():
        try:
            sdk_device.close_device(dev)
        except Exception:
            pass

    return reader, cleanup


# --- Config space ---


@router.get("/devices/{device_id}/config-space", response_model=ConfigSpaceDump)
async def get_config_space(
    device_id: str,
    offset: int = Query(0, ge=0, le=0xFFC),
    count: int = Query(64, ge=1, le=1024),
    port_number: int | None = Query(None),
) -> ConfigSpaceDump:
    """Read a range of PCIe config space registers."""
    if offset % 4 != 0:
        raise HTTPException(status_code=400, detail="Offset must be DWORD-aligned")

    def _read() -> ConfigSpaceDump:
        reader, cleanup = _get_config_reader_for_port(device_id, port_number)
        try:
            registers = reader.dump_config_space(offset=offset, count=count)
            caps = reader.walk_capabilities() + reader.walk_extended_capabilities()
            existing = {r.offset for r in registers}
            cap_regs = reader.read_capability_registers(caps, existing)
            all_registers = registers + cap_regs
            pn = port_number if port_number is not None else 0
            return ConfigSpaceDump(
                port_number=pn,
                registers=all_registers,
                capabilities=caps,
            )
        finally:
            cleanup()

    return await asyncio.to_thread(_read)


@router.get("/devices/{device_id}/capabilities", response_model=list[PcieCapabilityInfo])
async def get_capabilities(
    device_id: str,
    port_number: int | None = Query(None),
) -> list[PcieCapabilityInfo]:
    """List all PCI and PCIe extended capabilities."""

    def _read() -> list[PcieCapabilityInfo]:
        reader, cleanup = _get_config_reader_for_port(device_id, port_number)
        try:
            return reader.walk_capabilities() + reader.walk_extended_capabilities()
        finally:
            cleanup()

    return await asyncio.to_thread(_read)


# --- Device control ---


@router.get("/devices/{device_id}/device-control", response_model=DeviceControlStatus)
async def get_device_control(
    device_id: str,
    port_number: int | None = Query(None),
) -> DeviceControlStatus:
    """Read current device control and status."""

    def _read() -> DeviceControlStatus:
        reader, cleanup = _get_config_reader_for_port(device_id, port_number)
        try:
            return reader.get_device_control()
        finally:
            cleanup()

    return await asyncio.to_thread(_read)


class DeviceControlRequest(BaseModel):
    mps: int | None = None
    mrrs: int | None = None


@router.post("/devices/{device_id}/device-control", response_model=DeviceControlStatus)
async def set_device_control(
    device_id: str,
    body: DeviceControlRequest,
    port_number: int | None = Query(None),
) -> DeviceControlStatus:
    """Modify MPS and/or MRRS in the device control register."""

    def _write() -> DeviceControlStatus:
        reader, cleanup = _get_config_reader_for_port(device_id, port_number)
        try:
            return reader.set_device_control(body.mps, body.mrrs)
        finally:
            cleanup()

    return await asyncio.to_thread(_write)


# --- Link ---


class LinkResponse(BaseModel):
    capabilities: LinkCapabilities
    status: LinkControlStatus


@router.get("/devices/{device_id}/link", response_model=LinkResponse)
async def get_link(
    device_id: str,
    port_number: int | None = Query(None),
) -> LinkResponse:
    """Read link capabilities and current status."""

    def _read() -> LinkResponse:
        reader, cleanup = _get_config_reader_for_port(device_id, port_number)
        try:
            return LinkResponse(
                capabilities=reader.get_link_capabilities(),
                status=reader.get_link_status(),
            )
        finally:
            cleanup()

    return await asyncio.to_thread(_read)


@router.post("/devices/{device_id}/link/retrain")
async def retrain_link(
    device_id: str,
    port_number: int | None = Query(None),
) -> dict[str, str]:
    """Initiate link retraining."""

    def _do() -> dict[str, str]:
        reader, cleanup = _get_config_reader_for_port(device_id, port_number)
        try:
            reader.retrain_link()
            return {"status": "retraining"}
        finally:
            cleanup()

    return await asyncio.to_thread(_do)


class TargetSpeedRequest(BaseModel):
    speed: int


@router.post("/devices/{device_id}/link/target-speed")
async def set_target_speed(
    device_id: str,
    body: TargetSpeedRequest,
    port_number: int | None = Query(None),
) -> dict[str, str]:
    """Set target link speed (1=Gen1 through 6=Gen6)."""
    if body.speed < 1 or body.speed > 6:
        raise HTTPException(status_code=400, detail="Speed must be 1-6")

    def _do() -> dict[str, str]:
        reader, cleanup = _get_config_reader_for_port(device_id, port_number)
        try:
            reader.set_target_link_speed(body.speed)
            full = SPEED_STRINGS[PCIeLinkSpeed(body.speed)]
            gen_name = full.split(" ")[0]
            return {"status": "set", "target_speed": gen_name}
        finally:
            cleanup()

    return await asyncio.to_thread(_do)


# --- AER ---


@router.get("/devices/{device_id}/aer", response_model=AerStatus | None)
async def get_aer(
    device_id: str,
    port_number: int | None = Query(None),
) -> AerStatus | None:
    """Read AER extended capability status. Returns null if AER not present."""

    def _read() -> AerStatus | None:
        reader, cleanup = _get_config_reader_for_port(device_id, port_number)
        try:
            return reader.get_aer_status()
        finally:
            cleanup()

    return await asyncio.to_thread(_read)


@router.post("/devices/{device_id}/aer/clear")
async def clear_aer(
    device_id: str,
    port_number: int | None = Query(None),
) -> dict[str, str]:
    """Clear all AER error status registers."""

    def _do() -> dict[str, str]:
        reader, cleanup = _get_config_reader_for_port(device_id, port_number)
        try:
            reader.clear_aer_errors()
            return {"status": "cleared"}
        finally:
            cleanup()

    return await asyncio.to_thread(_do)


# --- Config write ---


class ConfigWriteRequest(BaseModel):
    offset: int
    value: int


@router.post("/devices/{device_id}/config-write")
async def write_config_register(
    device_id: str,
    body: ConfigWriteRequest,
    port_number: int | None = Query(None),
) -> dict[str, str]:
    """Write a single DWORD to PCIe config space.

    Offset must be 0-0xFFF and DWORD-aligned.
    """
    if body.offset < 0 or body.offset > 0xFFF:
        raise HTTPException(status_code=400, detail="Offset must be 0x000-0xFFF")
    if body.offset % 4 != 0:
        raise HTTPException(status_code=400, detail="Offset must be DWORD-aligned (multiple of 4)")
    if body.value < 0 or body.value > 0xFFFFFFFF:
        raise HTTPException(status_code=400, detail="Value must be 0x00000000-0xFFFFFFFF")

    logger.warning(
        "config_space_write",
        device_id=device_id,
        port_number=port_number,
        offset=f"0x{body.offset:03X}",
        value=f"0x{body.value:08X}",
    )

    def _do() -> dict[str, str]:
        reader, cleanup = _get_config_reader_for_port(device_id, port_number)
        try:
            reader.write_config_register(body.offset, body.value)
            return {
                "status": "written",
                "offset": f"0x{body.offset:03X}",
                "value": f"0x{body.value:08X}",
            }
        finally:
            cleanup()

    return await asyncio.to_thread(_do)
