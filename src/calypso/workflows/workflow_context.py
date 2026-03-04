"""Mutable runtime context for workflow execution."""

from __future__ import annotations

from calypso.workflows.models import RecipeSummary


class WorkflowExecutionContext:
    """Tracks mutable state during workflow execution.

    Stores results from each completed step so that subsequent
    steps can reference them via expressions and bindings.
    """

    def __init__(self) -> None:
        self._results: dict[str, RecipeSummary] = {}
        self._variables: dict[str, object] = {}
        self._step_index: int = 0

    @property
    def step_index(self) -> int:
        return self._step_index

    @step_index.setter
    def step_index(self, value: int) -> None:
        self._step_index = value

    @property
    def results(self) -> dict[str, RecipeSummary]:
        """All completed step results keyed by step_id."""
        return dict(self._results)

    @property
    def variables(self) -> dict[str, object]:
        """User-defined variables set during execution."""
        return dict(self._variables)

    def store_result(self, step_id: str, summary: RecipeSummary) -> None:
        """Store a recipe execution result."""
        self._results[step_id] = summary

    def get_result(self, step_id: str) -> RecipeSummary | None:
        """Get result for a specific step."""
        return self._results.get(step_id)

    def set_variable(self, name: str, value: object) -> None:
        """Set a context variable."""
        self._variables[name] = value

    def get_variable(self, name: str, default: object = None) -> object:
        """Get a context variable."""
        return self._variables.get(name, default)

    def resolve_binding(self, expression: str) -> object | None:
        """Resolve a binding expression like ``step_1.status`` or ``step_1.total_pass``.

        Supports:
        - ``{step_id}.status`` -> StepStatus value
        - ``{step_id}.total_pass`` -> int
        - ``{step_id}.total_fail`` -> int
        - ``{step_id}.duration_ms`` -> float
        - ``{step_id}.pass_rate`` -> float
        - ``{step_id}.parameters.{name}`` -> parameter value
        - ``{step_id}.steps[{index}].measured_values.{key}`` -> measured value
        - ``var.{name}`` -> context variable
        """
        if not expression:
            return None

        parts = expression.split(".")
        if not parts:
            return None

        if parts[0] == "var" and len(parts) >= 2:
            return self.get_variable(parts[1])

        step_id = parts[0]
        result = self._results.get(step_id)
        if result is None:
            return None

        if len(parts) < 2:
            return result

        attr = parts[1]

        if attr == "status":
            return result.status.value
        elif attr == "total_pass":
            return result.total_pass
        elif attr == "total_fail":
            return result.total_fail
        elif attr == "total_warn":
            return result.total_warn
        elif attr == "total_skip":
            return result.total_skip
        elif attr == "total_error":
            return result.total_error
        elif attr == "duration_ms":
            return result.duration_ms
        elif attr == "pass_rate":
            return result.pass_rate
        elif attr == "parameters" and len(parts) >= 3:
            return result.parameters.get(parts[2])
        elif attr == "steps" and len(parts) >= 3:
            # steps[0].measured_values.key
            idx_str = parts[2].strip("[]")
            try:
                idx = int(idx_str)
            except ValueError:
                return None
            if idx >= len(result.steps):
                return None
            step = result.steps[idx]
            if len(parts) >= 5 and parts[3] == "measured_values":
                return step.measured_values.get(parts[4])
            return step

        return None
