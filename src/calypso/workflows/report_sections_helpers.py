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
