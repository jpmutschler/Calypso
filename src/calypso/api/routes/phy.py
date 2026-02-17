"""PHY layer monitoring and diagnostics API endpoints."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from calypso.exceptions import CalypsoError
from calypso.models.pcie_config import EqStatus16GT, EqStatus32GT, SupportedSpeedsVector
from calypso.models.phy_api import (
    EyeSweepResult,
    LaneMarginCapabilitiesResponse,
    SweepProgress,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["phy"])


def _get_switch(device_id: str):
    from calypso.api.app import get_device_registry
    registry = get_device_registry()
    sw = registry.get(device_id)
    if sw is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return sw


def _get_phy_monitor(device_id: str, port_number: int = 0):
    from calypso.core.phy_monitor import PhyMonitor
    sw = _get_switch(device_id)
    return PhyMonitor(sw._device_obj, sw._device_key, port_number)


def _get_config_reader(device_id: str):
    from calypso.core.pcie_config import PcieConfigReader
    sw = _get_switch(device_id)
    return PcieConfigReader(sw._device_obj, sw._device_key)


# --- Supported Speeds ---


@router.get(
    "/devices/{device_id}/phy/speeds",
    response_model=SupportedSpeedsVector,
)
async def get_supported_speeds(device_id: str) -> SupportedSpeedsVector:
    """Read supported link speeds vector from Link Capabilities 2."""
    reader = _get_config_reader(device_id)
    return await asyncio.to_thread(reader.get_supported_speeds)


# --- Equalization Status ---


class EqStatusResponse(BaseModel):
    eq_16gt: EqStatus16GT | None = None
    eq_32gt: EqStatus32GT | None = None


@router.get(
    "/devices/{device_id}/phy/eq-status",
    response_model=EqStatusResponse,
)
async def get_eq_status(device_id: str) -> EqStatusResponse:
    """Read equalization status from 16 GT/s and 32 GT/s PHY layer capabilities."""
    reader = _get_config_reader(device_id)

    def _read():
        return EqStatusResponse(
            eq_16gt=reader.get_eq_status_16gt(),
            eq_32gt=reader.get_eq_status_32gt(),
        )

    return await asyncio.to_thread(_read)


# --- Lane EQ Settings ---


class LaneEqEntry(BaseModel):
    lane: int
    downstream_tx_preset: int
    downstream_rx_hint: int
    upstream_tx_preset: int
    upstream_rx_hint: int


class LaneEqResponse(BaseModel):
    lanes: list[LaneEqEntry] = Field(default_factory=list)


@router.get(
    "/devices/{device_id}/phy/lane-eq",
    response_model=LaneEqResponse,
)
async def get_lane_eq(
    device_id: str,
    port_number: int = Query(0, ge=0, le=143),
    num_lanes: int = Query(16, ge=1, le=16),
) -> LaneEqResponse:
    """Read per-lane equalization control settings from 16 GT/s PHY capability."""
    monitor = _get_phy_monitor(device_id, port_number)

    def _read():
        settings = monitor.get_lane_eq_settings_16gt(num_lanes=num_lanes)
        return LaneEqResponse(
            lanes=[
                LaneEqEntry(
                    lane=s.lane,
                    downstream_tx_preset=int(s.downstream_tx_preset),
                    downstream_rx_hint=int(s.downstream_rx_hint),
                    upstream_tx_preset=int(s.upstream_tx_preset),
                    upstream_rx_hint=int(s.upstream_rx_hint),
                )
                for s in settings
            ]
        )

    return await asyncio.to_thread(_read)


# --- SerDes Diagnostics ---


class SerDesDiagEntry(BaseModel):
    lane: int
    synced: bool
    error_count: int
    expected_data: int
    actual_data: int


class SerDesDiagResponse(BaseModel):
    port_number: int
    lanes: list[SerDesDiagEntry] = Field(default_factory=list)


@router.get(
    "/devices/{device_id}/phy/serdes-diag",
    response_model=SerDesDiagResponse,
)
async def get_serdes_diag(
    device_id: str,
    port_number: int = Query(0, ge=0, le=143),
    num_lanes: int = Query(16, ge=1, le=16),
) -> SerDesDiagResponse:
    """Read SerDes diagnostic data (sync status, error counts) for all lanes."""
    monitor = _get_phy_monitor(device_id, port_number)

    def _read():
        diags = monitor.get_all_serdes_diag(num_lanes=num_lanes)
        return SerDesDiagResponse(
            port_number=port_number,
            lanes=[
                SerDesDiagEntry(
                    lane=i,
                    synced=d.utp_sync,
                    error_count=d.utp_error_count,
                    expected_data=d.utp_expected_data,
                    actual_data=d.utp_actual_data,
                )
                for i, d in enumerate(diags)
            ],
        )

    return await asyncio.to_thread(_read)


class ClearSerDesRequest(BaseModel):
    lane: int = Field(ge=0, le=15)


@router.post("/devices/{device_id}/phy/serdes-diag/clear")
async def clear_serdes_errors(
    device_id: str,
    body: ClearSerDesRequest,
    port_number: int = Query(0, ge=0, le=143),
) -> dict[str, str]:
    """Clear SerDes error counter for a specific lane."""
    monitor = _get_phy_monitor(device_id, port_number)
    await asyncio.to_thread(monitor.clear_serdes_errors, body.lane)
    return {"status": "cleared", "lane": str(body.lane)}


# --- Port Control ---


class PortControlResponse(BaseModel):
    disable_port: bool
    port_quiet: bool
    lock_down_fe_preset: bool
    test_pattern_rate: int
    bypass_utp_alignment: int
    port_select: int


@router.get(
    "/devices/{device_id}/phy/port-control",
    response_model=PortControlResponse,
)
async def get_port_control(
    device_id: str,
    port_number: int = Query(0, ge=0, le=143),
) -> PortControlResponse:
    """Read the vendor-specific Port Control Register (0x3208)."""
    monitor = _get_phy_monitor(device_id, port_number)

    def _read():
        ctrl = monitor.get_port_control()
        return PortControlResponse(
            disable_port=ctrl.disable_port,
            port_quiet=ctrl.port_quiet,
            lock_down_fe_preset=ctrl.lock_down_fe_preset,
            test_pattern_rate=int(ctrl.test_pattern_rate),
            bypass_utp_alignment=ctrl.bypass_utp_alignment,
            port_select=ctrl.port_select,
        )

    try:
        return await asyncio.to_thread(_read)
    except CalypsoError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read Port Control register for port {port_number}: {exc}",
        ) from exc


# --- PHY Command/Status ---


class PhyCmdStatusResponse(BaseModel):
    num_ports: int
    upstream_crosslink_enable: bool
    downstream_crosslink_enable: bool
    lane_reversal_disable: bool
    ltssm_wdt_disable: bool
    ltssm_wdt_port_select: int
    utp_kcode_flags: int


@router.get(
    "/devices/{device_id}/phy/cmd-status",
    response_model=PhyCmdStatusResponse,
)
async def get_phy_cmd_status(
    device_id: str,
    port_number: int = Query(0, ge=0, le=143),
) -> PhyCmdStatusResponse:
    """Read the PHY Command/Status Register (0x321C)."""
    monitor = _get_phy_monitor(device_id, port_number)

    def _read():
        status = monitor.get_phy_cmd_status()
        return PhyCmdStatusResponse(
            num_ports=status.num_ports,
            upstream_crosslink_enable=status.upstream_crosslink_enable,
            downstream_crosslink_enable=status.downstream_crosslink_enable,
            lane_reversal_disable=status.lane_reversal_disable,
            ltssm_wdt_disable=status.ltssm_wdt_disable,
            ltssm_wdt_port_select=status.ltssm_wdt_port_select,
            utp_kcode_flags=status.utp_kcode_flags,
        )

    try:
        return await asyncio.to_thread(_read)
    except CalypsoError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read PHY Command/Status register for port {port_number}: {exc}",
        ) from exc


# --- Lane Margining Detection ---


@router.get("/devices/{device_id}/phy/lane-margining")
async def get_lane_margining(device_id: str) -> dict[str, bool | int | None]:
    """Check if Lane Margining at Receiver capability is present."""
    reader = _get_config_reader(device_id)
    offset = await asyncio.to_thread(reader.get_lane_margining_offset)
    return {
        "supported": offset is not None,
        "capability_offset": offset,
    }


# --- UTP Operations ---


class UTPLoadRequest(BaseModel):
    """Load a user test pattern. Either use a preset name or provide raw hex bytes."""
    preset: str | None = None  # "prbs7", "prbs15", "prbs31", "alternating", "walking_ones", "zeros", "ones"
    pattern_hex: str | None = None  # 32 hex chars (16 bytes)


class UTPResultEntry(BaseModel):
    lane: int
    synced: bool
    error_count: int
    passed: bool
    error_rate: str
    expected_on_error: int | None = None
    actual_on_error: int | None = None


class UTPResultsResponse(BaseModel):
    port_number: int
    results: list[UTPResultEntry] = Field(default_factory=list)


@router.post("/devices/{device_id}/phy/utp/load")
async def load_utp(
    device_id: str,
    body: UTPLoadRequest,
    port_number: int = Query(0, ge=0, le=143),
) -> dict[str, str]:
    """Load a User Test Pattern into the UTP registers."""
    from calypso.hardware.atlas3_phy import UTP_PRESET_NAMES, UserTestPattern, get_utp_preset

    if body.preset:
        try:
            pattern = get_utp_preset(body.preset)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown preset '{body.preset}'. Options: {', '.join(UTP_PRESET_NAMES)}",
            )
    elif body.pattern_hex:
        try:
            raw = bytes.fromhex(body.pattern_hex)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid hex string")
        if len(raw) != 16:
            raise HTTPException(status_code=400, detail="Pattern must be exactly 16 bytes (32 hex chars)")
        pattern = UserTestPattern(pattern=raw)
    else:
        raise HTTPException(status_code=400, detail="Provide either 'preset' or 'pattern_hex'")

    monitor = _get_phy_monitor(device_id, port_number)
    await asyncio.to_thread(monitor.load_utp, pattern)
    return {"status": "loaded", "pattern": pattern.pattern.hex()}


@router.get(
    "/devices/{device_id}/phy/utp/results",
    response_model=UTPResultsResponse,
)
async def get_utp_results(
    device_id: str,
    port_number: int = Query(0, ge=0, le=143),
    num_lanes: int = Query(16, ge=1, le=16),
) -> UTPResultsResponse:
    """Collect UTP test results from SerDes diagnostic registers."""
    monitor = _get_phy_monitor(device_id, port_number)

    def _read():
        results = monitor.collect_utp_results(num_lanes=num_lanes)
        return UTPResultsResponse(
            port_number=port_number,
            results=[
                UTPResultEntry(
                    lane=r.lane,
                    synced=r.synced,
                    error_count=r.error_count,
                    passed=r.passed,
                    error_rate=r.error_rate,
                    expected_on_error=r.expected_on_error,
                    actual_on_error=r.actual_on_error,
                )
                for r in results
            ],
        )

    return await asyncio.to_thread(_read)


class UTPPrepareRequest(BaseModel):
    preset: str = "prbs7"
    rate: int = Field(2, ge=0, le=5, description="TestPatternRate: 0=2.5GT, 1=5GT, 2=8GT, 3=16GT, 4=32GT, 5=64GT")
    port_select: int = Field(0, ge=0, le=15)


@router.post("/devices/{device_id}/phy/utp/prepare")
async def prepare_utp_test(
    device_id: str,
    body: UTPPrepareRequest,
    port_number: int = Query(0, ge=0, le=143),
) -> dict[str, str]:
    """Prepare a port for UTP testing (disable, set rate, load pattern)."""
    from calypso.hardware.atlas3_phy import TestPatternRate, UTP_PRESET_NAMES, get_utp_preset

    try:
        pattern = get_utp_preset(body.preset)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown preset '{body.preset}'. Options: {', '.join(UTP_PRESET_NAMES)}",
        )

    rate = TestPatternRate(body.rate)

    monitor = _get_phy_monitor(device_id, port_number)
    await asyncio.to_thread(
        monitor.prepare_utp_test, pattern=pattern, rate=rate, port_select=body.port_select,
    )
    return {"status": "prepared", "pattern": body.preset, "rate": rate.name}


# --- Lane Margining Sweep (Eye Diagram) ---


@router.get(
    "/devices/{device_id}/phy/margining/capabilities",
    response_model=LaneMarginCapabilitiesResponse,
)
async def get_margining_capabilities(
    device_id: str,
    port_number: int = Query(0, ge=0, le=143),
    lane: int = Query(0, ge=0, le=15),
) -> LaneMarginCapabilitiesResponse:
    """Read lane margining capabilities for a port via the command protocol."""
    sw = _get_switch(device_id)

    def _read():
        from calypso.core.lane_margining import LaneMarginingEngine
        engine = LaneMarginingEngine(sw._device_obj, sw._device_key, port_number)
        caps = engine.get_capabilities(lane=lane)
        return LaneMarginCapabilitiesResponse(
            max_timing_offset=caps.max_timing_offset,
            max_voltage_offset=caps.max_voltage_offset,
            num_timing_steps=caps.num_timing_steps,
            num_voltage_steps=caps.num_voltage_steps,
            ind_up_down_voltage=caps.ind_up_down_voltage,
            ind_left_right_timing=caps.ind_left_right_timing,
        )

    try:
        return await asyncio.to_thread(_read)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


class SweepRequest(BaseModel):
    lane: int = Field(ge=0, le=15)
    port_number: int = Field(0, ge=0, le=143)
    receiver: int = Field(0, ge=0, le=3, description="0=broadcast, 1=A, 2=B, 3=C")


@router.post("/devices/{device_id}/phy/margining/sweep")
async def start_margining_sweep(
    device_id: str,
    body: SweepRequest,
) -> dict[str, str]:
    """Start a background lane margining sweep for eye diagram data."""
    from calypso.core.lane_margining import get_sweep_progress
    from calypso.models.phy import MarginingReceiverNumber

    progress = get_sweep_progress(device_id, body.lane)
    if progress.status == "running":
        raise HTTPException(status_code=409, detail="Sweep already running on this lane")

    sw = _get_switch(device_id)
    receiver = MarginingReceiverNumber(body.receiver)

    def _run_sweep():
        from calypso.core.lane_margining import LaneMarginingEngine
        try:
            engine = LaneMarginingEngine(sw._device_obj, sw._device_key, body.port_number)
            engine.sweep_lane(body.lane, device_id, receiver)
        except Exception:
            logger.exception("Background sweep failed for lane %d", body.lane)

    # Fire-and-forget: run_in_executor returns immediately so the HTTP response
    # is sent before the sweep finishes. Use get_margining_progress to poll.
    asyncio.get_running_loop().run_in_executor(None, _run_sweep)

    return {"status": "started", "lane": str(body.lane)}


@router.get(
    "/devices/{device_id}/phy/margining/progress",
    response_model=SweepProgress,
)
async def get_margining_progress(
    device_id: str,
    lane: int = Query(0, ge=0, le=15),
) -> SweepProgress:
    """Poll the progress of a running margining sweep."""
    from calypso.core.lane_margining import get_sweep_progress
    return get_sweep_progress(device_id, lane)


@router.get(
    "/devices/{device_id}/phy/margining/result",
    response_model=EyeSweepResult,
)
async def get_margining_result(
    device_id: str,
    lane: int = Query(0, ge=0, le=15),
) -> EyeSweepResult:
    """Get the completed sweep result for a lane."""
    from calypso.core.lane_margining import get_sweep_result
    result = get_sweep_result(device_id, lane)
    if result is None:
        raise HTTPException(status_code=404, detail="No sweep result available for this lane")
    return result


class ResetRequest(BaseModel):
    lane: int = Field(ge=0, le=15)
    port_number: int = Field(0, ge=0, le=143)


@router.post("/devices/{device_id}/phy/margining/reset")
async def reset_margining(
    device_id: str,
    body: ResetRequest,
) -> dict[str, str]:
    """Send GO_TO_NORMAL_SETTINGS to reset a lane after margining."""
    sw = _get_switch(device_id)

    def _reset():
        from calypso.core.lane_margining import LaneMarginingEngine
        engine = LaneMarginingEngine(sw._device_obj, sw._device_key, body.port_number)
        engine.reset_lane(body.lane)

    try:
        await asyncio.to_thread(_reset)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "reset", "lane": str(body.lane)}
