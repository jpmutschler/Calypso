"""JSON persistence for workflow definitions.

Stores workflows as individual JSON files in ``~/.calypso/workflows/``.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from calypso.utils.logging import get_logger
from calypso.workflows.workflow_models import WorkflowDefinition, WorkflowSummary

logger = get_logger(__name__)

_STORAGE_DIR = Path.home() / ".calypso" / "workflows"
_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _ensure_dir() -> Path:
    _STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    return _STORAGE_DIR


def _validate_workflow_id(workflow_id: str) -> None:
    """Validate that a workflow ID is safe for filesystem use."""
    if not _SAFE_ID_RE.match(workflow_id):
        raise ValueError(f"Invalid workflow_id: {workflow_id!r}")


def _workflow_path(workflow_id: str) -> Path:
    _validate_workflow_id(workflow_id)
    path = (_ensure_dir() / f"{workflow_id}.json").resolve()
    if not path.is_relative_to(_STORAGE_DIR.resolve()):
        raise ValueError(f"Path traversal detected: {workflow_id!r}")
    return path


def save_workflow(workflow: WorkflowDefinition) -> WorkflowDefinition:
    """Save a workflow definition to disk.

    If ``workflow_id`` is empty, a new ID is generated.
    Updates the ``updated_at`` timestamp.
    """
    now = datetime.now(tz=timezone.utc).isoformat()

    if not workflow.workflow_id:
        workflow = workflow.model_copy(
            update={
                "workflow_id": str(uuid.uuid4())[:8],
                "created_at": now,
            }
        )

    workflow = workflow.model_copy(update={"updated_at": now})

    path = _workflow_path(workflow.workflow_id)
    path.write_text(json.dumps(workflow.model_dump(), indent=2, default=str))

    return workflow


def load_workflow(workflow_id: str) -> WorkflowDefinition | None:
    """Load a workflow definition by ID."""
    path = _workflow_path(workflow_id)
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return WorkflowDefinition.model_validate(data)


def list_workflows() -> list[WorkflowSummary]:
    """List all saved workflows as summaries."""
    storage = _ensure_dir()
    summaries: list[WorkflowSummary] = []

    for path in sorted(storage.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            wf = WorkflowDefinition.model_validate(data)
            summaries.append(
                WorkflowSummary(
                    workflow_id=wf.workflow_id,
                    name=wf.name,
                    description=wf.description,
                    recipe_count=wf.recipe_count,
                    tags=wf.tags,
                    created_at=wf.created_at,
                    updated_at=wf.updated_at,
                )
            )
        except Exception:
            logger.warning("workflow_load_failed", path=str(path))
            continue

    return summaries


def delete_workflow(workflow_id: str) -> bool:
    """Delete a workflow definition."""
    path = _workflow_path(workflow_id)
    if path.exists():
        path.unlink()
        return True
    return False
