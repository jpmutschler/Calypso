"""Multi-recipe workflow progress monitor."""

from __future__ import annotations

from nicegui import ui

from calypso.ui.theme import COLORS
from calypso.workflows.models import StepStatus
from calypso.workflows.workflow_executor import get_run_progress, get_run_results


_STATUS_COLORS: dict[str, str] = {
    "pass": COLORS.green,
    "fail": COLORS.red,
    "warn": COLORS.yellow,
    "skip": COLORS.text_muted,
    "error": COLORS.red,
    "running": COLORS.cyan,
    "pending": COLORS.text_muted,
}


class WorkflowMonitor:
    """Displays live progress for a multi-step workflow run.

    Creates an overall progress bar, metric cards, and per-step
    expansion panels.  Polls ``get_run_progress`` on a timer.

    Args:
        run_id: The workflow run ID to monitor.
    """

    def __init__(self, run_id: str) -> None:
        self._run_id = run_id
        self._timer: ui.timer | None = None
        self._finished = False

        with (
            ui.card()
            .classes("w-full q-pa-md")
            .style(f"background: {COLORS.bg_card}; border: 1px solid {COLORS.border};")
        ):
            with ui.column().classes("w-full q-gutter-sm"):
                self._title = (
                    ui.label("Running workflow...")
                    .classes("text-subtitle1")
                    .style(f"color: {COLORS.text_primary}; font-weight: 600;")
                )

                # Overall progress
                self._progress = (
                    ui.linear_progress(
                        value=0,
                        show_value=False,
                    )
                    .classes("w-full")
                    .props(f'color="{COLORS.cyan}"')
                )

                self._status_label = ui.label("Preparing...").style(
                    f"color: {COLORS.text_secondary}; font-size: 13px;"
                )
                self._elapsed_label = ui.label("").style(
                    f"color: {COLORS.text_muted}; font-size: 12px;"
                )

                # Metric cards row
                self._metrics_container = ui.row().classes("w-full gap-4 q-mt-sm")

                # Step panels
                self._panels_container = ui.column().classes("w-full q-mt-sm q-gutter-sm")

                # Results summary (shown when complete)
                self._results_container = ui.column().classes("w-full q-mt-md")
                self._results_container.set_visibility(False)

        self._timer = ui.timer(1.0, self._poll_progress)

    def _poll_progress(self) -> None:
        """Fetch current workflow progress and update the UI."""
        if self._finished:
            return

        state = get_run_progress(self._run_id)
        if state is None:
            return

        self._title.set_text(state.recipe_name or "Running workflow...")
        self._progress.set_value(state.percent / 100.0)
        self._status_label.set_text(
            f"{state.status.upper()} - {state.current_step}"
            f" ({state.steps_completed}/{state.steps_total})"
        )
        self._elapsed_label.set_text(f"Elapsed: {state.elapsed_ms / 1000:.1f}s")

        # Rebuild metrics
        self._update_metrics(state)

        # Rebuild step panels
        self._update_panels(state)

        if state.status in ("complete", "cancelled", "error"):
            self._finished = True
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._render_results()

    def _update_metrics(self, state) -> None:
        """Redraw the metric cards row."""
        self._metrics_container.clear()
        with self._metrics_container:
            pass_count = sum(1 for s in state.steps if s.status == StepStatus.PASS)
            fail_count = sum(1 for s in state.steps if s.status == StepStatus.FAIL)
            error_count = sum(1 for s in state.steps if s.status == StepStatus.ERROR)
            running_count = sum(1 for s in state.steps if s.status == StepStatus.RUNNING)

            _metric_card("Completed", str(state.steps_completed), COLORS.cyan)
            _metric_card("Pass", str(pass_count), COLORS.green)
            _metric_card("Fail", str(fail_count), COLORS.red)
            _metric_card("Error", str(error_count), COLORS.red)
            _metric_card("Running", str(running_count), COLORS.cyan)

    def _update_panels(self, state) -> None:
        """Redraw per-step expansion panels."""
        self._panels_container.clear()
        with self._panels_container:
            for step in state.steps:
                step_color = _STATUS_COLORS.get(step.status.value, COLORS.text_muted)
                icon_name = _status_to_icon(step.status)

                with (
                    ui.expansion(
                        text=step.step_name,
                        icon=icon_name,
                    )
                    .classes("w-full")
                    .style(f"background: {COLORS.bg_primary}; border: 1px solid {COLORS.border};")
                ):
                    # Panel header color
                    ui.label(f"{step.status.value.upper()} - {step.message}").style(
                        f"color: {step_color}; font-size: 13px;"
                    )

                    if step.duration_ms > 0:
                        ui.label(f"Duration: {step.duration_ms:.0f}ms").style(
                            f"color: {COLORS.text_muted}; font-size: 12px;"
                        )

                    if step.measured_values:
                        with ui.column().classes("q-mt-xs"):
                            for key, val in step.measured_values.items():
                                ui.label(f"{key}: {val}").classes("mono").style(
                                    f"color: {COLORS.text_secondary}; font-size: 12px;"
                                )

    def _render_results(self) -> None:
        """Show final workflow results after completion."""
        results = get_run_results(self._run_id)
        if results is None:
            return

        self._results_container.set_visibility(True)
        self._results_container.clear()

        with self._results_container:
            ui.separator().style(f"background-color: {COLORS.border};")
            ui.label("Workflow Results").classes("text-subtitle1 q-mt-sm").style(
                f"color: {COLORS.text_primary}; font-weight: 600;"
            )

            for summary in results:
                overall_color = _STATUS_COLORS.get(summary.status.value, COLORS.text_secondary)
                with (
                    ui.card()
                    .classes("w-full q-pa-sm q-mt-xs")
                    .style(f"background: {COLORS.bg_primary}; border: 1px solid {COLORS.border};")
                ):
                    with ui.row().classes("items-center gap-3 w-full"):
                        ui.label(summary.recipe_name).style(
                            f"color: {COLORS.text_primary}; font-weight: 500;"
                        )
                        ui.badge(summary.status.value.upper()).style(
                            f"background: {overall_color}20; color: {overall_color};"
                        )
                        ui.space()
                        ui.label(
                            f"P:{summary.total_pass} F:{summary.total_fail} W:{summary.total_warn}"
                        ).style(f"color: {COLORS.text_secondary}; font-size: 12px;")
                        ui.label(f"{summary.duration_ms / 1000:.1f}s").style(
                            f"color: {COLORS.text_muted}; font-size: 12px;"
                        )

    def cancel(self) -> None:
        """Stop the polling timer."""
        self._finished = True
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None


def _metric_card(label: str, value: str, color: str) -> None:
    """Render a small metric card."""
    with (
        ui.card()
        .classes("q-pa-sm")
        .style(
            f"background: {COLORS.bg_primary}; border: 1px solid {COLORS.border}; min-width: 80px;"
        )
    ):
        with ui.column().classes("items-center"):
            ui.label(value).classes("text-h6").style(f"color: {color}; font-weight: bold;")
            ui.label(label).style(f"color: {COLORS.text_muted}; font-size: 11px;")


def _status_to_icon(status: StepStatus) -> str:
    """Map a step status to a Quasar icon name."""
    return {
        StepStatus.PENDING: "radio_button_unchecked",
        StepStatus.RUNNING: "sync",
        StepStatus.PASS: "check_circle",
        StepStatus.FAIL: "cancel",
        StepStatus.WARN: "warning",
        StepStatus.SKIP: "skip_next",
        StepStatus.ERROR: "error",
    }.get(status, "help_outline")
