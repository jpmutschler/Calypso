"""Run-to-run comparison report generator.

Produces a self-contained HTML report comparing two sets of recipe results
(baseline vs current) with color-coded deltas for key metrics.
"""

from __future__ import annotations

import html as html_mod

from calypso.workflows.models import RecipeSummary, StepStatus
from calypso.workflows.report_charts import (
    metric_card,
    results_table,
    section_header,
    status_badge,
)
from calypso.workflows.report_sections_helpers import (
    CYAN,
    GREEN,
    RED,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    format_ber,
)
from calypso.workflows.thresholds import NEUTRAL_METRIC_KEYS
from calypso.workflows.workflow_report import format_duration, wrap_html


# ---------------------------------------------------------------------------
# Key metric extraction
# ---------------------------------------------------------------------------

_METRIC_KEYS = [
    ("total_errors", "Total Errors", True),  # (key, label, lower_is_better)
    ("estimated_ber", "Estimated BER", True),
    ("bits_tested", "Bits Tested", False),
    ("utilization", "Utilization", False),
    ("flits_tracked", "Flits Tracked", False),
    # Eye scan metrics
    ("eye_width_ui", "Eye Width (UI)", False),
    ("eye_height_mv", "Eye Height (mV)", False),
    # Error recovery metrics
    ("clean_count", "Clean Recoveries", False),
    ("degraded_count", "Degraded Recoveries", True),
    ("transient_error_count", "Transient Errors", True),
    # FBER metrics
    ("fber_total", "FBER Total", True),
    # SerDes metrics
    ("lanes_with_errors", "Lanes with Errors", True),
    # FEC analysis metrics
    ("fec_correctable_total", "FEC Correctable", True),
    ("fec_uncorrectable_total", "FEC Uncorrectable", True),
    ("fec_correction_rate", "FEC Rate (/s)", True),
    ("fec_margin_ratio", "FEC Margin Ratio", False),  # higher is better
]

# Keys that are identifiers/enums rather than comparable numeric metrics
_IDENTIFIER_KEYS = frozenset(
    {
        "port_number",
        "lane",
        "attempt",
        "original_speed_code",
        "error_type",
        "cap_offset",
        "first_error_pointer",
        "ltssm_state",
    }
)

_SKIP_KEYS = _IDENTIFIER_KEYS | NEUTRAL_METRIC_KEYS


def _extract_key_metrics(summary: RecipeSummary) -> dict[str, float]:
    """Extract key numeric metrics from ALL steps' measured_values.

    Walks all steps (not just the richest one) to capture metrics
    spread across different steps within a recipe.
    """
    metrics: dict[str, float] = {}

    # Walk all steps to find scalar metrics
    for step in summary.steps:
        mv = step.measured_values or {}
        for key, _label, _lower in _METRIC_KEYS:
            if key in metrics:
                continue
            val = mv.get(key)
            if val is not None:
                try:
                    metrics[key] = float(val)
                except (ValueError, TypeError):
                    pass

    # Auto-discover additional numeric metrics not in _METRIC_KEYS
    for step in summary.steps:
        mv = step.measured_values or {}
        for key, val in mv.items():
            if key in metrics or key in _SKIP_KEYS:
                continue
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                metrics[key] = float(val)

    # Aggregate worst-lane BER from any step with a lanes list
    worst_ber = 0.0
    for step in summary.steps:
        mv = step.measured_values or {}
        lanes = mv.get("lanes", [])
        if isinstance(lanes, list):
            for lane in lanes:
                if isinstance(lane, dict):
                    try:
                        ber = float(lane.get("estimated_ber", 0))
                    except (ValueError, TypeError):
                        continue
                    if ber > worst_ber:
                        worst_ber = ber
    if worst_ber > 0:
        metrics["worst_lane_ber"] = worst_ber

    # Aggregate worst eye width/height across per-lane steps
    min_eye_width: float | None = None
    min_eye_height: float | None = None
    for step in summary.steps:
        mv = step.measured_values or {}
        ew = mv.get("eye_width_ui")
        eh = mv.get("eye_height_mv")
        if ew is not None:
            try:
                ew_f = float(ew)
                if min_eye_width is None or ew_f < min_eye_width:
                    min_eye_width = ew_f
            except (ValueError, TypeError):
                pass
        if eh is not None:
            try:
                eh_f = float(eh)
                if min_eye_height is None or eh_f < min_eye_height:
                    min_eye_height = eh_f
            except (ValueError, TypeError):
                pass
    if min_eye_width is not None:
        metrics.setdefault("worst_eye_width", min_eye_width)
    if min_eye_height is not None:
        metrics.setdefault("worst_eye_height", min_eye_height)

    # Sum recovery_delta across attempt steps
    total_recovery_delta = 0
    has_recovery = False
    for step in summary.steps:
        mv = step.measured_values or {}
        rd = mv.get("recovery_delta")
        if rd is not None:
            try:
                total_recovery_delta += int(float(str(rd)))
                has_recovery = True
            except (ValueError, TypeError):
                pass
    if has_recovery:
        metrics["total_recovery_delta"] = float(total_recovery_delta)

    return metrics


