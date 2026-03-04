"""Recipe and workflow execution API endpoints."""

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(tags=["recipes"])


def _get_switch(device_id: str):
    from calypso.api.app import get_device_registry

    registry = get_device_registry()
    sw = registry.get(device_id)
    if sw is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return sw


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class RunRecipeRequest(BaseModel):
    recipe_id: str = Field(..., description="ID of the recipe to execute")
    parameters: dict = Field(default_factory=dict, description="Override parameters")


class RunRecipeResponse(BaseModel):
    status: str
    device_id: str


class RunWorkflowResponse(BaseModel):
    status: str
    run_id: str


class SaveWorkflowRequest(BaseModel):
    workflow: dict = Field(..., description="WorkflowDefinition JSON payload")


# ---------------------------------------------------------------------------
# Recipe endpoints
# ---------------------------------------------------------------------------


@router.get("/devices/{device_id}/recipes")
async def list_recipes(device_id: str) -> list[dict]:
    """List all available recipes with metadata."""
    from calypso.workflows import get_all_recipes

    _get_switch(device_id)  # validate device exists

    recipes = get_all_recipes()
    return [
        {
            "recipe_id": r.recipe_id,
            "name": r.name,
            "description": r.description,
            "category": r.category,
            "estimated_duration_s": r.estimated_duration_s,
            "parameters": r.parameters,
        }
        for r in recipes
    ]


@router.post("/devices/{device_id}/recipes/run")
async def start_recipe(
    device_id: str,
    body: RunRecipeRequest,
) -> RunRecipeResponse:
    """Start a recipe execution in a background thread."""
    from calypso.workflows import get_recipe
    from calypso.workflows.workflow_executor import get_recipe_progress, run_single_recipe

    sw = _get_switch(device_id)

    recipe = get_recipe(body.recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail=f"Recipe '{body.recipe_id}' not found")

    # Check if already running
    progress = get_recipe_progress(device_id)
    if progress is not None and progress.get("status") == "running":
        raise HTTPException(status_code=409, detail="A recipe is already running on this device")

    def _run():
        try:
            run_single_recipe(
                sw._device_obj,
                sw._device_key,
                device_id,
                body.recipe_id,
                body.parameters,
            )
        except Exception:
            logger.exception("Recipe execution failed for %s on %s", body.recipe_id, device_id)

    asyncio.get_running_loop().run_in_executor(None, _run)

    return RunRecipeResponse(status="started", device_id=device_id)


@router.get("/devices/{device_id}/recipes/progress")
async def get_recipe_progress_endpoint(device_id: str) -> dict | None:
    """Poll recipe execution progress."""
    from calypso.workflows.workflow_executor import get_recipe_progress

    _get_switch(device_id)
    return get_recipe_progress(device_id)


@router.get("/devices/{device_id}/recipes/result")
async def get_recipe_result_endpoint(device_id: str) -> dict:
    """Get the completed recipe result."""
    from calypso.workflows.workflow_executor import get_recipe_result

    _get_switch(device_id)
    result = get_recipe_result(device_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No recipe result available")
    return result


@router.post("/devices/{device_id}/recipes/cancel")
async def cancel_recipe_endpoint(device_id: str) -> dict[str, str]:
    """Request cancellation of a running recipe."""
    from calypso.workflows.workflow_executor import cancel_recipe

    _get_switch(device_id)
    cancel_recipe(device_id)
    return {"status": "cancelling"}


# ---------------------------------------------------------------------------
# Workflow execution endpoints
# ---------------------------------------------------------------------------


@router.post("/devices/{device_id}/workflows/run")
async def start_workflow(
    device_id: str,
    body: dict,
) -> RunWorkflowResponse:
    """Start a workflow execution in a background thread."""
    from calypso.workflows.workflow_executor import WorkflowExecutor
    from calypso.workflows.workflow_models import WorkflowDefinition

    sw = _get_switch(device_id)

    try:
        workflow = WorkflowDefinition(**body)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid workflow definition: {exc}") from exc

    run_id = str(uuid.uuid4())
    executor = WorkflowExecutor(sw._device_obj, sw._device_key, device_id)

    def _run():
        try:
            executor.run(workflow, run_id=run_id)
        except Exception:
            logger.exception("Workflow execution failed for run %s on %s", run_id, device_id)

    asyncio.get_running_loop().run_in_executor(None, _run)

    return RunWorkflowResponse(status="started", run_id=run_id)


@router.get("/devices/{device_id}/workflows/progress/{run_id}")
async def get_workflow_progress_endpoint(device_id: str, run_id: str) -> dict | None:
    """Poll workflow execution progress."""
    from calypso.workflows.workflow_executor import get_run_progress

    _get_switch(device_id)
    return get_run_progress(run_id)


@router.get("/devices/{device_id}/workflows/result/{run_id}")
async def get_workflow_result_endpoint(device_id: str, run_id: str) -> dict | None:
    """Get the completed workflow result."""
    from calypso.workflows.workflow_executor import get_run_results

    _get_switch(device_id)
    result = get_run_results(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No workflow result available")
    return result


@router.post("/devices/{device_id}/workflows/cancel/{run_id}")
async def cancel_workflow_endpoint(device_id: str, run_id: str) -> dict[str, str]:
    """Request cancellation of a running workflow."""
    from calypso.workflows.workflow_executor import cancel_run

    _get_switch(device_id)
    cancel_run(run_id)
    return {"status": "cancelling"}


@router.get("/devices/{device_id}/workflows/report/{run_id}")
async def download_workflow_report(device_id: str, run_id: str) -> HTMLResponse:
    """Generate and return an HTML workflow report."""
    from calypso.workflows.workflow_executor import get_run_results
    from calypso.workflows.workflow_report import generate_report

    _get_switch(device_id)
    result = get_run_results(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No workflow result available")

    html_content = await asyncio.to_thread(generate_report, result)
    return HTMLResponse(
        content=html_content,
        headers={
            "Content-Disposition": (f'attachment; filename="workflow-report-{run_id}.html"'),
        },
    )


# ---------------------------------------------------------------------------
# Saved workflow CRUD (not device-scoped)
# ---------------------------------------------------------------------------


@router.get("/workflows")
async def list_saved_workflows() -> list[dict]:
    """List all saved workflow definitions."""
    from calypso.workflows.workflow_storage import list_workflows

    return list_workflows()


@router.get("/workflows/{workflow_id}")
async def get_saved_workflow(workflow_id: str) -> dict:
    """Load a saved workflow definition by ID."""
    from calypso.workflows.workflow_storage import load_workflow

    workflow = load_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@router.post("/workflows")
async def save_workflow_endpoint(body: SaveWorkflowRequest) -> dict[str, str]:
    """Save a workflow definition."""
    from calypso.workflows.workflow_storage import save_workflow

    workflow_id = save_workflow(body.workflow)
    return {"status": "saved", "workflow_id": workflow_id}


@router.delete("/workflows/{workflow_id}")
async def delete_workflow_endpoint(workflow_id: str) -> dict[str, str]:
    """Delete a saved workflow definition."""
    from calypso.workflows.workflow_storage import delete_workflow

    delete_workflow(workflow_id)
    return {"status": "deleted"}
