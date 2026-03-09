"""Shared helpers and theme constants for report section renderers."""

from __future__ import annotations

import html
import math

from calypso.workflows.models import RecipeResult, RecipeSummary
from calypso.workflows.report_charts import (
    BG_CARD,
    BORDER,
    CYAN,
    GREEN,
    RED,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    YELLOW,
    metric_card,
    status_color,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def safe_int(value: object) -> int:
    """Safely convert a value to int, handling floats from JSON round-tripping."""
    try:
        if isinstance(value, bool):
            return int(value)
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
# PCIe AER error bit definitions (PCIe 6.1 §7.8.4)
# ---------------------------------------------------------------------------

_AER_UNCORRECTABLE_BITS: tuple[tuple[int, str], ...] = (
    (4, "Data Link Protocol Error"),
    (5, "Surprise Down Error"),
    (12, "Poisoned TLP Received"),
    (13, "Flow Control Protocol Error"),
    (14, "Completion Timeout"),
    (15, "Completer Abort"),
    (16, "Unexpected Completion"),
    (17, "Receiver Overflow"),
    (18, "Malformed TLP"),
    (19, "ECRC Error"),
    (20, "Unsupported Request"),
    (21, "ACS Violation"),
    (22, "Internal Error"),
    (23, "MC Blocked TLP"),
    (24, "AtomicOp Egress Blocked"),
    (25, "TLP Prefix Blocked"),
    (26, "Poisoned TLP Egress Blocked"),
)

_AER_CORRECTABLE_BITS: tuple[tuple[int, str], ...] = (
    (0, "Receiver Error"),
    (6, "Bad TLP"),
    (7, "Bad DLLP"),
    (8, "Replay Num Rollover"),
    (12, "Replay Timer Timeout"),
    (13, "Advisory Non-Fatal Error"),
    (14, "Corrected Internal Error"),
    (15, "Header Log Overflow"),
)


def decode_aer_bits(raw: int, error_type: str = "uncorrectable") -> list[str]:
    """Decode AER status register bits into named error strings.

    Args:
        raw: Raw AER status register value.
        error_type: "uncorrectable" or "correctable".

    Returns:
        List of error name strings for each set bit.
    """
    bit_defs = (
        _AER_UNCORRECTABLE_BITS if error_type == "uncorrectable"
        else _AER_CORRECTABLE_BITS
    )
    return [name for bit, name in bit_defs if raw & (1 << bit)]


def format_aer_with_decode(raw: int, error_type: str = "uncorrectable") -> str:
    """Format an AER register value as hex with decoded error names."""
    hex_str = f"0x{raw:08X}"
    if raw == 0:
        return hex_str
    names = decode_aer_bits(raw, error_type)
    if names:
        return hex_str + " (" + ", ".join(names) + ")"
    return hex_str


# ---------------------------------------------------------------------------
# Debug guidance for common failure patterns
# ---------------------------------------------------------------------------

_FAILURE_GUIDANCE: dict[str, list[str]] = {
    "aer_uncorrectable": [
        "Check physical connections and cable seating",
        "Run eye_quick_scan to verify signal margins",
        "Inspect TX EQ settings with eq_phase_audit",
    ],
    "link_degraded": [
        "Run speed_downshift_test to isolate the degraded speed tier",
        "Check EQ status with eq_phase_audit",
        "Verify endpoint supports the target link speed and width",
    ],
    "recovery_high": [
        "Check cable/connector seating on all lanes",
        "Run ber_soak for per-lane error rate analysis",
        "Monitor LTSSM transitions with ltssm_monitor",
    ],
    "ber_errors": [
        "Run eye_quick_scan on affected lanes",
        "Check TX EQ coefficients with phy_64gt_audit",
        "Consider retesting with a shorter or higher-quality cable",
    ],
    "eye_fail": [
        "Check channel loss — verify cable length and connector quality",
        "Inspect TX EQ presets negotiated with eq_phase_audit",
        "Try different receiver preset hints if supported",
    ],
    "eq_incomplete": [
        "Verify endpoint supports the target speed's EQ phases",
        "Check for firmware updates on the endpoint device",
        "Run link_training_debug for detailed LTSSM analysis",
    ],
    "flit_errors": [
        "Check for FEC uncorrectable errors in the Flit Error Log",
        "Run serdes_diagnostics for per-lane signal quality",
        "Verify endpoint Flit mode compliance at 64GT/s",
    ],
}


def failure_guidance_box(guidance_key: str) -> str:
    """Render a 'What to do next' guidance box for a failure pattern.

    Args:
        guidance_key: Key into _FAILURE_GUIDANCE dict.

    Returns:
        HTML string, or empty string if no guidance available.
    """
    steps = _FAILURE_GUIDANCE.get(guidance_key)
    if not steps:
        return ""
    bullet = "\u2022"
    items = "".join(
        f'<div style="margin:2px 0; color:{TEXT_PRIMARY}; font-size:12px;">'
        f"{bullet} {html.escape(step)}</div>"
        for step in steps
    )
    return (
        f'<div style="margin:12px 0; padding:10px 14px; background:{BG_CARD}; '
        f"border:1px solid {BORDER}; border-left:3px solid {YELLOW}; "
        f'border-radius:4px;">'
        f'<div style="font-size:12px; font-weight:600; color:{YELLOW}; '
        f'margin-bottom:4px;">What To Do Next</div>'
        f"{items}</div>"
    )


# ---------------------------------------------------------------------------
# Timestamp formatting
# ---------------------------------------------------------------------------


def format_timestamp_ms(ts: str) -> str:
    """Format an ISO timestamp to HH:MM:SS.mmm for display."""
    if not ts:
        return ""
    try:
        if "T" in ts:
            time_part = ts.split("T")[1]
            time_part = time_part.split("+")[0].split("Z")[0]
            parts = time_part.split(".")
            if len(parts) > 1:
                return parts[0] + "." + parts[1][:3]
            return parts[0]
    except (IndexError, ValueError):
        pass
    return ts


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
        if abs(value) >= 1e6:
            return html.escape(f"{value:.2e}")
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


def render_step_details(steps: list[RecipeResult]) -> str:
    """Render steps that have non-empty ``details`` fields as collapsible preformatted text.

    Useful for register dumps, stack traces, or raw diagnostic output.
    """
    parts: list[str] = []
    for step in steps:
        if not step.details:
            continue
        step_label = html.escape(step.step_name)
        parts.append(
            f'<details style="margin:8px 0;">'
            f'<summary style="color:{TEXT_SECONDARY}; cursor:pointer; '
            f'font-size:13px;">{step_label} - Details</summary>'
            f'<pre style="background:{BG_CARD}; border:1px solid {BORDER}; '
            f"border-radius:4px; padding:12px; font-size:12px; "
            f'color:{TEXT_PRIMARY}; overflow-x:auto; white-space:pre-wrap;">'
            f"{html.escape(step.details)}</pre></details>"
        )
    if not parts:
        return ""
    return (
        f'<div style="margin:16px 0;">'
        f'<div style="font-size:14px; font-weight:600; color:{TEXT_PRIMARY}; '
        f'margin-bottom:8px;">Diagnostic Details</div>'
        f"{''.join(parts)}</div>"
    )
