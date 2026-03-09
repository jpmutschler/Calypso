"""Shared helpers and theme constants for report section renderers."""

from __future__ import annotations

import html
import math

from calypso.workflows.models import RecipeResult, RecipeSummary
from calypso.workflows.report_charts import metric_card, status_color

# ---------------------------------------------------------------------------
# Theme constants (matching report_charts)
# ---------------------------------------------------------------------------
BG_CARD = "#1c2128"
BORDER = "#30363d"
TEXT_PRIMARY = "#e6edf3"
TEXT_SECONDARY = "#8b949e"
TEXT_MUTED = "#484f58"
CYAN = "#00d4ff"
GREEN = "#3fb950"
YELLOW = "#d29922"
RED = "#f85149"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def safe_int(value: object) -> int:
    """Safely convert a value to int, handling floats from JSON round-tripping."""
    try:
        return int(float(str(value)))
    except (ValueError, TypeError):
        return 0


def criteria_box(lines: list[str]) -> str:
    """Render a subtle Test Criteria info box."""
    body = "".join(
        f'<div style="margin:2px 0; color:{TEXT_SECONDARY}; font-size:12px;">'
        f"{html.escape(line)}</div>"
        for line in lines
    )
    return (
        f'<div style="margin:12px 0; padding:10px 14px; background:{BG_CARD}; '
        f"border:1px solid {BORDER}; border-left:3px solid {CYAN}; "
        f'border-radius:4px;">'
        f'<div style="font-size:12px; font-weight:600; color:{CYAN}; '
        f'margin-bottom:4px;">Test Criteria</div>'
        f"{body}</div>"
    )


def summary_metrics(summary: RecipeSummary) -> str:
    """Common pass/fail/warn metric cards row."""
    return (
        f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
        f"{metric_card('Pass', str(summary.total_pass), GREEN)}"
        f"{metric_card('Fail', str(summary.total_fail), RED)}"
        f"{metric_card('Warn', str(summary.total_warn), YELLOW)}"
        f"{metric_card('Overall', summary.status.value.upper(), status_color(summary.status.value))}"
        f"</div>"
    )


def find_step_with_key(steps: list[RecipeResult], key: str) -> RecipeResult | None:
    """Find the last step whose measured_values contains *key*."""
    for step in reversed(steps):
        if key in step.measured_values:
            return step
    return None


def format_ber(value: float) -> str:
    """Format a BER value in scientific notation."""
    if value == 0:
        return "0"
    return f"{value:.2e}"


def ber_confidence_interval(
    error_count: int,
    estimated_ber: float,
    bits_tested: float = 0.0,
) -> str | None:
    """Compute 95% CI for BER and return formatted string, or None.

    When *error_count* is 0 and *bits_tested* > 0, returns a rule-of-three
    upper bound ``< 3/bits_tested`` (95% confidence).
    """
    if error_count == 0 and bits_tested > 0:
        upper = 3.0 / bits_tested
        return f"< {format_ber(upper)}"
    if error_count <= 0 or estimated_ber <= 0:
        return None
    computed_bits = error_count / estimated_ber
    lo_count = max(0.0, error_count - 1.96 * math.sqrt(error_count))
    hi_count = error_count + 1.96 * math.sqrt(error_count)
    lo_ber = lo_count / computed_bits if computed_bits > 0 else 0.0
    hi_ber = hi_count / computed_bits if computed_bits > 0 else 0.0
    return f"[{format_ber(lo_ber)}, {format_ber(hi_ber)}]"


def color_for_status(status_str: str) -> str:
    """Return text color for a lane status string."""
    s = status_str.lower()
    if s in ("fail", "no_sync"):
        return RED
    if s in ("warn", "marginal", "errors_detected"):
        return YELLOW
    if s == "pass":
        return GREEN
    return TEXT_PRIMARY


# ---------------------------------------------------------------------------
# Measured values rendering helpers
# ---------------------------------------------------------------------------


def render_value_cell(value: object, depth: int = 0) -> str:
    """Render a single value as an HTML string, handling nested structures."""
    if depth > 5:
        return html.escape(str(value))
    if isinstance(value, dict):
        return _render_nested_dict(value, depth + 1)
    if isinstance(value, list):
        return _render_nested_list(value, depth + 1)
    if isinstance(value, bool):
        color = GREEN if value else RED
        label = "True" if value else "False"
        return f'<span style="color:{color}; font-weight:600;">{label}</span>'
    if isinstance(value, float):
        if abs(value) < 0.001 and value != 0:
            return html.escape(f"{value:.2e}")
        return html.escape(f"{value:.4f}".rstrip("0").rstrip("."))
    return html.escape(str(value))


