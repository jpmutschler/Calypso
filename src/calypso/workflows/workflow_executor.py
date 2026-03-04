"""Workflow executor with module-level threading state.

Matches the compliance/engine.py threading pattern: module-level
_lock, _active_runs, _completed_runs, _cancel_flags.
"""

from __future__ import annotations

import threading
import time
import uuid

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.utils.logging import get_logger
from calypso.workflows.models import RecipeSummary, StepStatus
from calypso.workflows.monitor_state import MonitorState
from calypso.workflows.workflow_context import WorkflowExecutionContext
from calypso.workflows.workflow_expressions import evaluate_condition
from calypso.workflows.workflow_models import OnFailAction, WorkflowDefinition

logger = get_logger(__name__)

# Module-level state keyed by run_id
_lock = threading.Lock()
_active_runs: dict[str, MonitorState] = {}
_completed_runs: dict[str, list[RecipeSummary]] = {}
_cancel_flags: dict[str, bool] = {}
_MAX_COMPLETED = 100  # evict oldest when exceeded


def get_run_progress(run_id: str) -> MonitorState | None:
    """Get live progress for a workflow run."""
    with _lock:
        return _active_runs.get(run_id)


def get_run_results(run_id: str) -> list[RecipeSummary] | None:
    """Get completed workflow results."""
    with _lock:
        return _completed_runs.get(run_id)


def cancel_run(run_id: str) -> None:
    """Request cancellation of a workflow run."""
    with _lock:
        _cancel_flags[run_id] = True


def _is_cancelled(run_id: str) -> bool:
    with _lock:
        return _cancel_flags.get(run_id, False)


# Also support single-recipe runs keyed by device_id
_recipe_lock = threading.Lock()
_recipe_active: dict[str, MonitorState] = {}
_recipe_completed: dict[str, RecipeSummary] = {}
_recipe_cancel: dict[str, bool] = {}


def get_recipe_progress(device_id: str) -> MonitorState | None:
    with _recipe_lock:
        return _recipe_active.get(device_id)


def get_recipe_result(device_id: str) -> RecipeSummary | None:
    with _recipe_lock:
        return _recipe_completed.get(device_id)


def cancel_recipe(device_id: str) -> None:
    with _recipe_lock:
        _recipe_cancel[device_id] = True


def run_single_recipe(
    recipe_id: str,
    dev: PLX_DEVICE_OBJECT,
    dev_key: PLX_DEVICE_KEY,
    device_id: str,
    **kwargs: object,
) -> RecipeSummary:
    """Execute a single recipe with progress tracking.

    Thread-safe: updates _recipe_active progress, stores result
    in _recipe_completed, and honours _recipe_cancel.
    """
    from calypso.workflows import get_recipe

    recipe = get_recipe(recipe_id)
    if recipe is None:
        raise ValueError(f"Unknown recipe: {recipe_id}")

    cancel: dict[str, bool] = {"cancelled": False}

    monitor = MonitorState(
        recipe_id=recipe_id,
        recipe_name=recipe.name,
        status="running",
        steps_total=len(recipe.parameters) + 5,  # rough estimate
    )

    with _recipe_lock:
        _recipe_cancel[device_id] = False
        _recipe_active[device_id] = monitor

    start_time = time.monotonic()

    try:
        gen = recipe.run(dev, dev_key, cancel, **kwargs)
        steps_collected: list = []

        while True:
            try:
                result = next(gen)
            except StopIteration as e:
                # Generator returned — capture RecipeSummary from return value
                if isinstance(e.value, RecipeSummary):
                    summary = e.value
                else:
                    summary = recipe._make_summary(steps_collected, start_time, kwargs, device_id)
                break

            # Check external cancel
            with _recipe_lock:
                if _recipe_cancel.get(device_id, False):
                    cancel["cancelled"] = True

            monitor.update_from_result(result)
            monitor.elapsed_ms = round((time.monotonic() - start_time) * 1000, 2)

            with _recipe_lock:
                _recipe_active[device_id] = monitor.model_copy()

            if result.status != StepStatus.RUNNING:
                steps_collected.append(result)

    except Exception as exc:
        logger.error("recipe_execution_failed", recipe=recipe_id, error=str(exc))
        summary = RecipeSummary(
            recipe_id=recipe_id,
            recipe_name=recipe.name,
            category=recipe.category,
            status=StepStatus.ERROR,
            duration_ms=round((time.monotonic() - start_time) * 1000, 2),
        )

    monitor.finalize(summary)

    with _recipe_lock:
        _recipe_completed[device_id] = summary
        _recipe_active[device_id] = monitor.model_copy()
        _recipe_cancel.pop(device_id, None)
        # Evict oldest completed entries to bound memory
        if len(_recipe_completed) > _MAX_COMPLETED:
            oldest = next(iter(_recipe_completed))
            _recipe_completed.pop(oldest, None)
            _recipe_active.pop(oldest, None)

    return summary


