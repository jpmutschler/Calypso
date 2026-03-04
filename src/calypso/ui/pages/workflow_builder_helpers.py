"""Pure helpers for converting between UI step dicts and workflow models."""

from __future__ import annotations

from calypso.workflows.workflow_models import (
    LoopConfig,
    OnFailAction,
    StepCondition,
    WorkflowStep,
)


def step_data_to_model(step_data: dict) -> WorkflowStep:
    """Convert a UI step data dict to a WorkflowStep model.

    Args:
        step_data: Dict with keys produced by the step editor UI.

    Returns:
        A validated WorkflowStep instance.
    """
    return WorkflowStep(
        step_id=str(step_data.get("step_id", "")),
        recipe_id=str(step_data.get("recipe_id", "")),
        label=str(step_data.get("label", "")),
        parameters=dict(step_data.get("parameters", {})),
        on_fail=OnFailAction(step_data.get("on_fail", OnFailAction.STOP.value)),
        loop=LoopConfig(
            count=int(step_data.get("loop_count", 1)),
            delay_s=float(step_data.get("loop_delay_s", 0.0)),
            stop_on_fail=bool(step_data.get("loop_stop_on_fail", True)),
        ),
        condition=StepCondition(
            expression=str(step_data.get("condition_expression", "")),
        ),
        bindings=dict(step_data.get("bindings", {})),
        enabled=bool(step_data.get("enabled", True)),
    )


def model_to_step_data(step: WorkflowStep) -> dict:
    """Convert a WorkflowStep model to a UI-friendly dict.

    Args:
        step: The workflow step model.

    Returns:
        A dict suitable for the step editor component.
    """
    return {
        "step_id": step.step_id,
        "recipe_id": step.recipe_id,
        "label": step.label,
        "parameters": dict(step.parameters),
        "on_fail": step.on_fail.value,
        "loop_count": step.loop.count,
        "loop_delay_s": step.loop.delay_s,
        "loop_stop_on_fail": step.loop.stop_on_fail,
        "condition_expression": step.condition.expression,
        "bindings": dict(step.bindings),
        "enabled": step.enabled,
    }