def _render_nested_dict(d: dict[str, object], depth: int = 0) -> str:
    """Render a dict as a compact inline sub-table."""
    rows: list[str] = []
    for k, v in d.items():
        rows.append(
            f'<tr><td style="padding:2px 6px; color:{TEXT_SECONDARY}; '
            f'font-size:11px; vertical-align:top; white-space:nowrap;">'
            f"{html.escape(str(k))}</td>"
            f'<td style="padding:2px 6px; color:{TEXT_PRIMARY}; '
            f'font-size:11px;">{render_value_cell(v, depth)}</td></tr>'
        )
    return (
        f'<table style="border-collapse:collapse; background:{BG_CARD}; '
        f'border:1px solid {BORDER}; border-radius:4px; margin:2px 0;">'
        f"{''.join(rows)}</table>"
    )


def _render_nested_list(items: list[object], depth: int = 0) -> str:
    """Render a list. If items are dicts, render as a sub-table with columns."""
    if not items:
        return f'<span style="color:{TEXT_MUTED};">[]</span>'

    if all(isinstance(item, dict) for item in items):
        dict_items: list[dict[str, object]] = items  # type: ignore[assignment]
        all_keys: list[str] = []
        for item in dict_items:
            for k in item:
                if k not in all_keys:
                    all_keys.append(k)

        header_cells = "".join(
            f'<th style="text-align:left; padding:3px 6px; color:{TEXT_SECONDARY}; '
            f'font-size:11px; font-weight:600; border-bottom:1px solid {BORDER};">'
            f"{html.escape(str(k))}</th>"
            for k in all_keys
        )
        body_rows: list[str] = []
        for item in dict_items:
            cells = "".join(
                f'<td style="padding:3px 6px; color:{TEXT_PRIMARY}; '
                f'font-size:11px; border-bottom:1px solid {BORDER};">'
                f"{render_value_cell(item.get(k, ''), depth)}</td>"
                for k in all_keys
            )
            body_rows.append(f"<tr>{cells}</tr>")

        return (
            f'<table style="border-collapse:collapse; background:{BG_CARD}; '
            f"border:1px solid {BORDER}; border-radius:4px; "
            f'margin:4px 0; width:100%;">'
            f"<thead><tr>{header_cells}</tr></thead>"
            f"<tbody>{''.join(body_rows)}</tbody></table>"
        )

    formatted = ", ".join(html.escape(str(item)) for item in items[:20])
    if len(items) > 20:
        formatted += f" ... ({len(items)} total)"
    return f'<span style="color:{TEXT_PRIMARY}; font-size:12px;">[{formatted}]</span>'


def render_measured_values_table(values: dict[str, object]) -> str:
    """Render a key-value HTML table from measured_values dict."""
    if not values:
        return ""

    rows: list[str] = []
    for key, value in values.items():
        rows.append(
            f'<tr><td style="padding:4px 10px; color:{TEXT_SECONDARY}; '
            f"font-size:12px; vertical-align:top; white-space:nowrap; "
            f'border-bottom:1px solid {BORDER}; font-weight:500;">'
            f"{html.escape(str(key))}</td>"
            f'<td style="padding:4px 10px; color:{TEXT_PRIMARY}; '
            f'font-size:12px; border-bottom:1px solid {BORDER};">'
            f"{render_value_cell(value)}</td></tr>"
        )

    return (
        f'<table style="width:100%; border-collapse:collapse; '
        f"background:{BG_CARD}; border:1px solid {BORDER}; "
        f'border-radius:6px; overflow:hidden; margin:6px 0;">'
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def render_extra_measured_values(
    summary: RecipeSummary,
    rendered_keys: frozenset[str],
) -> str:
    """Render a catch-all section for measured_values keys not handled by a specialized renderer.

    Uses a collapsible ``<details>`` element to avoid visual clutter.
    """
    parts: list[str] = []
    for step in summary.steps:
        extra = {k: v for k, v in step.measured_values.items() if k not in rendered_keys}
        if not extra:
            continue
        step_label = html.escape(step.step_name)
        step_hdr = (
            f'<div style="font-size:13px; font-weight:600; color:{CYAN}; '
            f'margin:10px 0 4px 0;">{step_label}</div>'
        )
        parts.append(f"{step_hdr}{render_measured_values_table(extra)}")

    if not parts:
        return ""
    return (
        f'<details style="margin:16px 0;">'
        f'<summary style="color:{TEXT_SECONDARY}; cursor:pointer; font-size:13px; '
        f'font-weight:600; margin-bottom:8px;">Additional Measurements</summary>'
        f"{''.join(parts)}</details>"
    )
