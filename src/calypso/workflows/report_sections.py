"""Recipe-specific HTML section renderers for workflow reports.

Each function produces a self-contained HTML fragment for a recipe's
results, using the chart primitives from report_charts.
"""

from __future__ import annotations

import html
from collections.abc import Callable

from calypso.workflows.models import RecipeSummary
from calypso.workflows.report_charts import (
    results_table,
    section_header,
)
from calypso.workflows.report_sections_helpers import (
    CYAN,
    TEXT_PRIMARY,
    render_measured_values_table,
    summary_metrics,
)
from calypso.workflows.report_sections_gen6 import (
    render_eye_scan,
    render_flit_perf_measurement,
    render_link_training_debug,
    render_pam4_eye_sweep,
    render_phy_64gt_audit,
)
from calypso.workflows.report_sections_recipes import (
    render_bandwidth,
    render_ber,
    render_fber_measurement,
    render_port_sweep,
)


def render_recipe_section(summary: RecipeSummary) -> str:
    """Render a full HTML section for a recipe result.

    Dispatches to a specialized renderer if available, otherwise
    uses the generic table renderer.
    """
    renderer = _RENDERERS.get(summary.recipe_id, _render_generic)
    return renderer(summary)


def _format_timestamp(ts: str) -> str:
    """Format an ISO timestamp to HH:MM:SS for display."""
    if not ts:
        return ""
    try:
        if "T" in ts:
            time_part = ts.split("T")[1]
            time_part = time_part.split("+")[0].split("Z")[0]
            if "." in time_part:
                time_part = time_part.split(".")[0]
            return time_part
    except (IndexError, ValueError):
        pass
    return ts


# ---------------------------------------------------------------------------
# Generic renderer (fallback for all unregistered recipes)
# ---------------------------------------------------------------------------


def _render_generic(summary: RecipeSummary) -> str:
    """Generic recipe result renderer as a table.

    Shows step overview AND detailed measured_values for every step,
    so no measurement data is silently discarded.
    """
    header = section_header(
        summary.recipe_name,
        f"Category: {summary.category.value} | Duration: {summary.duration_ms:.0f}ms",
    )

    columns = ["Step", "Status", "Message", "Duration", "Time"]
    rows = [
        [
            step.step_name,
            step.status.value.upper(),
            step.message,
            f"{step.duration_ms:.0f}ms",
            _format_timestamp(step.timestamp),
        ]
        for step in summary.steps
    ]
    table = results_table(columns, rows, status_column=1)

    metrics = summary_metrics(summary)

    # Detailed Measurements section (C-1 fix) -- render measured_values
    details_parts: list[str] = []
    for step in summary.steps:
        if not step.measured_values:
            continue
        step_label = html.escape(step.step_name)
        step_header = (
            f'<div style="font-size:13px; font-weight:600; color:{CYAN}; '
            f'margin:10px 0 4px 0;">{step_label}</div>'
        )
        mv_table = render_measured_values_table(step.measured_values)
        details_parts.append(f"{step_header}{mv_table}")

    details_section = ""
    if details_parts:
        details_header = (
            f'<div style="font-size:15px; font-weight:600; color:{TEXT_PRIMARY}; '
            f'margin:20px 0 8px 0;">Detailed Measurements</div>'
        )
        details_section = details_header + "".join(details_parts)

    return f"{header}{metrics}{table}{details_section}"


# ---------------------------------------------------------------------------
# Renderer registry
# ---------------------------------------------------------------------------

_RENDERERS: dict[str, Callable[[RecipeSummary], str]] = {
    "all_port_sweep": render_port_sweep,
    "bandwidth_baseline": render_bandwidth,
    "ber_soak": render_ber,
    "multi_speed_ber": render_ber,
    "eye_quick_scan": render_eye_scan,
    "fber_measurement": render_fber_measurement,
    "link_training_debug": render_link_training_debug,
    "phy_64gt_audit": render_phy_64gt_audit,
    "flit_perf_measurement": render_flit_perf_measurement,
    "pam4_eye_sweep": render_pam4_eye_sweep,
}
