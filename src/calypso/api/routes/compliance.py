"""PCIe compliance testing API endpoints."""

from __future__ import annotations

import asyncio
import datetime
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from calypso.compliance.models import (
    DeviceMetadata,
    PortConfig,
    TestRunConfig,
    TestRunProgress,
    TestSuiteId,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["compliance"])


def _get_switch(device_id: str):
    from calypso.api.app import get_device_registry
    registry = get_device_registry()
    sw = registry.get(device_id)
    if sw is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return sw


class StartComplianceRequest(BaseModel):
    suites: list[TestSuiteId] = Field(default_factory=lambda: list(TestSuiteId))
    ports: list[PortConfig] = Field(default_factory=lambda: [PortConfig()])
    ber_duration_s: float = Field(10.0, ge=1.0, le=300.0)
    idle_wait_s: float = Field(5.0, ge=1.0, le=60.0)
    speed_settle_s: float = Field(2.0, ge=0.5, le=10.0)


@router.post("/devices/{device_id}/compliance/start")
async def start_compliance_run(
    device_id: str,
    body: StartComplianceRequest,
) -> dict[str, str]:
    """Start a background compliance test run."""
    from calypso.compliance.engine import ComplianceRunner, get_run_progress

    sw = _get_switch(device_id)

    # Check if already running
    progress = get_run_progress(device_id)
    if progress.status == "running":
        raise HTTPException(status_code=409, detail="Compliance run already in progress")

    config = TestRunConfig(
        suites=body.suites,
        ports=body.ports,
        ber_duration_s=body.ber_duration_s,
        idle_wait_s=body.idle_wait_s,
        speed_settle_s=body.speed_settle_s,
    )

    key = sw._device_key
    metadata = DeviceMetadata(
        device_id=device_id,
        vendor_id=f"0x{key.VendorId:04X}",
        device_id_hex=f"0x{key.DeviceId:04X}",
        chip_revision=f"0x{key.Revision:02X}",
        description=f"Port {key.PlxPort}",
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    )

    runner = ComplianceRunner(sw._device_obj, sw._device_key, device_id)

    def _run():
        try:
            runner.run(config, metadata)
        except Exception:
            logger.exception("Compliance run failed for %s", device_id)

    asyncio.get_running_loop().run_in_executor(None, _run)

    return {"status": "started"}


@router.get(
    "/devices/{device_id}/compliance/progress",
    response_model=TestRunProgress,
)
async def get_compliance_progress(device_id: str) -> TestRunProgress:
    """Poll compliance test run progress."""
    from calypso.compliance.engine import get_run_progress
    return get_run_progress(device_id)


@router.get("/devices/{device_id}/compliance/result")
async def get_compliance_result(device_id: str) -> dict:
    """Get the completed compliance test run result."""
    from calypso.compliance.engine import get_run_result
    result = get_run_result(device_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No compliance result available")
    return result.model_dump()


@router.post("/devices/{device_id}/compliance/cancel")
async def cancel_compliance_run(device_id: str) -> dict[str, str]:
    """Request cancellation of a running compliance test."""
    from calypso.compliance.engine import cancel_run
    cancel_run(device_id)
    return {"status": "cancelling"}


@router.get("/devices/{device_id}/compliance/report")
async def download_compliance_report(device_id: str) -> HTMLResponse:
    """Generate and return an HTML compliance report."""
    from calypso.compliance.engine import get_run_result
    from calypso.compliance.report import generate_report

    result = get_run_result(device_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No compliance result available")

    html_content = generate_report(result)
    return HTMLResponse(
        content=html_content,
        headers={
            "Content-Disposition": f'attachment; filename="compliance-report-{device_id}.html"',
        },
    )
