"""Models for multi-recipe workflows."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class OnFailAction(StrEnum):
    """What to do when a workflow step fails."""

    STOP = "stop"
    CONTINUE = "continue"
    SKIP_REMAINING = "skip_remaining"


class LoopConfig(BaseModel):
    """Loop configuration for repeating a step."""

    count: int = Field(1, ge=1, le=100)
    delay_s: float = Field(0.0, ge=0.0, le=300.0)
    stop_on_fail: bool = True


class StepCondition(BaseModel):
    """Conditional execution expression for a workflow step.

    The ``expression`` is evaluated by the expression parser against
    the workflow context's result store.
    """

    expression: str = ""
    description: str = ""


class WorkflowStep(BaseModel):
    """A single step in a workflow definition."""

    step_id: str = ""
    recipe_id: str
    label: str = ""
    parameters: dict[str, object] = Field(default_factory=dict)
    on_fail: OnFailAction = OnFailAction.STOP
    loop: LoopConfig = Field(default_factory=LoopConfig)
    condition: StepCondition = Field(default_factory=StepCondition)
    bindings: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class WorkflowDefinition(BaseModel):
    """A saved workflow comprising an ordered list of recipe steps."""

    workflow_id: str = ""
    name: str = ""
    description: str = ""
    steps: list[WorkflowStep] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    tags: list[str] = Field(default_factory=list)

    @property
    def recipe_count(self) -> int:
        return len([s for s in self.steps if s.enabled])


class WorkflowSummary(BaseModel):
    """Summary of a workflow (for listing without full step details)."""

    workflow_id: str = ""
    name: str = ""
    description: str = ""
    recipe_count: int = 0
    tags: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
