"""JSON and CSV export utilities for recipe/workflow results."""

from __future__ import annotations

import csv
import io
import json

from calypso.workflows.models import RecipeSummary


def export_json(summaries: list[RecipeSummary], indent: int = 2) -> str:
    """Export recipe summaries as a JSON string."""
    data = [s.to_export_dict() for s in summaries]
    return json.dumps(data, indent=indent, default=str)


def export_single_json(summary: RecipeSummary, indent: int = 2) -> str:
    """Export a single recipe summary as JSON."""
    return json.dumps(summary.to_export_dict(), indent=indent, default=str)


def export_csv(summaries: list[RecipeSummary]) -> str:
    """Export recipe summaries as a CSV string.

    Produces one row per step across all recipes.
    """
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(
        [
            "recipe_id",
            "recipe_name",
            "category",
            "recipe_status",
            "step_name",
            "step_status",
            "criticality",
            "message",
            "duration_ms",
            "port_number",
            "lane",
        ]
    )

    for summary in summaries:
        for step in summary.steps:
            writer.writerow(
                [
                    summary.recipe_id,
                    summary.recipe_name,
                    summary.category.value,
                    summary.status.value,
                    step.step_name,
                    step.status.value,
                    step.criticality.value,
                    step.message,
                    f"{step.duration_ms:.2f}",
                    step.port_number if step.port_number is not None else "",
                    step.lane if step.lane is not None else "",
                ]
            )

    return output.getvalue()


def export_summary_csv(summaries: list[RecipeSummary]) -> str:
    """Export recipe-level summary as CSV (one row per recipe)."""
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(
        [
            "recipe_id",
            "recipe_name",
            "category",
            "status",
            "total_steps",
            "pass",
            "fail",
            "warn",
            "skip",
            "error",
            "pass_rate",
            "duration_ms",
            "started_at",
            "completed_at",
        ]
    )

    for s in summaries:
        writer.writerow(
            [
                s.recipe_id,
                s.recipe_name,
                s.category.value,
                s.status.value,
                s.total_steps,
                s.total_pass,
                s.total_fail,
                s.total_warn,
                s.total_skip,
                s.total_error,
                f"{s.pass_rate:.1f}",
                f"{s.duration_ms:.2f}",
                s.started_at,
                s.completed_at,
            ]
        )

    return output.getvalue()
