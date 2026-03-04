"""Live step-by-step progress display for a running recipe."""

from __future__ import annotations

from nicegui import ui

from calypso.ui.theme import COLORS
from calypso.workflows.models import StepStatus
from calypso.workflows.workflow_executor import get_recipe_progress


_STATUS_DISPLAY: dict[StepStatus, tuple[str, str]] = {
    StepStatus.PENDING: ("radio_button_unchecked", COLORS.text_muted),
    StepStatus.RUNNING: ("sync", COLORS.cyan),
    StepStatus.PASS: ("check_circle", COLORS.green),
    StepStatus.FAIL: ("cancel", COLORS.red),
    StepStatus.WARN: ("warning", COLORS.yellow),
    StepStatus.SKIP: ("skip_next", COLORS.text_muted),
    StepStatus.ERROR: ("error", COLORS.red),
}


class RecipeStepper:
    """Displays live progress for a single recipe run.

    Creates UI elements for title, progress bar, and per-step status list,
    then polls ``get_recipe_progress`` on a timer to keep the display current.

    Args:
        device_id: The device ID whose recipe run to monitor.
    """

    def __init__(self, device_id: str) -> None:
        self._device_id = device_id
        self._timer: ui.timer | None = None
        self._finished = False

        with (
            ui.card()
            .classes("w-full q-pa-md")
            .style(f"background: {COLORS.bg_card}; border: 1px solid {COLORS.border};")
        ):
            with ui.column().classes("w-full q-gutter-sm"):
                self._title = (
                    ui.label("Running recipe...")
                    .classes("text-subtitle1")
                    .style(f"color: {COLORS.text_primary}; font-weight: 600;")
                )

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
        self._progress.set_value(state.percent / 100.0)
        self._status_label.set_text(
            f"{state.status.upper()} - {state.current_step}"
            f" ({state.steps_completed}/{state.steps_total})"
        )
        self._elapsed_label.set_text(f"Elapsed: {state.elapsed_ms / 1000:.1f}s")

        # Rebuild step list
        self._steps_container.clear()
        with self._steps_container:
            for step in state.steps:
                icon_name, icon_color = _status_icon(step.status)
                with ui.row().classes("items-center gap-2 q-py-xs"):
                    ui.icon(icon_name).style(f"color: {icon_color}; font-size: 1.1rem;")
                    ui.label(step.step_name).style(
                        f"color: {COLORS.text_primary}; font-size: 13px;"
                    )
                    if step.message:
                        ui.label(step.message).style(
                            f"color: {COLORS.text_secondary}; font-size: 12px;"
                        )
                    if step.duration_ms > 0:
                        ui.label(f"{step.duration_ms:.0f}ms").style(
                            f"color: {COLORS.text_muted}; font-size: 11px;"
                        )

        # Check for completion
        if state.status in ("complete", "cancelled", "error"):
            self._finished = True
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._render_summary(state)

    def _render_summary(self, state) -> None:
        """Render the final summary after recipe completion."""
        self._summary_container.set_visibility(True)
        self._summary_container.clear()

        summary = state.summary
        if summary is None:
            with self._summary_container:
                ui.label("No summary available").style(f"color: {COLORS.text_muted};")
            return

        overall_color = _status_color(summary.status)

        with self._summary_container:
            ui.separator().style(f"background-color: {COLORS.border};")

            with ui.row().classes("items-center gap-6 q-mt-sm"):
                _summary_chip(
                    "Result",
                    summary.status.value.upper(),
                    overall_color,
                )
                _summary_chip("Pass", str(summary.total_pass), COLORS.green)
                _summary_chip("Fail", str(summary.total_fail), COLORS.red)
                _summary_chip("Warn", str(summary.total_warn), COLORS.yellow)
                _summary_chip("Skip", str(summary.total_skip), COLORS.text_muted)
                _summary_chip(
                    "Duration",
                    f"{summary.duration_ms / 1000:.1f}s",
                    COLORS.text_secondary,
                )

    def cancel(self) -> None:
        """Stop the polling timer."""
        self._finished = True
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None


def _status_icon(status: StepStatus) -> tuple[str, str]:
    """Return (icon_name, color) for the given step status."""
    return _STATUS_DISPLAY.get(status, ("help_outline", COLORS.text_muted))


def _status_color(status: StepStatus) -> str:
    """Return the display color for an overall status."""
    return {
        StepStatus.PASS: COLORS.green,
        StepStatus.FAIL: COLORS.red,
        StepStatus.WARN: COLORS.yellow,
        StepStatus.SKIP: COLORS.text_muted,
        StepStatus.ERROR: COLORS.red,
    }.get(status, COLORS.text_secondary)


def _summary_chip(label: str, value: str, color: str) -> None:
    """Render a small stat chip for the summary row."""
    with ui.column().classes("items-center"):
        ui.label(value).classes("text-subtitle1").style(f"color: {color}; font-weight: bold;")
        ui.label(label).style(f"color: {COLORS.text_muted}; font-size: 11px;")
