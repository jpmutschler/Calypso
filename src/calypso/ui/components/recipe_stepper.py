"""Live step-by-step progress display for a running recipe."""

from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from calypso.ui.components.monitor_common import (
    CRITICALITY_BORDER,
    SUBDUED_CRITICALITIES,
    download_action_bar,
    format_elapsed,
    measured_values_table,
    progress_text,
    render_metric_cards,
    status_color,
    status_icon,
    summary_chip,
)
from calypso.ui.theme import COLORS
from calypso.workflows.monitor_state import MonitorState, MonitorStepState
from calypso.workflows.workflow_executor import get_recipe_progress



def _step_badges(step: MonitorStepState) -> None:
    """Render port/lane badges for a step if present."""
    badge_style = (
        f"background: {COLORS.bg_elevated}; color: {COLORS.text_secondary};"
        " font-size: 10px; padding: 2px 6px;"
    )
    if step.port_number is not None:
        ui.badge(f"Port {step.port_number}").style(badge_style)
    if step.lane is not None:
        ui.badge(f"Lane {step.lane}").style(badge_style)


class RecipeStepper:
    """Displays live progress for a single recipe run.

    Creates UI elements for title, progress bar, per-step status list with
    measured values, metric cards, and download actions on completion.

    Uses incremental DOM updates to avoid flicker: metric card values and
    step row labels are updated in-place via ``set_text()`` when the element
    count is stable.  A full ``clear()`` + rebuild only happens when the
    number of displayed elements changes (e.g. a new step appears or the
    "Running" metric card appears/disappears).

    Args:
        device_id: The device ID whose recipe run to monitor.
    """

    def __init__(
        self,
        device_id: str,
        recipe_name: str = "",
        on_rerun: Callable[[str, dict], None] | None = None,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        self._device_id = device_id
        self._on_rerun = on_rerun
        self._on_complete = on_complete
        self._timer: ui.timer | None = None
        self._finished = False
        self._notified = False

        # Cache for incremental metric card updates
        self._metric_cache: dict = {}

        # Incremental update tracking for steps
        self._last_step_count: int = 0
        self._step_elements: list[dict[str, ui.label | ui.icon]] = []

        initial_title = f"Running {recipe_name}..." if recipe_name else "Running recipe..."

        with (
            ui.card()
            .classes("w-full q-pa-md")
            .style(f"background: {COLORS.bg_card}; border: 1px solid {COLORS.border};")
        ):
            with ui.column().classes("w-full q-gutter-sm"):
                # Header row with title and cancel button
                with ui.row().classes("w-full items-center justify-between"):
                    self._title = (
                        ui.label(initial_title)
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

            if self._on_complete is not None:
                self._on_complete()

    def _update_metrics(self, state: MonitorState) -> None:
        """Update live metric cards via shared renderer with caching."""
        render_metric_cards(
            state, self._metrics_container, cache=self._metric_cache
        )

    def _update_steps(self, state: MonitorState) -> None:
        """Update the step list, only rebuilding when step count changes.

        When the step count is stable, existing step row elements are updated
        in-place (icon, name, duration, message) which preserves scroll
        position and avoids visible flicker.
        """
        step_count = len(state.steps)

        if step_count != self._last_step_count:
            # Full rebuild: step count changed (new step appeared)
            self._last_step_count = step_count
            self._step_elements.clear()
            self._steps_container.clear()
            with self._steps_container:
                for step in state.steps:
                    refs = self._build_step_row(step)
                    self._step_elements.append(refs)
        else:
            # Incremental: update existing element text in-place
            for idx, step in enumerate(state.steps):
                if idx >= len(self._step_elements):
                    break
                refs = self._step_elements[idx]
                icon_name, icon_color = status_icon(step.status)
                is_subdued = step.criticality in SUBDUED_CRITICALITIES
                text_color = COLORS.text_muted if is_subdued else COLORS.text_primary

                refs["icon"].props(f'name="{icon_name}"')
                refs["icon"].style(f"color: {icon_color}; font-size: 1.1rem;")
                refs["name"].set_text(step.step_name)
                refs["name"].style(f"color: {text_color}; font-size: 13px;")

                duration_text = (
                    f"{step.duration_ms:.0f}ms" if step.duration_ms > 0 else ""
                )
                refs["duration"].set_text(duration_text)
                refs["duration"].set_visibility(step.duration_ms > 0)

                refs["message"].set_text(step.message)
                refs["message"].set_visibility(bool(step.message))

    def _build_step_row(self, step: MonitorStepState) -> dict[str, ui.label | ui.icon]:
        """Build a single step row and return references to updatable elements."""
        icon_name, icon_color = status_icon(step.status)
        border_color = CRITICALITY_BORDER.get(step.criticality)
        is_subdued = step.criticality in SUBDUED_CRITICALITIES
        text_color = COLORS.text_muted if is_subdued else COLORS.text_primary

        border_style = (
            f"border-left: 3px solid {border_color}; padding-left: 8px;"
            if border_color
            else ""
        )

        with ui.column().classes("w-full q-py-xs").style(border_style):
            with ui.row().classes("items-center gap-2"):
                icon_el = ui.icon(icon_name).style(
                    f"color: {icon_color}; font-size: 1.1rem;"
                )
                name_el = ui.label(step.step_name).style(
                    f"color: {text_color}; font-size: 13px;"
                )
                _step_badges(step)
                duration_el = ui.label(
                    f"{step.duration_ms:.0f}ms" if step.duration_ms > 0 else ""
                ).style(f"color: {COLORS.text_muted}; font-size: 11px;")
                duration_el.set_visibility(step.duration_ms > 0)

            message_el = ui.label(step.message).style(
                f"color: {COLORS.text_secondary}; font-size: 12px;"
                " padding-left: 28px;"
            )
            message_el.set_visibility(bool(step.message))

            if step.measured_values:
                with ui.element("div").style("padding-left: 28px;"):
                    measured_values_table(step.measured_values)

        return {
            "icon": icon_el,
            "name": name_el,
            "duration": duration_el,
            "message": message_el,
        }

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

            # Run Again button
            if self._on_rerun is not None:
                rerun_id = summary.recipe_id
                rerun_params = dict(summary.parameters)

                ui.button(
                    "Run Again",
                    icon="replay",
                    on_click=lambda: self._on_rerun(rerun_id, rerun_params),
                ).props("flat").style(f"color: {COLORS.cyan};")

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
