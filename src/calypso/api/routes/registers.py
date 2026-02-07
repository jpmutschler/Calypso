"""PCIe config space, AER, link control, and device control API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
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

router = APIRouter(tags=["registers"])


def _get_switch(device_id: str):
    from calypso.api.app import get_device_registry
    registry = get_device_registry()
    sw = registry.get(device_id)
    if sw is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return sw


def _get_config_reader(device_id: str):
    from calypso.core.pcie_config import PcieConfigReader
    sw = _get_switch(device_id)
    return PcieConfigReader(sw._device_obj, sw._device_key)


# --- Config space ---


@router.get("/devices/{device_id}/config-space", response_model=ConfigSpaceDump)
async def get_config_space(
    device_id: str, offset: int = 0, count: int = 64
) -> ConfigSpaceDump:
    """Read a range of PCIe config space registers."""
    reader = _get_config_reader(device_id)
    registers = reader.dump_config_space(offset=offset, count=count)
    caps = reader.walk_capabilities() + reader.walk_extended_capabilities()
    sw = _get_switch(device_id)
    port_number = sw._device_key.PlxPort if sw._device_key else 0
    return ConfigSpaceDump(
        port_number=port_number,
        registers=registers,
        capabilities=caps,
    )


@router.get(
    "/devices/{device_id}/capabilities", response_model=list[PcieCapabilityInfo]
)
async def get_capabilities(device_id: str) -> list[PcieCapabilityInfo]:
    """List all PCI and PCIe extended capabilities."""
    reader = _get_config_reader(device_id)
    return reader.walk_capabilities() + reader.walk_extended_capabilities()


# --- Device control ---


@router.get(
    "/devices/{device_id}/device-control", response_model=DeviceControlStatus
)
async def get_device_control(device_id: str) -> DeviceControlStatus:
    """Read current device control and status."""
    reader = _get_config_reader(device_id)
    return reader.get_device_control()


class DeviceControlRequest(BaseModel):
    mps: int | None = None
    mrrs: int | None = None


@router.post(
    "/devices/{device_id}/device-control", response_model=DeviceControlStatus
)
async def set_device_control(
    device_id: str, body: DeviceControlRequest
) -> DeviceControlStatus:
    """Modify MPS and/or MRRS in the device control register."""
    reader = _get_config_reader(device_id)
    return reader.set_device_control(mps=body.mps, mrrs=body.mrrs)


# --- Link ---


class LinkResponse(BaseModel):
    capabilities: LinkCapabilities
    status: LinkControlStatus


@router.get("/devices/{device_id}/link", response_model=LinkResponse)
async def get_link(device_id: str) -> LinkResponse:
    """Read link capabilities and current status."""
    reader = _get_config_reader(device_id)
    return LinkResponse(
        capabilities=reader.get_link_capabilities(),
        status=reader.get_link_status(),
    )


@router.post("/devices/{device_id}/link/retrain")
async def retrain_link(device_id: str) -> dict[str, str]:
    """Initiate link retraining."""
    reader = _get_config_reader(device_id)
    reader.retrain_link()
    return {"status": "retraining"}


class TargetSpeedRequest(BaseModel):
    speed: int


@router.post("/devices/{device_id}/link/target-speed")
async def set_target_speed(device_id: str, body: TargetSpeedRequest) -> dict[str, str]:
    """Set target link speed (1=Gen1 through 6=Gen6)."""
    if body.speed < 1 or body.speed > 6:
        raise HTTPException(status_code=400, detail="Speed must be 1-6")
    reader = _get_config_reader(device_id)
    reader.set_target_link_speed(body.speed)
    full = SPEED_STRINGS[PCIeLinkSpeed(body.speed)]
    gen_name = full.split(" ")[0]  # "Gen4 (16.0 GT/s)" -> "Gen4"
    return {"status": "set", "target_speed": gen_name}


# --- AER ---


@router.get("/devices/{device_id}/aer", response_model=AerStatus | None)
async def get_aer(device_id: str) -> AerStatus | None:
    """Read AER extended capability status. Returns null if AER not present."""
    reader = _get_config_reader(device_id)
    return reader.get_aer_status()


@router.post("/devices/{device_id}/aer/clear")
async def clear_aer(device_id: str) -> dict[str, str]:
    """Clear all AER error status registers."""
    reader = _get_config_reader(device_id)
    reader.clear_aer_errors()
    return {"status": "cleared"}
