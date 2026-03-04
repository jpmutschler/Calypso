"""Recipe-specific HTML section renderers for workflow reports.

Each function produces a self-contained HTML fragment for a recipe's
results, using the chart primitives from report_charts.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from calypso.workflows.models import RecipeSummary
from calypso.workflows.report_charts import (
    bar_chart,
    metric_card,
    results_table,
    section_header,
    status_color,
)


def render_recipe_section(summary: RecipeSummary) -> str:
    """Render a full HTML section for a recipe result.

    Dispatches to a specialized renderer if available, otherwise
    uses the generic table renderer.
    """
    renderer = _RENDERERS.get(summary.recipe_id, _render_generic)
    return renderer(summary)


def _render_generic(summary: RecipeSummary) -> str:
    """Generic recipe result renderer as a table."""
    header = section_header(
        summary.recipe_name,
        f"Category: {summary.category.value} | Duration: {summary.duration_ms:.0f}ms",
    )

    columns = ["Step", "Status", "Message", "Duration"]
    rows = [
        [
            step.step_name,
            step.status.value.upper(),
            step.message,
            f"{step.duration_ms:.0f}ms",
        ]
        for step in summary.steps
    ]
    table = results_table(columns, rows, status_column=1)

    metrics = (
        f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
        f"{metric_card('Pass', str(summary.total_pass), '#3fb950')}"
        f"{metric_card('Fail', str(summary.total_fail), '#f85149')}"
        f"{metric_card('Warn', str(summary.total_warn), '#d29922')}"
        f"{metric_card('Overall', summary.status.value.upper(), status_color(summary.status.value))}"
        f"</div>"
    )

    return f"{header}{metrics}{table}"


def _render_port_sweep(summary: RecipeSummary) -> str:
    """Specialized renderer for all_port_sweep results."""
    header = section_header("All Port Sweep", f"Duration: {summary.duration_ms:.0f}ms")

    columns = ["Port", "Status", "Link", "Speed", "Width", "Role"]
    rows: list[list[str]] = []
    for step in summary.steps:
        mv = step.measured_values
        rows.append(
            [
                str(mv.get("port_number", step.port_number or "")),
                step.status.value.upper(),
                "UP" if mv.get("is_link_up") else "DOWN",
                str(mv.get("link_speed", "")),
                f"x{mv.get('link_width', '')}" if mv.get("link_width") else "",
                str(mv.get("role", "")),
            ]
        )

    table = results_table(columns, rows, status_column=1)

    up_count = sum(1 for s in summary.steps if s.measured_values.get("is_link_up"))
    total = len(summary.steps)
    metrics = (
        f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
        f"{metric_card('Links Up', str(up_count), '#3fb950')}"
        f"{metric_card('Links Down', str(total - up_count), '#f85149' if total - up_count > 0 else '#484f58')}"
        f"{metric_card('Total Ports', str(total), '#00d4ff')}"
        f"</div>"
    )

    return f"{header}{metrics}{table}"


def _render_bandwidth(summary: RecipeSummary) -> str:
    """Specialized renderer for bandwidth_baseline results."""
    header = section_header("Bandwidth Baseline", f"Duration: {summary.duration_ms:.0f}ms")

    # Collect bandwidth data from measured values
    bw_data: list[tuple[str, float]] = []
    for step in summary.steps:
        mv = step.measured_values
        if "avg_ingress_mbps" in mv:
            port = mv.get("port_number", step.port_number or 0)
            bw_data.append((f"Port {port} In", float(mv.get("avg_ingress_mbps", 0))))
            bw_data.append((f"Port {port} Out", float(mv.get("avg_egress_mbps", 0))))

    chart = bar_chart(bw_data) if bw_data else ""
    table = _render_generic(summary)

    return f"{header}{chart}{table}"


def _render_ber(summary: RecipeSummary) -> str:
    """Specialized renderer for BER results (ber_soak, multi_speed_ber)."""
    header = section_header(
        summary.recipe_name,
        f"Duration: {summary.duration_ms:.0f}ms",
    )

    # Extract BER per lane
    ber_data: list[tuple[str, float]] = []
    for step in summary.steps:
        mv = step.measured_values
        if "ber" in mv:
            lane = mv.get("lane", step.lane or 0)
            ber_val = float(mv.get("ber", 0))
            # Use log scale for display (show as -log10)
            display_val = -math.log10(ber_val) if ber_val > 0 else 15
            ber_data.append((f"Lane {lane}", display_val))

    chart = ""
    if ber_data:
        chart = bar_chart(ber_data, max_value=15, bar_color="#3fb950", height_px=16)

    generic = _render_generic(summary)
    return f"{header}{chart}{generic}"


def _render_eye_scan(summary: RecipeSummary) -> str:
    """Specialized renderer for eye_quick_scan results."""
    header = section_header("Eye Quick Scan", f"Duration: {summary.duration_ms:.0f}ms")

    columns = ["Lane", "Status", "Margin", "Steps"]
    rows: list[list[str]] = []
    for step in summary.steps:
        mv = step.measured_values
        rows.append(
            [
                str(mv.get("lane", step.lane or "")),
                step.status.value.upper(),
                str(mv.get("margin", "")),
                str(mv.get("total_steps", "")),
            ]
        )

    table = results_table(columns, rows, status_column=1)
    return f"{header}{table}"


# Map recipe IDs to specialized renderers
_RENDERERS: dict[str, Callable[[RecipeSummary], str]] = {
    "all_port_sweep": _render_port_sweep,
    "bandwidth_baseline": _render_bandwidth,
    "ber_soak": _render_ber,
    "multi_speed_ber": _render_ber,
    "eye_quick_scan": _render_eye_scan,
}