# ---------------------------------------------------------------------------
# Per-lane metric extraction
# ---------------------------------------------------------------------------


def _extract_lane_metrics(
    summary: RecipeSummary,
) -> dict[int, dict[str, float]]:
    """Extract per-lane metrics from steps with 'lanes' lists or lane fields."""
    lane_data: dict[int, dict[str, float]] = {}
    for step in summary.steps:
        mv = step.measured_values or {}
        lanes = mv.get("lanes", [])
        if isinstance(lanes, list):
            for lane_info in lanes:
                if not isinstance(lane_info, dict):
                    continue
                lane_idx = lane_info.get("lane", len(lane_data))
                try:
                    lane_num = int(lane_idx)
                except (ValueError, TypeError):
                    continue
                entry = lane_data.setdefault(lane_num, {})
                for k in ("estimated_ber", "error_count", "utp_error_count"):
                    v = lane_info.get(k)
                    if v is not None:
                        try:
                            entry[k] = float(v)
                        except (ValueError, TypeError):
                            pass
        # Also extract per-lane eye data from eye scan steps
        ew = mv.get("eye_width_ui")
        eh = mv.get("eye_height_mv")
        lane_val = step.lane if step.lane is not None else mv.get("lane")
        if lane_val is not None and (ew is not None or eh is not None):
            try:
                ln = int(lane_val)
            except (ValueError, TypeError):
                continue
            entry = lane_data.setdefault(ln, {})
            if ew is not None:
                try:
                    entry["eye_width_ui"] = float(ew)
                except (ValueError, TypeError):
                    pass
            if eh is not None:
                try:
                    entry["eye_height_mv"] = float(eh)
                except (ValueError, TypeError):
                    pass
    return lane_data


# ---------------------------------------------------------------------------
# Delta formatting
# ---------------------------------------------------------------------------


def _delta_color(delta: float, lower_is_better: bool) -> str:
    """Return color for a metric delta."""
    if delta == 0:
        return TEXT_MUTED
    improved = (delta < 0) if lower_is_better else (delta > 0)
    return GREEN if improved else RED


def _format_metric_value(key: str, value: float) -> str:
    """Format a metric value for display."""
    if "ber" in key:
        return format_ber(value)
    if "utilization" in key:
        return f"{value * 100:.1f}%"
    if value >= 1e9:
        return f"{value:.2e}"
    if isinstance(value, float) and value != int(value):
        return f"{value:.4g}"
    return str(int(value))


def _format_delta(key: str, delta: float) -> str:
    """Format a delta value with sign."""
    sign = "+" if delta > 0 else ""
    if "ber" in key:
        return f"{sign}{format_ber(delta)}"
    if abs(delta) >= 1e6:
        return f"{sign}{delta:.2e}"
    if isinstance(delta, float) and delta != int(delta):
        return f"{sign}{delta:.4g}"
    return f"{sign}{int(delta)}"


# ---------------------------------------------------------------------------
# Comparison report
# ---------------------------------------------------------------------------


