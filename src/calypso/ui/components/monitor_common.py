"""Shared UI helpers for recipe/workflow monitoring components."""

from __future__ import annotations

import json as _json

from nicegui import ui

from calypso.ui.theme import COLORS
from calypso.workflows.models import StepStatus
from calypso.workflows.monitor_state import MonitorState, MonitorStepState

# ── Status icon mapping ──────────────────────────────────────────────────

_STATUS_DISPLAY: dict[StepStatus, tuple[str, str]] = {
    StepStatus.PENDING: ("radio_button_unchecked", COLORS.text_muted),
    StepStatus.RUNNING: ("sync", COLORS.cyan),
    StepStatus.PASS: ("check_circle", COLORS.green),
    StepStatus.FAIL: ("cancel", COLORS.red),
    StepStatus.WARN: ("warning", COLORS.yellow),
    StepStatus.SKIP: ("skip_next", COLORS.text_muted),
    StepStatus.ERROR: ("error", COLORS.red),
}


def status_icon(status: StepStatus) -> tuple[str, str]:
    """Return ``(icon_name, color)`` for the given step status."""
    return _STATUS_DISPLAY.get(status, ("help_outline", COLORS.text_muted))


def status_color(status: StepStatus | str) -> str:
    """Return display color for a status (StepStatus or string)."""
    if isinstance(status, StepStatus):
        _, color = _STATUS_DISPLAY.get(status, ("", COLORS.text_secondary))
        return color
    key = str(status).lower()
    for member in StepStatus:
        if member.value.lower() == key:
            _, color = _STATUS_DISPLAY.get(member, ("", COLORS.text_secondary))
            return color
    return COLORS.text_secondary


# ── Step status counting ─────────────────────────────────────────────────


def count_step_statuses(
    steps: list[MonitorStepState],
) -> dict[StepStatus, int]:
    """Count steps by status. Returns a dict with all statuses that appear."""
    counts: dict[StepStatus, int] = {}
    for s in steps:
        counts[s.status] = counts.get(s.status, 0) + 1
    return counts


# ── Elapsed time formatting ──────────────────────────────────────────────


def format_elapsed(ms: float) -> str:
    """Format elapsed milliseconds as human-readable string."""
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    remaining = int(seconds % 60)
    return f"{minutes}:{remaining:02d}"


# ── Progress text ────────────────────────────────────────────────────────


def progress_text(state: MonitorState) -> str:
    """Build status line text from monitor state."""
    step_info = (
        f" ({state.steps_completed}/{state.steps_total})"
        if state.steps_total > 0
        else ""
    )
    current = f" - {state.current_step}" if state.current_step else ""
    return f"{state.status.upper()}{current}{step_info}"


# ── Metric card ──────────────────────────────────────────────────────────


def metric_card(label: str, value: str, color: str) -> None:
    """Render a compact metric card with value and label."""
    with (
        ui.card()
        .classes("q-pa-sm")
        .style(
            f"background: {COLORS.bg_primary}; border: 1px solid {COLORS.border};"
            " min-width: 80px;"
        )
    ):
        with ui.column().classes("items-center"):
            ui.label(value).classes("text-h6").style(
                f"color: {color}; font-weight: bold;"
            )
            ui.label(label).style(f"color: {COLORS.text_muted}; font-size: 11px;")


# ── Measured values table ────────────────────────────────────────────────


def _format_measured_value(key: str, val: object) -> tuple[str, str]:
    """Format a measured value with units and color coding."""
    key_lower = key.lower()

    if isinstance(val, float):
        if "rate" in key_lower or "ber" in key_lower:
            formatted = f"{val:.2e}"
        elif "bandwidth" in key_lower or "gbps" in key_lower:
            formatted = f"{val:.1f} Gbps"
        elif "percent" in key_lower or "pct" in key_lower:
            formatted = f"{val:.1f}%"
        else:
            formatted = f"{val:.3g}"
    elif isinstance(val, int):
        if "0x" in key_lower or "register" in key_lower or "addr" in key_lower:
            formatted = f"0x{val:08X}"
        else:
            formatted = f"{val:,}"
    else:
        formatted = str(val)

    # Color-code anomalies
    color = COLORS.text_primary
    if "error" in key_lower and isinstance(val, (int, float)) and val > 0:
        color = COLORS.red
    elif "ber" in key_lower and isinstance(val, float) and val > 1e-12:
        color = COLORS.yellow

    return formatted, color


def measured_values_table(values: dict[str, object]) -> None:
    """Render measured_values as a compact key-value block."""
    if not values:
        return

    with ui.element("div").style(
        f"background: {COLORS.bg_primary}; border: 1px solid {COLORS.border};"
        " border-radius: 4px; padding: 8px; margin-top: 4px;"
    ):
        ui.label("Measured Values").style(
            f"color: {COLORS.text_muted}; font-size: 11px;"
            " text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px;"
        )
        for key, val in values.items():
            display_key = key.replace("_", " ").title()
            display_val, val_color = _format_measured_value(key, val)
            with ui.row().classes("items-center justify-between w-full q-py-xs"):
                ui.label(display_key).style(
                    f"color: {COLORS.text_secondary}; font-size: 12px;"
                )
                ui.label(display_val).classes("mono").style(
                    f"color: {val_color}; font-size: 12px; font-weight: 500;"
                )


# ── Download action bar ──────────────────────────────────────────────────


def download_action_bar(
    *,
    report_url: str,
    json_url: str | None = None,
    csv_url: str | None = None,
) -> None:
    """Render a row of export/download buttons.

    URLs are safely escaped via ``json.dumps`` before interpolation into
    JavaScript to prevent XSS from untrusted path segments.
    """
    safe_report = _json.dumps(report_url)

    with ui.row().classes("w-full q-mt-md gap-2"):
        ui.button(
            "Download Report",
            icon="download",
            on_click=lambda: ui.run_javascript(
                f"window.open({safe_report}, '_blank')"
            ),
        ).props("flat").style(
            f"color: {COLORS.cyan}; border: 1px solid {COLORS.border};"
        )

        if json_url:
            safe_json = _json.dumps(json_url)
            ui.button(
                "JSON",
                icon="data_object",
                on_click=lambda: ui.run_javascript(
                    f"window.open({safe_json}, '_blank')"
                ),
            ).props("flat").style(
                f"color: {COLORS.text_secondary}; border: 1px solid {COLORS.border};"
            )

        if csv_url:
            safe_csv = _json.dumps(csv_url)
            ui.button(
                "CSV",
                icon="table_chart",
                on_click=lambda: ui.run_javascript(
                    f"window.open({safe_csv}, '_blank')"
                ),
            ).props("flat").style(
                f"color: {COLORS.text_secondary}; border: 1px solid {COLORS.border};"
            )


# ── Summary chip ─────────────────────────────────────────────────────────


def summary_chip(label: str, value: str, color: str) -> None:
    """Render a small stat chip (value above label)."""
    with ui.column().classes("items-center"):
        ui.label(value).classes("text-subtitle1").style(
            f"color: {color}; font-weight: bold;"
        )
        ui.label(label).style(f"color: {COLORS.text_muted}; font-size: 11px;")
