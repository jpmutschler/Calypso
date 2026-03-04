"""Live metric cards for recipe/workflow execution in the UI."""

from __future__ import annotations

from nicegui import ui

from calypso.ui.theme import COLORS
from calypso.workflows.models import StepStatus
from calypso.workflows.monitor_state import MonitorState


class MonitorMetrics:
    """Renders live metric cards that update during execution."""

    def __init__(self) -> None:
        self._container: ui.row | None = None
        self._pass_label: ui.label | None = None
        self._fail_label: ui.label | None = None
        self._warn_label: ui.label | None = None
        self._duration_label: ui.label | None = None
        self._steps_label: ui.label | None = None

    def render(self) -> None:
        """Build the metrics card row."""
        self._container = ui.row().classes("w-full gap-3 mt-2")
        with self._container:
            self._pass_label = _metric_chip("Pass", "0", COLORS.green)
            self._fail_label = _metric_chip("Fail", "0", COLORS.red)
            self._warn_label = _metric_chip("Warn", "0", COLORS.yellow)
            self._steps_label = _metric_chip("Steps", "0/0", COLORS.cyan)
            self._duration_label = _metric_chip("Duration", "0.0s", COLORS.text_secondary)

    def update(self, state: MonitorState) -> None:
        """Update metric values from monitor state."""
        if state is None:
            return

        pass_count = sum(1 for s in state.steps if s.status == StepStatus.PASS)
        fail_count = sum(1 for s in state.steps if s.status == StepStatus.FAIL)
        warn_count = sum(1 for s in state.steps if s.status == StepStatus.WARN)

        if self._pass_label:
            self._pass_label.set_text(str(pass_count))
        if self._fail_label:
            self._fail_label.set_text(str(fail_count))
        if self._warn_label:
            self._warn_label.set_text(str(warn_count))
        if self._steps_label:
            self._steps_label.set_text(f"{state.steps_completed}/{state.steps_total}")
        if self._duration_label:
            secs = state.elapsed_ms / 1000
            self._duration_label.set_text(f"{secs:.1f}s")

    def update_from_summary(self, summary) -> None:
        """Update from a completed RecipeSummary."""
        if summary is None:
            return
        if self._pass_label:
            self._pass_label.set_text(str(summary.total_pass))
        if self._fail_label:
            self._fail_label.set_text(str(summary.total_fail))
        if self._warn_label:
            self._warn_label.set_text(str(summary.total_warn))
        if self._steps_label:
            self._steps_label.set_text(str(summary.total_steps))
        if self._duration_label:
            secs = summary.duration_ms / 1000
            self._duration_label.set_text(f"{secs:.1f}s")


def _metric_chip(label: str, initial_value: str, color: str) -> ui.label:
    """Create a single metric chip and return the value label for updates."""
    with (
        ui.column()
        .classes("items-center")
        .style(
            f"background: {COLORS.bg_card}; border: 1px solid {COLORS.border}; "
            f"border-radius: 8px; padding: 8px 16px; min-width: 80px;"
        )
    ):
        value_label = (
            ui.label(initial_value)
            .classes("text-subtitle1")
            .style(f"color: {color}; font-weight: bold;")
        )
        ui.label(label).style(f"color: {COLORS.text_muted}; font-size: 11px;")
    return value_label
