"""Live step-by-step progress display for a running recipe."""

from __future__ import annotations

from nicegui import ui

from calypso.ui.components.monitor_common import (
    count_step_statuses,
    download_action_bar,
    format_elapsed,
    measured_values_table,
    metric_card,
    progress_text,
    status_color,
    status_icon,
    summary_chip,
)
from calypso.ui.theme import COLORS
from calypso.workflows.models import StepStatus
from calypso.workflows.monitor_state import MonitorState
from calypso.workflows.workflow_executor import get_recipe_progress


class RecipeStepper:
    """Displays live progress for a single recipe run.

    Creates UI elements for title, progress bar, per-step status list with
    measured values, metric cards, and download actions on completion.

    Args:
        device_id: The device ID whose recipe run to monitor.
    """

    def __init__(self, device_id: str) -> None:
        self._device_id = device_id
        self._timer: ui.timer | None = None
        self._finished = False
        self._notified = False

        with (
            ui.card()
            .classes("w-full q-pa-md")
            .style(f"background: {COLORS.bg_card}; border: 1px solid {COLORS.border};")
        ):
            with ui.column().classes("w-full q-gutter-sm"):
                # Header row with title and cancel button
                with ui.row().classes("w-full items-center justify-between"):
                    self._title = (
                        ui.label("Running recipe...")
                        .classes("text-subtitle1")
                        .style(f"color: {COLORS.text_primary}; font-weight: 600;")
                    )
                    self._cancel_btn = (
                        ui.button(icon="stop", on_click=self._request_cancel)
                        .props("flat round size=sm")
                        .style(f"color: {COLORS.red};")
                        .tooltip("Cancel recipe")
                    )

                self._progress = (
                    ui.linear_progress(value=0, show_value=False)
                    .classes("w-full")
                    .props(f'color="{COLORS.cyan}" indeterminate')
                )

                self._status_label = ui.label("Preparing...").style(
                    f"color: {COLORS.text_secondary}; font-size: 13px;"
                )
                self._elapsed_label = ui.label("").style(
                    f"color: {COLORS.text_muted}; font-size: 12px;"
                )

                # Live metric cards (shown during execution)
                self._metrics_container = ui.row().classes("w-full gap-4 q-mt-sm")

                # Step list
                self._steps_container = ui.column().classes("w-full q-mt-sm")

                # Summary section (shown after completion)
                self._summary_container = ui.column().classes("w-full q-mt-md")
                self._summary_container.set_visibility(False)

        self._timer = ui.timer(1.0, self._poll_progress)

    def _poll_progress(self) -> None:
        """Fetch current progress and update the UI elements."""
        if self._finished:
            return

        state = get_recipe_progress(self._device_id)
        if state is None:
            return

        self._title.set_text(state.recipe_name or "Running recipe...")
        self._status_label.set_text(progress_text(state))
        self._elapsed_label.set_text(f"Elapsed: {format_elapsed(state.elapsed_ms)}")

        # Switch from indeterminate to determinate once we have step data
        if state.steps_total > 0:
            self._progress.props(remove="indeterminate")
            self._progress.set_value(state.percent / 100.0)

        # Update live metrics
        self._update_metrics(state)

        # Rebuild step list
        self._update_steps(state)

        # Check for completion
        if state.status in ("complete", "cancelled", "error"):
            self._finished = True
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._cancel_btn.set_visibility(False)
            self._render_summary(state)

            if not self._notified:
                self._notified = True
                status_text = (
                    "completed" if state.status == "complete" else state.status
                )
                notify_type = (
                    "positive" if state.status == "complete" else "negative"
                )
                ui.notify(
                    f"Recipe '{state.recipe_name}' {status_text}",
                    type=notify_type,
                    position="top-right",
                    timeout=5000,
                )

    def _update_metrics(self, state: MonitorState) -> None:
        """Redraw live metric cards."""
        counts = count_step_statuses(state.steps)

        self._metrics_container.clear()
        with self._metrics_container:
            metric_card(
                "Progress",
                f"{state.steps_completed}/{state.steps_total}",
                COLORS.cyan,
            )
            metric_card("Pass", str(counts.get(StepStatus.PASS, 0)), COLORS.green)
            metric_card("Fail", str(counts.get(StepStatus.FAIL, 0)), COLORS.red)
            metric_card("Warn", str(counts.get(StepStatus.WARN, 0)), COLORS.yellow)
            running = counts.get(StepStatus.RUNNING, 0)
            if running > 0:
                metric_card("Running", str(running), COLORS.cyan)

    def _update_steps(self, state: MonitorState) -> None:
        """Redraw the step list with measured values."""
        self._steps_container.clear()
        with self._steps_container:
            for step in state.steps:
                icon_name, icon_color = status_icon(step.status)
                with ui.column().classes("w-full q-py-xs"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon(icon_name).style(
                            f"color: {icon_color}; font-size: 1.1rem;"
                        )
                        ui.label(step.step_name).style(
                            f"color: {COLORS.text_primary}; font-size: 13px;"
                        )
                        if step.duration_ms > 0:
                            ui.label(f"{step.duration_ms:.0f}ms").style(
                                f"color: {COLORS.text_muted}; font-size: 11px;"
                            )
                    if step.message:
                        ui.label(step.message).style(
                            f"color: {COLORS.text_secondary}; font-size: 12px;"
                            " padding-left: 28px;"
                        )
                    if step.measured_values:
                        with ui.element("div").style("padding-left: 28px;"):
                            measured_values_table(step.measured_values)

    def _render_summary(self, state: MonitorState) -> None:
        """Render the final summary after recipe completion."""
        self._summary_container.set_visibility(True)
        self._summary_container.clear()

        summary = state.summary
        if summary is None:
            with self._summary_container:
                ui.label("No summary available").style(
                    f"color: {COLORS.text_muted};"
                )
            return

        overall_color = status_color(summary.status)

        # Update progress bar to reflect pass rate
        if summary.total_steps > 0:
            pass_rate = summary.total_pass / summary.total_steps
            bar_color = (
                COLORS.green
                if pass_rate >= 0.9
                else COLORS.yellow if pass_rate >= 0.7 else COLORS.red
            )
            self._progress.set_value(1.0)
            self._progress.props(f'color="{bar_color}"')

        with self._summary_container:
            ui.separator().style(f"background-color: {COLORS.border};")

            with ui.row().classes("items-center gap-6 q-mt-sm"):
                summary_chip(
                    "Result",
                    summary.status.value.upper(),
                    overall_color,
                )
                summary_chip("Pass", str(summary.total_pass), COLORS.green)
                summary_chip("Fail", str(summary.total_fail), COLORS.red)
                summary_chip("Warn", str(summary.total_warn), COLORS.yellow)
                summary_chip("Skip", str(summary.total_skip), COLORS.text_muted)
                summary_chip(
                    "Duration",
                    format_elapsed(summary.duration_ms),
                    COLORS.text_secondary,
                )

            # Download / export actions
            download_action_bar(
                report_url=(
                    f"/api/devices/{self._device_id}/recipes/report"
                ),
                json_url=(
                    f"/api/devices/{self._device_id}/recipes/result"
                ),
            )

    def _request_cancel(self) -> None:
        """Request cancellation via the API."""
        from calypso.workflows.workflow_executor import cancel_recipe

        cancel_recipe(self._device_id)
        ui.notify("Cancellation requested", position="top-right", timeout=3000)

    def cancel(self) -> None:
        """Stop the polling timer."""
        self._finished = True
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
