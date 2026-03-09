"""Recipe-specific HTML section renderers for workflow reports.

Each function produces a self-contained HTML fragment for a recipe's
results, using the chart primitives from report_charts.
"""

from __future__ import annotations

import html
from collections.abc import Callable

from calypso.workflows.models import RecipeSummary
from calypso.workflows.report_charts import (
    metric_card,
    results_table,
    section_header,
    status_color,
)
from calypso.workflows.report_sections_recipes import (
    render_bandwidth,
    render_ber,
    render_eye_scan,
    render_fber_measurement,
    render_flit_perf_measurement,
    render_link_training_debug,
    render_pam4_eye_sweep,
    render_phy_64gt_audit,
    render_port_sweep,
)

# Theme colors (matching report_charts)
_BG_CARD = "#1c2128"
_BORDER = "#30363d"
_TEXT_PRIMARY = "#e6edf3"
_TEXT_SECONDARY = "#8b949e"
_TEXT_MUTED = "#484f58"
_CYAN = "#00d4ff"
_GREEN = "#3fb950"
_YELLOW = "#d29922"
_RED = "#f85149"


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
# Measured values rendering helpers (C-1 fix)
# ---------------------------------------------------------------------------


def _render_value_cell(value: object) -> str:
    """Render a single value as an HTML string, handling nested structures."""
    if isinstance(value, dict):
        return _render_nested_dict(value)
    if isinstance(value, list):
        return _render_nested_list(value)
    if isinstance(value, bool):
        color = _GREEN if value else _RED
        label = "True" if value else "False"
        return f'<span style="color:{color}; font-weight:600;">{label}</span>'
    if isinstance(value, float):
        if abs(value) < 0.001 and value != 0:
            return html.escape(f"{value:.2e}")
        return html.escape(f"{value:.4f}".rstrip("0").rstrip("."))
    return html.escape(str(value))


def _render_nested_dict(d: dict[str, object]) -> str:
    """Render a dict as a compact inline sub-table."""
    rows: list[str] = []
    for k, v in d.items():
        rows.append(
            f'<tr><td style="padding:2px 6px; color:{_TEXT_SECONDARY}; '
            f'font-size:11px; vertical-align:top; white-space:nowrap;">'
            f"{html.escape(str(k))}</td>"
            f'<td style="padding:2px 6px; color:{_TEXT_PRIMARY}; '
            f'font-size:11px;">{_render_value_cell(v)}</td></tr>'
        )
    return (
        f'<table style="border-collapse:collapse; background:{_BG_CARD}; '
        f'border:1px solid {_BORDER}; border-radius:4px; margin:2px 0;">'
        f"{''.join(rows)}</table>"
    )


def _render_nested_list(items: list[object]) -> str:
    """Render a list. If items are dicts, render as a sub-table with columns."""
    if not items:
        return f'<span style="color:{_TEXT_MUTED};">[]</span>'

    # Check if all items are dicts -- render as a proper table
    if all(isinstance(item, dict) for item in items):
        dict_items: list[dict[str, object]] = items  # type: ignore[assignment]
        all_keys: list[str] = []
        for item in dict_items:
            for k in item:
                if k not in all_keys:
                    all_keys.append(k)

        header_cells = "".join(
            f'<th style="text-align:left; padding:3px 6px; color:{_TEXT_SECONDARY}; '
            f'font-size:11px; font-weight:600; border-bottom:1px solid {_BORDER};">'
            f"{html.escape(str(k))}</th>"
            for k in all_keys
        )
        body_rows: list[str] = []
        for item in dict_items:
            cells = "".join(
                f'<td style="padding:3px 6px; color:{_TEXT_PRIMARY}; '
                f'font-size:11px; border-bottom:1px solid {_BORDER};">'
                f"{_render_value_cell(item.get(k, ''))}</td>"
                for k in all_keys
            )
            body_rows.append(f"<tr>{cells}</tr>")

        return (
            f'<table style="border-collapse:collapse; background:{_BG_CARD}; '
            f"border:1px solid {_BORDER}; border-radius:4px; "
            f'margin:4px 0; width:100%;">'
            f"<thead><tr>{header_cells}</tr></thead>"
            f"<tbody>{''.join(body_rows)}</tbody></table>"
        )

    # Simple list of scalar values
    formatted = ", ".join(html.escape(str(item)) for item in items[:20])
    if len(items) > 20:
        formatted += f" ... ({len(items)} total)"
    return f'<span style="color:{_TEXT_PRIMARY}; font-size:12px;">[{formatted}]</span>'


def _render_measured_values_table(values: dict[str, object]) -> str:
    """Render a key-value HTML table from measured_values dict."""
    if not values:
        return ""

    rows: list[str] = []
    for key, value in values.items():
        rows.append(
            f'<tr><td style="padding:4px 10px; color:{_TEXT_SECONDARY}; '
            f"font-size:12px; vertical-align:top; white-space:nowrap; "
            f'border-bottom:1px solid {_BORDER}; font-weight:500;">'
            f"{html.escape(str(key))}</td>"
            f'<td style="padding:4px 10px; color:{_TEXT_PRIMARY}; '
            f'font-size:12px; border-bottom:1px solid {_BORDER};">'
            f"{_render_value_cell(value)}</td></tr>"
        )

    return (
        f'<table style="width:100%; border-collapse:collapse; '
        f"background:{_BG_CARD}; border:1px solid {_BORDER}; "
        f'border-radius:6px; overflow:hidden; margin:6px 0;">'
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


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

    metrics = (
        f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
        f"{metric_card('Pass', str(summary.total_pass), _GREEN)}"
        f"{metric_card('Fail', str(summary.total_fail), _RED)}"
        f"{metric_card('Warn', str(summary.total_warn), _YELLOW)}"
        f"{metric_card('Overall', summary.status.value.upper(), status_color(summary.status.value))}"
        f"</div>"
    )

    # Detailed Measurements section (C-1 fix) -- render measured_values
    details_parts: list[str] = []
    for step in summary.steps:
        if not step.measured_values:
            continue
        step_label = html.escape(step.step_name)
        step_header = (
            f'<div style="font-size:13px; font-weight:600; color:{_CYAN}; '
            f'margin:10px 0 4px 0;">{step_label}</div>'
        )
        mv_table = _render_measured_values_table(step.measured_values)
        details_parts.append(f"{step_header}{mv_table}")

    details_section = ""
    if details_parts:
        details_header = (
            f'<div style="font-size:15px; font-weight:600; color:{_TEXT_PRIMARY}; '
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
