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


_CSV_FORMULA_CHARS = frozenset("=+-@\t\r")


def _sanitize_csv_value(value: object) -> object:
    """Sanitize a string value to prevent CSV formula injection (CWE-1236).

    Prefixes a leading single-quote if the string starts with a character
    that spreadsheet applications interpret as a formula trigger.
    """
    if isinstance(value, str) and value and value[0] in _CSV_FORMULA_CHARS:
        return f"'{value}"
    return value


def _is_scalar(value: object) -> bool:
    """Return True if value is a scalar type suitable for a CSV column."""
    return isinstance(value, (str, int, float, bool)) or value is None


def _collect_scalar_keys(summaries: list[RecipeSummary]) -> list[str]:
    """Collect the sorted union of all scalar measured_values keys across all steps."""
    keys: set[str] = set()
    for summary in summaries:
        for step in summary.steps:
            for key, value in step.measured_values.items():
                if _is_scalar(value):
                    keys.add(key)
    return sorted(keys)


def _serialize_measured_values(measured_values: dict[str, object]) -> str:
    """Serialize a measured_values dict to a JSON string."""
    if not measured_values:
        return ""
    return json.dumps(measured_values, default=str)


def export_csv(summaries: list[RecipeSummary]) -> str:
    """Export recipe summaries as a CSV string.

    Produces one row per step across all recipes. Includes a
    ``measured_values_json`` column with the full serialized dict, plus
    individual columns for each scalar top-level key found across all steps.
    """
    output = io.StringIO()
    writer = csv.writer(output)

    scalar_keys = _collect_scalar_keys(summaries)

    fixed_columns = [
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
        "timestamp",
    ]
    writer.writerow(fixed_columns + ["measured_values_json"] + scalar_keys)

    for summary in summaries:
        for step in summary.steps:
            mv = step.measured_values or {}
            fixed_row = [
                _sanitize_csv_value(summary.recipe_id),
                _sanitize_csv_value(summary.recipe_name),
                _sanitize_csv_value(summary.category.value),
                _sanitize_csv_value(summary.status.value),
                _sanitize_csv_value(step.step_name),
                _sanitize_csv_value(step.status.value),
                _sanitize_csv_value(step.criticality.value),
                _sanitize_csv_value(step.message),
                f"{step.duration_ms:.2f}",
                step.port_number if step.port_number is not None else "",
                step.lane if step.lane is not None else "",
                _sanitize_csv_value(step.timestamp),
            ]
            mv_json = _serialize_measured_values(mv)
            scalar_values: list[object] = []
            for key in scalar_keys:
                raw = mv.get(key)
                scalar_values.append("" if raw is None else _sanitize_csv_value(raw))
            writer.writerow(fixed_row + [mv_json] + scalar_values)

    return output.getvalue()


def _collect_lane_keys(summaries: list[RecipeSummary]) -> list[str]:
    """Collect sorted union of all keys from lane dicts across all steps."""
    keys: set[str] = set()
    for summary in summaries:
        for step in summary.steps:
            lanes = step.measured_values.get("lanes", [])
            if isinstance(lanes, list):
                for lane in lanes:
                    if isinstance(lane, dict):
                        for k in lane:
                            keys.add(k)
    return sorted(keys)


def export_lane_csv(summaries: list[RecipeSummary]) -> str:
    """Export per-lane data as a flattened CSV (one row per lane per step).

    Only includes steps that have a 'lanes' list in measured_values.
    Steps without lane data are omitted.
    """
    output = io.StringIO()
    writer = csv.writer(output)

    lane_keys = _collect_lane_keys(summaries)
    if not lane_keys:
        return ""

    fixed_columns = [
        "recipe_id",
        "recipe_name",
        "step_name",
        "step_status",
        "lane_index",
    ]
    writer.writerow(fixed_columns + lane_keys)

    for summary in summaries:
        for step in summary.steps:
            lanes = step.measured_values.get("lanes", [])
            if not isinstance(lanes, list):
                continue
            for idx, lane in enumerate(lanes):
                if not isinstance(lane, dict):
                    continue
                fixed_row = [
                    _sanitize_csv_value(summary.recipe_id),
                    _sanitize_csv_value(summary.recipe_name),
                    _sanitize_csv_value(step.step_name),
                    _sanitize_csv_value(step.status.value),
                    idx,
                ]
                lane_values = [
                    _sanitize_csv_value(lane.get(k, "")) for k in lane_keys
                ]
                writer.writerow(fixed_row + lane_values)

    return output.getvalue()


def export_summary_csv(summaries: list[RecipeSummary]) -> str:
    """Export recipe-level summary as CSV (one row per recipe).

    Includes ``device_id`` and a ``measured_values_json`` column containing
    the aggregated measured_values from the last step of each recipe.
    """
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(
        [
            "recipe_id",
            "recipe_name",
            "category",
            "status",
            "device_id",
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
            "measured_values_json",
        ]
    )

    for s in summaries:
        # Use the step with the richest measured_values (most keys) as the
        # aggregate, since the analysis step may not always be last.
        best_mv: dict[str, object] = {}
        for step in s.steps:
            mv = step.measured_values or {}
            if len(mv) > len(best_mv):
                best_mv = mv

        writer.writerow(
            [
                _sanitize_csv_value(s.recipe_id),
                _sanitize_csv_value(s.recipe_name),
                _sanitize_csv_value(s.category.value),
                _sanitize_csv_value(s.status.value),
                _sanitize_csv_value(s.device_id),
                s.total_steps,
                s.total_pass,
                s.total_fail,
                s.total_warn,
                s.total_skip,
                s.total_error,
                f"{s.pass_rate:.1f}",
                f"{s.duration_ms:.2f}",
                _sanitize_csv_value(s.started_at),
                _sanitize_csv_value(s.completed_at),
                _serialize_measured_values(best_mv),
            ]
        )

    return output.getvalue()
