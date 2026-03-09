"""Live monitoring state for recipe/workflow execution in the UI."""

from __future__ import annotations

from pydantic import BaseModel, Field

from calypso.workflows.models import RecipeResult, RecipeSummary, StepCriticality, StepStatus


class MonitorStepState(BaseModel):
    """State of a single step visible in the monitor UI."""

    step_name: str = ""
    status: StepStatus = StepStatus.PENDING
    message: str = ""
    duration_ms: float = 0.0
    measured_values: dict[str, object] = Field(default_factory=dict)
    port_number: int | None = None
    lane: int | None = None
    criticality: StepCriticality = StepCriticality.INFO
    step_index: int = 0


class MonitorState(BaseModel):
    """Aggregated monitor state for a recipe or workflow run.

    Updated by the executor and read by UI polling.
    """

    recipe_id: str = ""
    recipe_name: str = ""
    status: str = "idle"  # idle, running, complete, cancelled, error
    steps: list[MonitorStepState] = Field(default_factory=list)
    current_step: str = ""
    steps_completed: int = 0
    steps_total: int = 0
    percent: float = 0.0
    elapsed_ms: float = 0.0
    error: str | None = None
    summary: RecipeSummary | None = None

    def update_from_result(self, result: RecipeResult, *, step_index: int = 0) -> None:
        """Update state from a yielded recipe result."""
        if result.status == StepStatus.RUNNING:
            self.current_step = result.step_name
            # Add or update step entry matched by step_index
            found = False
            for step in self.steps:
                if step.step_index == step_index:
                    step.status = StepStatus.RUNNING
                    step.message = result.message
                    step.port_number = result.port_number
                    step.lane = result.lane
                    step.criticality = result.criticality
                    found = True
                    break
            if not found:
                self.steps.append(
                    MonitorStepState(
                        step_name=result.step_name,
                        status=StepStatus.RUNNING,
                        message=result.message,
                        port_number=result.port_number,
                        lane=result.lane,
                        criticality=result.criticality,
                        step_index=step_index,
                    )
                )
        else:
            # Completed step matched by step_index
            for step in self.steps:
                if step.step_index == step_index:
                    step.status = result.status
                    step.message = result.message
                    step.duration_ms = result.duration_ms
                    step.measured_values = result.measured_values
                    step.port_number = result.port_number
                    step.lane = result.lane
                    step.criticality = result.criticality
                    break
            else:
                self.steps.append(
                    MonitorStepState(
                        step_name=result.step_name,
                        status=result.status,
                        message=result.message,
                        duration_ms=result.duration_ms,
                        measured_values=result.measured_values,
                        port_number=result.port_number,
                        lane=result.lane,
                        criticality=result.criticality,
                        step_index=step_index,
                    )
                )
            self.steps_completed = sum(
                1 for s in self.steps if s.status not in (StepStatus.PENDING, StepStatus.RUNNING)
            )

        if self.steps_total > 0:
            self.percent = round(self.steps_completed / self.steps_total * 100, 1)

    def finalize(self, summary: RecipeSummary) -> None:
        """Mark the run as complete with final summary."""
        self.summary = summary
        self.status = "complete"
        self.percent = 100.0
        self.steps_completed = self.steps_total