class WorkflowExecutor:
    """Executes a workflow definition step by step."""

    def __init__(
        self,
        dev: PLX_DEVICE_OBJECT,
        dev_key: PLX_DEVICE_KEY,
        device_id: str,
    ) -> None:
        self._dev = dev
        self._key = dev_key
        self._device_id = device_id

    def run(self, workflow: WorkflowDefinition) -> list[RecipeSummary]:
        """Execute all steps in a workflow.

        Thread-safe: updates _active_runs, stores results in _completed_runs.
        """
        from calypso.workflows import get_recipe

        run_id = str(uuid.uuid4())[:8]
        ctx = WorkflowExecutionContext()
        start_time = time.monotonic()
        summaries: list[RecipeSummary] = []

        enabled_steps = [s for s in workflow.steps if s.enabled]

        monitor = MonitorState(
            recipe_id=workflow.workflow_id,
            recipe_name=workflow.name,
            status="running",
            steps_total=len(enabled_steps),
        )

        with _lock:
            _cancel_flags[run_id] = False
            _active_runs[run_id] = monitor.model_copy()

        cancel: dict[str, bool] = {"cancelled": False}

        try:
            for step_idx, step in enumerate(enabled_steps):
                if _is_cancelled(run_id):
                    cancel["cancelled"] = True
                    break

                ctx.step_index = step_idx
                step_id = step.step_id or f"step_{step_idx}"

                # Evaluate condition
                if step.condition.expression:
                    if not evaluate_condition(step.condition.expression, ctx):
                        logger.info(
                            "workflow_step_skipped",
                            step=step_id,
                            condition=step.condition.expression,
                        )
                        continue

                recipe = get_recipe(step.recipe_id)
                if recipe is None:
                    logger.error("workflow_recipe_not_found", recipe=step.recipe_id)
                    continue

                # Resolve parameter bindings
                params = dict(step.parameters)
                for param_name, binding_expr in step.bindings.items():
                    resolved = ctx.resolve_binding(binding_expr)
                    if resolved is not None:
                        params[param_name] = resolved

                # Execute with loop support
                for loop_iter in range(step.loop.count):
                    if _is_cancelled(run_id):
                        cancel["cancelled"] = True
                        break

                    monitor.current_step = f"{step.label or recipe.name}" + (
                        f" (iter {loop_iter + 1}/{step.loop.count})" if step.loop.count > 1 else ""
                    )

                    with _lock:
                        _active_runs[run_id] = monitor.model_copy()

                    # Run the recipe
                    loop_start = time.monotonic()
                    try:
                        gen = recipe.run(self._dev, self._key, cancel, **params)
                        steps_collected = []

                        while True:
                            try:
                                result = next(gen)
                            except StopIteration as e:
                                if isinstance(e.value, RecipeSummary):
                                    summary = e.value
                                else:
                                    summary = recipe._make_summary(
                                        steps_collected, loop_start, params, self._device_id
                                    )
                                break

                            if _is_cancelled(run_id):
                                cancel["cancelled"] = True

                            monitor.update_from_result(result)
                            monitor.elapsed_ms = round((time.monotonic() - start_time) * 1000, 2)
                            with _lock:
                                _active_runs[run_id] = monitor.model_copy()

                            if result.status != StepStatus.RUNNING:
                                steps_collected.append(result)
                    except Exception as exc:
                        logger.error(
                            "workflow_step_failed",
                            step=step_id,
                            error=str(exc),
                        )
                        summary = RecipeSummary(
                            recipe_id=recipe.recipe_id,
                            recipe_name=recipe.name,
                            category=recipe.category,
                            status=StepStatus.ERROR,
                            duration_ms=round((time.monotonic() - loop_start) * 1000, 2),
                            device_id=self._device_id,
                        )

                    summaries.append(summary)
                    ctx.store_result(step_id, summary)

                    # Handle failure
                    if summary.status in (StepStatus.FAIL, StepStatus.ERROR):
                        if step.loop.stop_on_fail:
                            break
                        if step.on_fail == OnFailAction.STOP:
                            with _lock:
                                _active_runs[run_id] = monitor.model_copy()
                            break
                        elif step.on_fail == OnFailAction.SKIP_REMAINING:
                            break

                    # Loop delay
                    if (
                        step.loop.count > 1
                        and loop_iter < step.loop.count - 1
                        and step.loop.delay_s > 0
                    ):
                        time.sleep(step.loop.delay_s)

                # Check if we should stop the whole workflow
                if (
                    summaries
                    and summaries[-1].status in (StepStatus.FAIL, StepStatus.ERROR)
                    and step.on_fail == OnFailAction.STOP
                ):
                    break

                monitor.steps_completed = step_idx + 1
                if monitor.steps_total > 0:
                    monitor.percent = round(monitor.steps_completed / monitor.steps_total * 100, 1)

        except Exception as exc:
            logger.error("workflow_execution_failed", error=str(exc))

        monitor.status = "cancelled" if _is_cancelled(run_id) else "complete"
        monitor.elapsed_ms = round((time.monotonic() - start_time) * 1000, 2)
        monitor.percent = 100.0

        with _lock:
            _completed_runs[run_id] = summaries
            _active_runs[run_id] = monitor.model_copy()
            _cancel_flags.pop(run_id, None)
            # Evict oldest completed entries to bound memory
            if len(_completed_runs) > _MAX_COMPLETED:
                oldest = next(iter(_completed_runs))
                _completed_runs.pop(oldest, None)
                _active_runs.pop(oldest, None)

        return summaries
