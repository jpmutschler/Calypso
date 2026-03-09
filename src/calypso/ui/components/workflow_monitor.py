"""Multi-recipe workflow progress monitor."""

from __future__ import annotations

from nicegui import ui

from calypso.ui.components.monitor_common import (
    CRITICALITY_BORDER,
    download_action_bar,
    format_elapsed,
    measured_values_table,
    progress_text,
    render_metric_cards,
    status_color,
    status_icon,
)
from calypso.ui.theme import COLORS
from calypso.workflows.models import StepStatus
from calypso.workflows.monitor_state import MonitorState, MonitorStepState
from calypso.workflows.workflow_executor import get_run_progress, get_run_results



def _panel_header_text(step: MonitorStepState) -> str:
    """Build the expansion panel header, appending port/lane when present."""
    parts: list[str] = []
    if step.port_number is not None:
        parts.append(f"Port {step.port_number}")
    if step.lane is not None:
        parts.append(f"Lane {step.lane}")
    if parts:
        return f"{step.step_name} [{', '.join(parts)}]"
    return step.step_name


class WorkflowMonitor:
    """Displays live progress for a multi-step workflow run.

    Creates an overall progress bar, metric cards, per-step expansion panels
    with measured values, and download actions on completion.

    Uses incremental DOM updates to avoid flicker: metric card values and
    expansion panel labels are updated in-place via ``set_text()`` when the
    element count is stable.  A full ``clear()`` + rebuild only happens when
    the number of displayed elements changes.  This preserves the user's
    open/close state on expansion panels.

    Args:
        run_id: The workflow run ID to monitor.
        device_id: The device ID (used for report download URLs).
    """

    def __init__(self, run_id: str, device_id: str = "") -> None:
        self._run_id = run_id
        self._device_id = device_id
        self._timer: ui.timer | None = None
        self._finished = False
        self._notified = False

        # Cache for incremental metric card updates
        self._metric_cache: dict = {}

        # Incremental update tracking for panels
        self._last_panel_count: int = 0
        self._panel_elements: list[dict[str, ui.label | ui.expansion]] = []

        with (
            ui.card()
            .classes("w-full q-pa-md")
            .style(f"background: {COLORS.bg_card}; border: 1px solid {COLORS.border};")
        ):
            with ui.column().classes("w-full q-gutter-sm"):
                # Header row with title and cancel button
                with ui.row().classes("w-full items-center justify-between"):
                    self._title = (
                        ui.label("Running workflow...")
                        .classes("text-subtitle1")
                        .style(f"color: {COLORS.text_primary}; font-weight: 600;")
                    )
                    self._cancel_btn = (
                        ui.button(icon="stop", on_click=self._request_cancel)
                        .props("flat round size=sm")
                        .style(f"color: {COLORS.red};")
                        .tooltip("Cancel workflow")
                    )

                # Overall progress
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

                # Metric cards row
                self._metrics_container = ui.row().classes("w-full gap-4 q-mt-sm")

                # Step panels
                self._panels_container = ui.column().classes(
                    "w-full q-mt-sm q-gutter-sm"
                )

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
        self._status_label.set_text(progress_text(state))
        self._elapsed_label.set_text(f"Elapsed: {format_elapsed(state.elapsed_ms)}")

        # Switch from indeterminate to determinate once we have step data
        if state.steps_total > 0:
            self._progress.props(remove="indeterminate")
            self._progress.set_value(state.percent / 100.0)

        # Update metrics incrementally
        self._update_metrics(state)

        # Update step panels incrementally
        self._update_panels(state)

        if state.status in ("complete", "cancelled", "error"):
            self._finished = True
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._cancel_btn.set_visibility(False)
            self._render_results()

            if not self._notified:
                self._notified = True
                status_text = (
                    "completed" if state.status == "complete" else state.status
                )
                notify_type = (
                    "positive" if state.status == "complete" else "negative"
                )
                ui.notify(
                    f"Workflow {status_text}",
                    type=notify_type,
                    position="top-right",
                    timeout=5000,
                )

    def _update_metrics(self, state: MonitorState) -> None:
        """Update metric cards via shared renderer with caching."""
        render_metric_cards(
            state, self._metrics_container, cache=self._metric_cache
        )

    def _update_panels(self, state: MonitorState) -> None:
        """Update per-step expansion panels, only rebuilding when count changes.

        When panel count is stable, update text labels in-place to preserve
        the user's open/close state on expansion panels.
        """
        panel_count = len(state.steps)

        if panel_count != self._last_panel_count:
            # Full rebuild: panel count changed
            self._last_panel_count = panel_count
            self._panel_elements.clear()
            self._panels_container.clear()
            with self._panels_container:
                for step in state.steps:
                    refs = self._build_panel(step)
                    self._panel_elements.append(refs)
        else:
            # Incremental: update existing panel text in-place
            for idx, step in enumerate(state.steps):
                if idx >= len(self._panel_elements):
                    break
                refs = self._panel_elements[idx]
                step_clr = status_color(step.status)
                icon_name, _ = status_icon(step.status)
                header_text = _panel_header_text(step)

                refs["expansion"].props(f'icon="{icon_name}"')
                refs["expansion"].text = header_text
                refs["expansion"].update()

                refs["status_label"].set_text(
                    f"{step.status.value.upper()} - {step.message}"
                )
                refs["status_label"].style(
                    f"color: {step_clr}; font-size: 13px;"
                )

                duration_text = (
                    f"Duration: {format_elapsed(step.duration_ms)}"
                    if step.duration_ms > 0
                    else ""
                )
                refs["duration_label"].set_text(duration_text)
                refs["duration_label"].set_visibility(step.duration_ms > 0)

    def _build_panel(
        self, step: MonitorStepState
    ) -> dict[str, ui.label | ui.expansion]:
        """Build a single expansion panel for a step, returning element refs."""
        step_clr = status_color(step.status)
        icon_name, _ = status_icon(step.status)
        is_running = step.status == StepStatus.RUNNING

        header_text = _panel_header_text(step)
        border_color = CRITICALITY_BORDER.get(step.criticality)
        border_style = (
            f"background: {COLORS.bg_primary};"
            f" border: 1px solid {COLORS.border};"
        )
        if border_color:
            border_style += f" border-left: 3px solid {border_color};"

        with (
            ui.expansion(
                text=header_text,
                icon=icon_name,
            )
            .classes("w-full")
            .style(border_style)
            .props("default-opened" if is_running else "")
        ) as expansion_el:
            status_label = ui.label(
                f"{step.status.value.upper()} - {step.message}"
            ).style(f"color: {step_clr}; font-size: 13px;")

            duration_label = ui.label(
                f"Duration: {format_elapsed(step.duration_ms)}"
                if step.duration_ms > 0
                else ""
            ).style(f"color: {COLORS.text_muted}; font-size: 12px;")
            duration_label.set_visibility(step.duration_ms > 0)

            if step.measured_values:
                measured_values_table(step.measured_values)

        return {
            "expansion": expansion_el,
            "status_label": status_label,
            "duration_label": duration_label,
        }

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
                overall_color = status_color(summary.status)
                with (
                    ui.card()
                    .classes("w-full q-pa-sm q-mt-xs")
                    .style(
                        f"background: {COLORS.bg_primary};"
                        f" border: 1px solid {COLORS.border};"
                    )
                ):
                    with ui.row().classes("items-center gap-3 w-full"):
                        ui.label(summary.recipe_name).style(
                            f"color: {COLORS.text_primary}; font-weight: 500;"
                        )
                        ui.badge(summary.status.value.upper()).style(
                            f"background: {overall_color}20;"
                            f" color: {overall_color};"
                        )
                        ui.space()
                        ui.label(
                            f"P:{summary.total_pass} F:{summary.total_fail}"
                            f" W:{summary.total_warn}"
                        ).style(
                            f"color: {COLORS.text_secondary}; font-size: 12px;"
                        )
                        ui.label(format_elapsed(summary.duration_ms)).style(
                            f"color: {COLORS.text_muted}; font-size: 12px;"
                        )

            # Download / export actions
            if self._device_id:
                download_action_bar(
                    report_url=(
                        f"/api/devices/{self._device_id}"
                        f"/workflows/report/{self._run_id}"
                    ),
                    json_url=(
                        f"/api/devices/{self._device_id}"
                        f"/workflows/result/{self._run_id}"
                    ),
                )

    def _request_cancel(self) -> None:
        """Request cancellation via the executor."""
        from calypso.workflows.workflow_executor import cancel_run

        cancel_run(self._run_id)
        ui.notify("Cancellation requested", position="top-right", timeout=3000)

    def cancel(self) -> None:
        """Stop the polling timer."""
        self._finished = True
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