def generate_comparison_report(
    baseline: list[RecipeSummary],
    current: list[RecipeSummary],
    title: str = "Comparison Report",
    device_id: str = "",
) -> str:
    """Generate a side-by-side comparison HTML report.

    Args:
        baseline: Recipe summaries from the baseline run.
        current: Recipe summaries from the current run.
        title: Report title.
        device_id: Device identifier.

    Returns:
        Complete HTML string.
    """
    baseline_map = {s.recipe_id: s for s in baseline}
    current_map = {s.recipe_id: s for s in current}
    all_ids = list(dict.fromkeys([s.recipe_id for s in baseline] + [s.recipe_id for s in current]))

    # Aggregate stats
    improved = 0
    regressed = 0
    unchanged = 0

    comparison_rows: list[str] = []
    detail_sections: list[str] = []

    for recipe_id in all_ids:
        base = baseline_map.get(recipe_id)
        curr = current_map.get(recipe_id)

        if base is not None and curr is not None:
            # Matched recipe — compare
            status_change = _status_delta(base.status, curr.status)
            if status_change == "improved":
                improved += 1
            elif status_change == "regressed":
                regressed += 1
            else:
                unchanged += 1

            name = html_mod.escape(curr.recipe_name)
            base_dur_ms = max(base.duration_ms, 1)
            dur_delta_pct = (curr.duration_ms - base.duration_ms) / base_dur_ms * 100
            dur_color = TEXT_SECONDARY
            if abs(dur_delta_pct) > 20:
                dur_color = GREEN if dur_delta_pct < 0 else RED
            base_badge = status_badge(base.status.value)
            curr_badge = status_badge(curr.status.value)
            base_dur = format_duration(base.duration_ms)
            curr_dur = format_duration(curr.duration_ms)
            comparison_rows.append(
                f"<tr>"
                f'<td style="padding:8px 12px; border-bottom:1px solid #30363d; '
                f'color:{TEXT_PRIMARY}; font-size:13px;">{name}</td>'
                f'<td style="padding:8px 12px; border-bottom:1px solid #30363d;">'
                f"{base_badge}</td>"
                f'<td style="padding:8px 12px; border-bottom:1px solid #30363d;">'
                f"{curr_badge}</td>"
                f'<td style="padding:8px 12px; border-bottom:1px solid #30363d; '
                f'color:{TEXT_SECONDARY}; font-size:13px; text-align:right;">'
                f"{base_dur}</td>"
                f'<td style="padding:8px 12px; border-bottom:1px solid #30363d; '
                f'color:{dur_color}; font-size:13px; text-align:right;">'
                f"{curr_dur}</td>"
                f"</tr>"
            )

            detail = _render_recipe_comparison(base, curr)
            if detail:
                detail_sections.append(detail)

        elif curr is not None:
            # New recipe
            name = html_mod.escape(curr.recipe_name)
            comparison_rows.append(
                f"<tr>"
                f'<td style="padding:8px 12px; border-bottom:1px solid #30363d; '
                f'color:{TEXT_PRIMARY}; font-size:13px;">{name}</td>'
                f'<td style="padding:8px 12px; border-bottom:1px solid #30363d; '
                f'color:{TEXT_MUTED}; font-size:12px;">—</td>'
                f'<td style="padding:8px 12px; border-bottom:1px solid #30363d;">'
                f"{status_badge(curr.status.value)}</td>"
                f'<td style="padding:8px 12px; border-bottom:1px solid #30363d; '
                f'color:{TEXT_MUTED};">—</td>'
                f'<td style="padding:8px 12px; border-bottom:1px solid #30363d; '
                f'color:{TEXT_SECONDARY}; font-size:13px; text-align:right;">'
                f"{format_duration(curr.duration_ms)}</td>"
                f"</tr>"
            )

        elif base is not None:
            # Removed recipe
            name = html_mod.escape(base.recipe_name)
            comparison_rows.append(
                f"<tr>"
                f'<td style="padding:8px 12px; border-bottom:1px solid #30363d; '
                f'color:{TEXT_MUTED}; font-size:13px;">{name}</td>'
                f'<td style="padding:8px 12px; border-bottom:1px solid #30363d;">'
                f"{status_badge(base.status.value)}</td>"
                f'<td style="padding:8px 12px; border-bottom:1px solid #30363d; '
                f'color:{TEXT_MUTED}; font-size:12px;">REMOVED</td>'
                f'<td style="padding:8px 12px; border-bottom:1px solid #30363d; '
                f'color:{TEXT_SECONDARY}; font-size:13px; text-align:right;">'
                f"{format_duration(base.duration_ms)}</td>"
                f'<td style="padding:8px 12px; border-bottom:1px solid #30363d; '
                f'color:{TEXT_MUTED};">—</td>'
                f"</tr>"
            )

    # Header
    device_line = ""
    if device_id:
        device_line = (
            f'<div style="color:{TEXT_SECONDARY}; font-size:14px; margin-top:8px;">'
            f"Device: {html_mod.escape(device_id)}</div>"
        )
    header_html = (
        f'<div style="text-align:center; padding:32px 0;">'
        f'<h1 style="color:#00d4ff; font-size:28px; margin:0; '
        f'letter-spacing:0.1em;">CALYPSO</h1>'
        f'<h2 style="color:{TEXT_PRIMARY}; font-size:22px; margin-top:16px;">'
        f"{html_mod.escape(title)}</h2>"
        f"{device_line}"
        f"</div>"
    )

    # Summary metrics
    total = len(all_ids)
    metrics_html = (
        f'<div style="display:flex; flex-wrap:wrap; justify-content:center; '
        f'gap:8px; margin:16px 0;">'
        f"{metric_card('Total Recipes', str(total), CYAN)}"
        f"{metric_card('Improved', str(improved), GREEN)}"
        f"{metric_card('Regressed', str(regressed), RED if regressed > 0 else TEXT_MUTED)}"
        f"{metric_card('Unchanged', str(unchanged), TEXT_SECONDARY)}"
        f"</div>"
    )

    # Comparison table
    comp_header = section_header("Recipe Comparison", "Baseline vs Current")
    comp_table = (
        f'<table style="width:100%; border-collapse:collapse; '
        f'background:#1c2128; border-radius:8px; overflow:hidden;">'
        f"<thead><tr>"
        f'<th style="text-align:left; padding:8px 12px; color:{TEXT_SECONDARY}; '
        f'font-size:12px; border-bottom:1px solid #30363d;">Recipe</th>'
        f'<th style="text-align:left; padding:8px 12px; color:{TEXT_SECONDARY}; '
        f'font-size:12px; border-bottom:1px solid #30363d;">Baseline</th>'
        f'<th style="text-align:left; padding:8px 12px; color:{TEXT_SECONDARY}; '
        f'font-size:12px; border-bottom:1px solid #30363d;">Current</th>'
        f'<th style="text-align:right; padding:8px 12px; color:{TEXT_SECONDARY}; '
        f'font-size:12px; border-bottom:1px solid #30363d;">Base Duration</th>'
        f'<th style="text-align:right; padding:8px 12px; color:{TEXT_SECONDARY}; '
        f'font-size:12px; border-bottom:1px solid #30363d;">Curr Duration</th>'
        f"</tr></thead>"
        f"<tbody>{''.join(comparison_rows)}</tbody></table>"
    )

    body = f"{header_html}{metrics_html}{comp_header}{comp_table}{''.join(detail_sections)}"

    return wrap_html(title, body)


