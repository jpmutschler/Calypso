"""Terminal formatting helpers for recipe and workflow CLI output."""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from calypso.workflows.models import RecipeResult, RecipeSummary


# ---------------------------------------------------------------------------
# Status icons and colors
# ---------------------------------------------------------------------------

_STATUS_ICONS: dict[str, str] = {
    "pass": "\u2713",  # checkmark
    "fail": "\u2717",  # ballot x
    "warn": "\u26a0",  # warning triangle
    "skip": "\u25cb",  # white circle
    "error": "\u2717",  # ballot x
    "running": "\u25cf",  # black circle
    "pending": "\u25cb",  # white circle
}

_STATUS_COLORS: dict[str, str] = {
    "pass": "green",
    "fail": "red",
    "warn": "yellow",
    "skip": "white",
    "error": "red",
    "running": "cyan",
    "pending": "white",
}


def status_icon(status: str) -> str:
    """Return a Unicode icon for the given step status."""
    return _STATUS_ICONS.get(status, "?")


def status_color(status: str) -> str:
    """Return a click style color name for the given step status."""
    return _STATUS_COLORS.get(status, "white")


# ---------------------------------------------------------------------------
# Line formatters
# ---------------------------------------------------------------------------


def format_step_header(step_name: str, status: str) -> str:
    """Format a colored step header line.

    Example: ``  [checkmark] Enumerate ports``
    """
    icon = status_icon(status)
    color = status_color(status)
    styled_icon = click.style(icon, fg=color)
    return f"  {styled_icon} {step_name}"


def format_result_line(result: RecipeResult) -> str:
    """Format a single completed step result with icon, name, and duration.

    Example: ``  [checkmark] Port 0 (UP x16 64GT)        0.5ms``
    """
    icon = status_icon(result.status)
    color = status_color(result.status)
    styled_prefix = click.style(f"  {icon}", fg=color)

    label = result.step_name
    if result.message and result.message != f"Running: {result.step_name}":
        label = result.message

    duration_str = _format_duration(result.duration_ms)
    # Right-align duration at column 40
    padding = max(1, 40 - len(label))
    return f"{styled_prefix} {label}{' ' * padding}{duration_str}"


def format_summary_table(summary: RecipeSummary) -> str:
    """Format a complete recipe execution summary as an ASCII table.

    Includes a header line, each step result, a separator, and totals.
    """
    from calypso.workflows.models import CATEGORY_DISPLAY_NAMES

    lines: list[str] = []

    # Header
    category_name = CATEGORY_DISPLAY_NAMES.get(summary.category, summary.category)
    lines.append(
        click.style(f"Recipe: {summary.recipe_name}", bold=True)
        + click.style(f" ({summary.recipe_id})", fg="bright_black")
    )
    lines.append(click.style(f"Category: {category_name}", fg="cyan"))
    lines.append(_separator())

    # Step results
    for step in summary.steps:
        lines.append(format_result_line(step))

    # Footer
    lines.append(_separator())

    # Counts
    parts: list[str] = []
    if summary.total_pass > 0:
        parts.append(click.style(f"{summary.total_pass} pass", fg="green"))
    if summary.total_fail > 0:
        parts.append(click.style(f"{summary.total_fail} fail", fg="red"))
    if summary.total_warn > 0:
        parts.append(click.style(f"{summary.total_warn} warn", fg="yellow"))
    if summary.total_skip > 0:
        parts.append(click.style(f"{summary.total_skip} skip", fg="white"))
    if summary.total_error > 0:
        parts.append(click.style(f"{summary.total_error} error", fg="red"))

    counts_str = ", ".join(parts) if parts else "no steps"
    duration_str = _format_duration(summary.duration_ms)
    lines.append(f"Summary: {counts_str} | {duration_str}")

    # Overall status
    overall_color = status_color(summary.status)
    overall_label = summary.status.upper()
    lines.append("Overall: " + click.style(overall_label, fg=overall_color, bold=True))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Workflow summary (multi-recipe)
# ---------------------------------------------------------------------------


def format_workflow_summary(summaries: list[RecipeSummary], workflow_name: str) -> str:
    """Format a multi-recipe workflow execution summary."""
    lines: list[str] = []

    lines.append(click.style(f"Workflow: {workflow_name}", bold=True))
    lines.append(_separator())

    for summary in summaries:
        icon = status_icon(summary.status)
        color = status_color(summary.status)
        styled = click.style(f"  {icon}", fg=color)
        duration_str = _format_duration(summary.duration_ms)
        padding = max(1, 40 - len(summary.recipe_name))
        lines.append(f"{styled} {summary.recipe_name}{' ' * padding}{duration_str}")

    lines.append(_separator())

    total_pass = sum(s.total_pass for s in summaries)
    total_fail = sum(s.total_fail for s in summaries)
    total_warn = sum(s.total_warn for s in summaries)
    total_duration = sum(s.duration_ms for s in summaries)

    parts: list[str] = []
    if total_pass > 0:
        parts.append(click.style(f"{total_pass} pass", fg="green"))
    if total_fail > 0:
        parts.append(click.style(f"{total_fail} fail", fg="red"))
    if total_warn > 0:
        parts.append(click.style(f"{total_warn} warn", fg="yellow"))

    counts_str = ", ".join(parts) if parts else "no results"
    lines.append(f"Total: {counts_str} | {_format_duration(total_duration)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _separator(width: int = 48) -> str:
    """Return a horizontal line separator."""
    return click.style("\u2500" * width, fg="bright_black")


def _format_duration(ms: float) -> str:
    """Format a millisecond duration for display."""
    if ms < 1000:
        return f"{ms:.1f}ms"
    return f"{ms / 1000:.2f}s"