def _status_delta(base: StepStatus, curr: StepStatus) -> str:
    """Classify a status change as improved, regressed, or unchanged."""
    rank = {
        StepStatus.PASS: 3,
        StepStatus.WARN: 2,
        StepStatus.SKIP: 1,
        StepStatus.FAIL: 0,
        StepStatus.ERROR: 0,
        StepStatus.PENDING: 1,
        StepStatus.RUNNING: 1,
    }
    base_rank = rank.get(base, 1)
    curr_rank = rank.get(curr, 1)
    if curr_rank > base_rank:
        return "improved"
    if curr_rank < base_rank:
        return "regressed"
    return "unchanged"


def _render_recipe_comparison(
    base: RecipeSummary,
    curr: RecipeSummary,
) -> str:
    """Render a detailed metric comparison for a matched recipe pair."""
    base_metrics = _extract_key_metrics(base)
    curr_metrics = _extract_key_metrics(curr)

    all_metric_keys = list(dict.fromkeys(list(base_metrics.keys()) + list(curr_metrics.keys())))

    if not all_metric_keys:
        return ""

    # --- Parameter differences warning ---
    param_warning = ""
    if base.parameters != curr.parameters:
        changed: list[str] = []
        all_param_keys = sorted(set(list(base.parameters.keys()) + list(curr.parameters.keys())))
        for k in all_param_keys:
            bv = base.parameters.get(k)
            cv = curr.parameters.get(k)
            if bv != cv:
                changed.append(f"{k}: {bv} \u2192 {cv}")
        if changed:
            changes_html = ", ".join(html_mod.escape(c) for c in changed)
            param_warning = (
                '<div style="margin:12px 0; padding:10px 14px; background:#1c2128; '
                "border:1px solid #30363d; border-left:3px solid #d29922; "
                'border-radius:4px;">'
                '<div style="font-size:12px; font-weight:600; color:#d29922; '
                'margin-bottom:4px;">Parameter Differences</div>'
                f'<div style="font-size:12px; color:#8b949e;">{changes_html}</div>'
                "</div>"
            )

    label_map: dict[str, str] = {k: label for k, label, _ in _METRIC_KEYS}
    label_map["worst_lane_ber"] = "Worst Lane BER"
    label_map["worst_eye_width"] = "Worst Eye Width (UI)"
    label_map["worst_eye_height"] = "Worst Eye Height (mV)"
    label_map["total_recovery_delta"] = "Total Recovery Count"
    lower_map: dict[str, bool] = {k: lower for k, _, lower in _METRIC_KEYS}
    lower_map["worst_lane_ber"] = True
    lower_map["worst_eye_width"] = False  # wider is better
    lower_map["worst_eye_height"] = False  # taller is better
    lower_map["total_recovery_delta"] = True  # fewer recoveries is better

    rows: list[list[str]] = []
    for key in all_metric_keys:
        label = label_map.get(key, key.replace("_", " ").title())
        base_val = base_metrics.get(key)
        curr_val = curr_metrics.get(key)

        base_str = _format_metric_value(key, base_val) if base_val is not None else "\u2014"
        curr_str = _format_metric_value(key, curr_val) if curr_val is not None else "\u2014"

        delta_str = ""
        if base_val is not None and curr_val is not None:
            delta = curr_val - base_val
            if delta != 0:
                lower = lower_map.get(key)
                d_str = _format_delta(key, delta)
                if lower is None:
                    # Auto-discovered metric: show delta without direction color
                    delta_str = f'<span style="color:{TEXT_SECONDARY};">{d_str}</span>'
                else:
                    color = _delta_color(delta, lower)
                    delta_str = f'<span style="color:{color}; font-weight:600;">{d_str}</span>'

        rows.append([label, base_str, curr_str, delta_str])

    header = section_header(
        curr.recipe_name,
        f"Status: {base.status.value} \u2192 {curr.status.value}",
    )
    table = results_table(
        ["Metric", "Baseline", "Current", "Delta"],
        rows,
    )

    # --- Per-lane regression table ---
    lane_html = ""
    base_lanes = _extract_lane_metrics(base)
    curr_lanes = _extract_lane_metrics(curr)
    common_lanes = sorted(set(base_lanes) & set(curr_lanes))
    if common_lanes:
        lane_rows: list[list[str]] = []
        lane_metric_keys = [
            "estimated_ber",
            "eye_width_ui",
            "eye_height_mv",
            "error_count",
        ]
        lane_labels = {
            "estimated_ber": "BER",
            "eye_width_ui": "Eye Width",
            "eye_height_mv": "Eye Height",
            "error_count": "Errors",
        }
        lane_lower = {
            "estimated_ber": True,
            "eye_width_ui": False,
            "eye_height_mv": False,
            "error_count": True,
        }
        for ln in common_lanes:
            bl = base_lanes[ln]
            cl = curr_lanes[ln]
            for mk in lane_metric_keys:
                bv = bl.get(mk)
                cv = cl.get(mk)
                if bv is None and cv is None:
                    continue
                bv_str = _format_metric_value(mk, bv) if bv is not None else "\u2014"
                cv_str = _format_metric_value(mk, cv) if cv is not None else "\u2014"
                delta_str = ""
                if bv is not None and cv is not None:
                    d = cv - bv
                    if d != 0:
                        lower = lane_lower.get(mk, True)
                        color = _delta_color(d, lower)
                        d_str = _format_delta(mk, d)
                        delta_str = f'<span style="color:{color}; font-weight:600;">{d_str}</span>'
                label = lane_labels.get(mk, mk)
                lane_rows.append([str(ln), label, bv_str, cv_str, delta_str])
        if lane_rows:
            lane_header = section_header("Per-Lane Regression", "")
            lane_table = results_table(
                ["Lane", "Metric", "Baseline", "Current", "Delta"],
                lane_rows,
            )
            lane_html = f"{lane_header}{lane_table}"

    return f"{header}{param_warning}{table}{lane_html}"
