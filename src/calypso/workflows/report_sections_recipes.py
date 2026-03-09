"""Specialized recipe HTML section renderers for workflow reports.

Each function produces a self-contained HTML fragment for a specific recipe's
results, using the chart primitives from report_charts.
"""

from __future__ import annotations

import html
import math

from calypso.workflows.models import RecipeResult, RecipeSummary
from calypso.workflows.report_charts import (
    bar_chart,
    metric_card,
    results_table,
    section_header,
    status_color,
)

# ---------------------------------------------------------------------------
# Theme constants (matching report_charts)
# ---------------------------------------------------------------------------
_BG_CARD = "#1c2128"
_BORDER = "#30363d"
_TEXT_PRIMARY = "#e6edf3"
_TEXT_SECONDARY = "#8b949e"
_TEXT_MUTED = "#484f58"
_CYAN = "#00d4ff"
_GREEN = "#3fb950"
_YELLOW = "#d29922"
_RED = "#f85149"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _safe_int(value: object) -> int:
    """Safely convert a value to int, handling floats from JSON round-tripping."""
    try:
        return int(float(str(value)))
    except (ValueError, TypeError):
        return 0


def _criteria_box(lines: list[str]) -> str:
    """Render a subtle Test Criteria info box."""
    body = "".join(
        f'<div style="margin:2px 0; color:{_TEXT_SECONDARY}; font-size:12px;">'
        f"{html.escape(line)}</div>"
        for line in lines
    )
    return (
        f'<div style="margin:12px 0; padding:10px 14px; background:{_BG_CARD}; '
        f"border-left:3px solid {_CYAN}; border-radius:4px; "
        f'border:1px solid {_BORDER};">'
        f'<div style="font-size:12px; font-weight:600; color:{_CYAN}; '
        f'margin-bottom:4px;">Test Criteria</div>'
        f"{body}</div>"
    )


def _summary_metrics(summary: RecipeSummary) -> str:
    """Common pass/fail/warn metric cards row."""
    return (
        f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
        f"{metric_card('Pass', str(summary.total_pass), _GREEN)}"
        f"{metric_card('Fail', str(summary.total_fail), _RED)}"
        f"{metric_card('Warn', str(summary.total_warn), _YELLOW)}"
        f"{metric_card('Overall', summary.status.value.upper(), status_color(summary.status.value))}"
        f"</div>"
    )


def _find_step_with_key(steps: list[RecipeResult], key: str) -> RecipeResult | None:
    """Find the last step whose measured_values contains *key*."""
    for step in reversed(steps):
        if key in step.measured_values:
            return step
    return None


def _format_ber(value: float) -> str:
    """Format a BER value in scientific notation."""
    if value == 0:
        return "0"
    return f"{value:.2e}"


def _ber_confidence_interval(error_count: int, estimated_ber: float) -> str | None:
    """Compute 95% CI for BER and return formatted string, or None."""
    if error_count <= 0 or estimated_ber <= 0:
        return None
    bits_tested = error_count / estimated_ber
    lo_count = max(0.0, error_count - 1.96 * math.sqrt(error_count))
    hi_count = error_count + 1.96 * math.sqrt(error_count)
    lo_ber = lo_count / bits_tested if bits_tested > 0 else 0.0
    hi_ber = hi_count / bits_tested if bits_tested > 0 else 0.0
    return f"[{_format_ber(lo_ber)}, {_format_ber(hi_ber)}]"


def _color_for_status(status_str: str) -> str:
    """Return text color for a lane status string."""
    s = status_str.lower()
    if s in ("fail", "no_sync"):
        return _RED
    if s in ("warn", "marginal", "errors_detected"):
        return _YELLOW
    if s == "pass":
        return _GREEN
    return _TEXT_PRIMARY


# ---------------------------------------------------------------------------
# Port Sweep
# ---------------------------------------------------------------------------


def render_port_sweep(summary: RecipeSummary) -> str:
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
        f"{metric_card('Links Up', str(up_count), _GREEN)}"
        f"{metric_card('Links Down', str(total - up_count), _RED if total - up_count > 0 else _TEXT_MUTED)}"
        f"{metric_card('Total Ports', str(total), _CYAN)}"
        f"</div>"
    )

    return f"{header}{metrics}{table}"


# ---------------------------------------------------------------------------
# BER (ber_soak + multi_speed_ber)
# ---------------------------------------------------------------------------


def render_ber(summary: RecipeSummary) -> str:
    """Specialized renderer for BER results (ber_soak, multi_speed_ber)."""
    header = section_header(summary.recipe_name, f"Duration: {summary.duration_ms:.0f}ms")

    criteria = _criteria_box(
        [
            "PASS: BER < 1e-12",
            "WARN: BER < 1e-9",
            "FAIL: BER >= 1e-9",
        ]
    )

    # Find the analysis step containing 'lanes' key
    lane_step = _find_step_with_key(summary.steps, "lanes")

    chart = ""
    lane_table = ""
    extra_metrics = ""

    if lane_step is not None:
        mv = lane_step.measured_values
        lanes = mv.get("lanes", [])
        total_errors = mv.get("total_errors", 0)
        mode = mv.get("mode", "unknown")

        extra_metrics = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{metric_card('Total Errors', str(total_errors), _RED if _safe_int(total_errors) > 0 else _GREEN)}"
            f"{metric_card('Mode', str(mode).upper(), _CYAN)}"
            f"{metric_card('Lanes', str(len(lanes)), _CYAN)}"
            f"</div>"
        )

        if isinstance(lanes, list) and lanes:
            # Build bar chart from per-lane BER
            ber_data: list[tuple[str, float]] = []
            columns = [
                "Lane",
                "Status",
                "Error Count",
                "Estimated BER",
                "95% CI",
            ]
            rows: list[list[str]] = []

            for lane_info in lanes:
                if not isinstance(lane_info, dict):
                    continue
                lane_idx = lane_info.get("lane", "?")
                error_count = int(lane_info.get("error_count", 0))
                estimated_ber = float(lane_info.get("estimated_ber", 0))
                lane_status = str(lane_info.get("status", ""))

                # Bar chart: -log10(BER) for display
                if estimated_ber > 0:
                    display_val = -math.log10(estimated_ber)
                else:
                    display_val = 15.0
                ber_data.append((f"Lane {lane_idx}", display_val))

                # Confidence interval (M-2)
                ci_str = ""
                ci = _ber_confidence_interval(error_count, estimated_ber)
                if ci is not None:
                    ci_str = f"{_format_ber(estimated_ber)} {ci}"

                rows.append(
                    [
                        str(lane_idx),
                        lane_status.upper(),
                        str(error_count),
                        _format_ber(estimated_ber),
                        ci_str,
                    ]
                )

            if ber_data:
                chart = bar_chart(ber_data, max_value=15, bar_color=_GREEN, height_px=16)
            lane_table = results_table(columns, rows, status_column=1)

    # Also handle multi_speed_ber which has per-speed steps
    speed_rows: list[list[str]] = []
    for step in summary.steps:
        mv = step.measured_values
        if "speed" in mv and "total_errors" in mv:
            speed_rows.append(
                [
                    str(mv.get("speed", "")),
                    step.status.value.upper(),
                    str(mv.get("mode", "")),
                    str(mv.get("total_errors", "")),
                    str(mv.get("actual_speed", "")),
                    f"{step.duration_ms:.0f}ms",
                ]
            )

    speed_table = ""
    if speed_rows:
        speed_table = section_header("Per-Speed Results", "") + results_table(
            ["Speed", "Status", "Mode", "Errors", "Actual Speed", "Duration"],
            speed_rows,
            status_column=1,
        )

    metrics = _summary_metrics(summary)
    return f"{header}{criteria}{metrics}{extra_metrics}{chart}{lane_table}{speed_table}"


# ---------------------------------------------------------------------------
# Eye Quick Scan
# ---------------------------------------------------------------------------


def render_eye_scan(summary: RecipeSummary) -> str:
    """Specialized renderer for eye_quick_scan results."""
    header = section_header("Eye Quick Scan", f"Duration: {summary.duration_ms:.0f}ms")

    criteria = _criteria_box(
        [
            "PASS: Eye width >= 0.15 UI",
            "WARN: Eye width >= 0.08 UI",
            "FAIL: Eye width < 0.08 UI",
        ]
    )

    columns = [
        "Lane",
        "Status",
        "Eye Width (UI)",
        "Eye Height (mV)",
        "Margin R (UI)",
        "Margin L (UI)",
    ]
    rows: list[list[str]] = []
    for step in summary.steps:
        mv = step.measured_values
        if "eye_width_ui" not in mv:
            continue
        lane = step.lane if step.lane is not None else mv.get("lane", "")
        rows.append(
            [
                str(lane),
                step.status.value.upper(),
                f"{float(mv.get('eye_width_ui', 0)):.4f}",
                f"{float(mv.get('eye_height_mv', 0)):.2f}",
                f"{float(mv.get('margin_right_ui', 0)):.4f}",
                f"{float(mv.get('margin_left_ui', 0)):.4f}",
            ]
        )

    table = results_table(columns, rows, status_column=1)
    metrics = _summary_metrics(summary)
    return f"{header}{criteria}{metrics}{table}"


# ---------------------------------------------------------------------------
# Bandwidth Baseline
# ---------------------------------------------------------------------------


def render_bandwidth(summary: RecipeSummary) -> str:
    """Specialized renderer for bandwidth_baseline results."""
    header = section_header("Bandwidth Baseline", f"Duration: {summary.duration_ms:.0f}ms")

    criteria = _criteria_box(
        [
            "WARN: Port utilization > 90%",
        ]
    )

    baseline_step = _find_step_with_key(summary.steps, "port_baselines")

    chart = ""
    port_table = ""
    if baseline_step is not None:
        mv = baseline_step.measured_values
        port_baselines = mv.get("port_baselines", {})

        if isinstance(port_baselines, dict):
            bw_data: list[tuple[str, float]] = []
            columns = [
                "Port",
                "Ingress Avg (MB/s)",
                "Egress Avg (MB/s)",
                "Ingress Max (MB/s)",
                "Utilization",
            ]
            rows: list[list[str]] = []

            for port_key, entry in sorted(port_baselines.items()):
                if not isinstance(entry, dict):
                    continue
                ingress_avg = float(entry.get("ingress_avg_bps", 0))
                egress_avg = float(entry.get("egress_avg_bps", 0))
                ingress_max = float(entry.get("ingress_max_bps", 0))
                utilization = entry.get("utilization")

                # Convert bps to MB/s
                ingress_avg_mb = ingress_avg / (1024 * 1024)
                egress_avg_mb = egress_avg / (1024 * 1024)
                ingress_max_mb = ingress_max / (1024 * 1024)

                bw_data.append((f"{port_key} In", ingress_avg_mb))
                bw_data.append((f"{port_key} Out", egress_avg_mb))

                util_str = f"{float(utilization) * 100:.1f}%" if utilization is not None else "N/A"
                rows.append(
                    [
                        port_key.replace("port_", "Port "),
                        f"{ingress_avg_mb:.2f}",
                        f"{egress_avg_mb:.2f}",
                        f"{ingress_max_mb:.2f}",
                        util_str,
                    ]
                )

            if bw_data:
                chart = bar_chart(bw_data)
            if rows:
                port_table = results_table(columns, rows)

    metrics = _summary_metrics(summary)
    return f"{header}{criteria}{metrics}{chart}{port_table}"


# ---------------------------------------------------------------------------
# FBER Measurement
# ---------------------------------------------------------------------------


def render_fber_measurement(summary: RecipeSummary) -> str:
    """Specialized renderer for fber_measurement results."""
    header = section_header("FBER Measurement", f"Duration: {summary.duration_ms:.0f}ms")

    criteria = _criteria_box(
        [
            "PASS: BER = 0 (zero errors)",
            "WARN: BER >= 1e-10",
            "FAIL: BER >= 1e-8",
        ]
    )

    lane_step = _find_step_with_key(summary.steps, "lanes")

    lane_table = ""
    extra_metrics = ""
    if lane_step is not None:
        mv = lane_step.measured_values
        lanes = mv.get("lanes", [])
        total_errors = mv.get("total_errors", 0)

        extra_metrics = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{metric_card('Total Errors', str(total_errors), _RED if _safe_int(total_errors) > 0 else _GREEN)}"
            f"{metric_card('Flit Counter', str(mv.get('flit_counter', 0)), _CYAN)}"
            f"</div>"
        )

        if isinstance(lanes, list) and lanes:
            has_ber = any(isinstance(li, dict) and "estimated_ber" in li for li in lanes)
            columns = ["Lane", "Status", "Error Count", "Error %"]
            if has_ber:
                columns.append("Est. BER")
            rows: list[list[str]] = []
            for lane_info in lanes:
                if not isinstance(lane_info, dict):
                    continue
                lane_idx = lane_info.get("lane", "?")
                error_count = lane_info.get("error_count", 0)
                error_pct = lane_info.get("error_pct")
                lane_status = str(lane_info.get("status", ""))
                row = [
                    str(lane_idx),
                    lane_status.upper(),
                    str(error_count),
                    f"{float(error_pct):.1f}%" if error_pct is not None else "0.0%",
                ]
                if has_ber:
                    ber_val = lane_info.get("estimated_ber", 0)
                    row.append(f"{float(ber_val):.2e}" if ber_val else "0")
                rows.append(row)
            lane_table = results_table(columns, rows, status_column=1)

    metrics = _summary_metrics(summary)
    return f"{header}{criteria}{metrics}{extra_metrics}{lane_table}"


# ---------------------------------------------------------------------------
# Link Training Debug
# ---------------------------------------------------------------------------


def render_link_training_debug(summary: RecipeSummary) -> str:
    """Specialized renderer for link_training_debug results."""
    header = section_header("Link Training Debug", f"Duration: {summary.duration_ms:.0f}ms")

    # LTSSM transition timeline
    transition_step = _find_step_with_key(summary.steps, "transitions")
    timeline = ""
    if transition_step is not None:
        mv = transition_step.measured_values
        transitions = mv.get("transitions", [])
        final_state = mv.get("final_state", "")

        if isinstance(transitions, list) and transitions:
            timeline_header = section_header(
                "LTSSM Transition Timeline",
                f"Final state: {final_state}",
            )
            columns = ["Time (ms)", "LTSSM State", "Recovery Count"]
            rows: list[list[str]] = []
            for t in transitions:
                if not isinstance(t, dict):
                    continue
                rows.append(
                    [
                        f"{float(t.get('elapsed_ms', 0)):.1f}",
                        str(t.get("state", "")),
                        str(t.get("recovery_count", "")),
                    ]
                )
            timeline = timeline_header + results_table(columns, rows)

    # AER results
    aer_step = _find_step_with_key(summary.steps, "uncorrectable_raw")
    aer_section = ""
    if aer_step is not None:
        mv = aer_step.measured_values
        uncorr = int(str(mv.get("uncorrectable_raw", 0)))
        corr = int(str(mv.get("correctable_raw", 0)))
        uncorr_hex = f"0x{uncorr:08X}"
        corr_hex = f"0x{corr:08X}"
        uncorr_color = _RED if uncorr != 0 else _GREEN
        corr_color = _YELLOW if corr != 0 else _GREEN
        aer_section = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{metric_card('Uncorrectable AER', uncorr_hex, uncorr_color)}"
            f"{metric_card('Correctable AER', corr_hex, corr_color)}"
            f"</div>"
        )

    # Post-retrain link status
    link_step = _find_step_with_key(summary.steps, "current_speed")
    link_section = ""
    if link_step is not None:
        mv = link_step.measured_values
        speed_val = str(mv.get("current_speed", ""))
        width_val = "x" + str(mv.get("current_width", ""))
        dll_active = mv.get("dll_link_active", False)
        dll_color = _GREEN if dll_active else _RED
        link_section = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{metric_card('Speed', speed_val, _CYAN)}"
            f"{metric_card('Width', width_val, _CYAN)}"
            f"{metric_card('DLL Active', str(dll_active), dll_color)}"
            f"</div>"
        )

    metrics = _summary_metrics(summary)
    return f"{header}{metrics}{link_section}{aer_section}{timeline}"


# ---------------------------------------------------------------------------
# PHY 64GT Audit
# ---------------------------------------------------------------------------


def render_phy_64gt_audit(summary: RecipeSummary) -> str:
    """Specialized renderer for phy_64gt_audit -- Gen6 capability checklist."""
    header = section_header("PHY 64GT Audit", f"Duration: {summary.duration_ms:.0f}ms")

    # Gather capability flags from steps
    cap_step = _find_step_with_key(summary.steps, "gen6_supported")
    link_step = _find_step_with_key(summary.steps, "is_at_64gt")
    eq_step = _find_step_with_key(summary.steps, "eq_complete")

    def _check_item(label: str, value: object) -> str:
        if value is True:
            icon_color = _GREEN
            icon = "PASS"
        elif value is False:
            icon_color = _RED
            icon = "FAIL"
        else:
            icon_color = _TEXT_MUTED
            icon = "N/A"
        return (
            f'<div style="display:flex; align-items:center; gap:8px; '
            f'padding:6px 12px; border-bottom:1px solid {_BORDER};">'
            f'<span style="color:{icon_color}; font-weight:600; '
            f'font-size:12px; min-width:40px;">{icon}</span>'
            f'<span style="color:{_TEXT_PRIMARY}; font-size:13px;">'
            f"{html.escape(label)}</span></div>"
        )

    checks: list[str] = []
    if cap_step is not None:
        mv = cap_step.measured_values
        checks.append(_check_item("Gen6 (64GT/s) Supported", mv.get("gen6_supported")))
        checks.append(_check_item("Gen5 (32GT/s) Supported", mv.get("gen5_supported")))
        checks.append(_check_item("Gen4 (16GT/s) Supported", mv.get("gen4_supported")))

    if link_step is not None:
        mv = link_step.measured_values
        checks.append(_check_item("Operating at 64GT/s", mv.get("is_at_64gt")))

    if eq_step is not None:
        mv = eq_step.measured_values
        checks.append(_check_item("64GT EQ Complete", mv.get("eq_complete")))
        checks.append(_check_item("Phase 1 OK", mv.get("phase1_ok")))
        checks.append(_check_item("Phase 2 OK", mv.get("phase2_ok")))
        checks.append(_check_item("Phase 3 OK", mv.get("phase3_ok")))
        checks.append(_check_item("Flit Mode Supported", mv.get("flit_mode_supported")))

    checklist = (
        f'<div style="background:{_BG_CARD}; border:1px solid {_BORDER}; '
        f'border-radius:8px; overflow:hidden; margin:12px 0;">'
        f"{''.join(checks)}</div>"
        if checks
        else ""
    )

    metrics = _summary_metrics(summary)
    return f"{header}{metrics}{checklist}"


# ---------------------------------------------------------------------------
# Flit Performance Measurement
# ---------------------------------------------------------------------------


def render_flit_perf_measurement(summary: RecipeSummary) -> str:
    """Specialized renderer for flit_perf_measurement results."""
    header = section_header(
        "Flit Performance Measurement",
        f"Duration: {summary.duration_ms:.0f}ms",
    )

    results_step = _find_step_with_key(summary.steps, "flits_tracked")
    flit_metrics = ""
    ltssm_table = ""

    if results_step is not None:
        mv = results_step.measured_values
        flits = mv.get("flits_tracked", 0)
        ltssm_counter = mv.get("ltssm_counter", 0)

        flit_metrics = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{metric_card('Flits Tracked', str(flits), _GREEN if _safe_int(flits) > 0 else _YELLOW)}"
            f"{metric_card('LTSSM Counter', str(ltssm_counter), _CYAN)}"
            f"</div>"
        )

        # Extract LTSSM register data
        ltssm_rows: list[list[str]] = []
        idx = 0
        while f"ltssm_{idx}_counter" in mv:
            ltssm_rows.append(
                [
                    str(idx),
                    str(mv.get(f"ltssm_{idx}_tracking_status", "")),
                    str(mv.get(f"ltssm_{idx}_counter", "")),
                    str(mv.get(f"ltssm_{idx}_tracking_count", "")),
                ]
            )
            idx += 1

        if ltssm_rows:
            ltssm_table = section_header("LTSSM Tracking Registers", "") + results_table(
                ["Index", "Tracking Status", "Counter", "Tracking Count"],
                ltssm_rows,
            )

    # Capability info
    cap_step = _find_step_with_key(summary.steps, "cap_offset")
    cap_section = ""
    if cap_step is not None:
        mv = cap_step.measured_values
        cap_hex = f"0x{int(str(mv.get('cap_offset', 0))):04X}"
        cap_section = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{metric_card('Cap Offset', cap_hex, _TEXT_SECONDARY)}"
            f"</div>"
        )

    metrics = _summary_metrics(summary)
    return f"{header}{metrics}{flit_metrics}{cap_section}{ltssm_table}"


# ---------------------------------------------------------------------------
# PAM4 Eye Sweep
# ---------------------------------------------------------------------------


def render_pam4_eye_sweep(summary: RecipeSummary) -> str:
    """Specialized renderer for pam4_eye_sweep results."""
    header = section_header("PAM4 Eye Sweep", f"Duration: {summary.duration_ms:.0f}ms")

    criteria = _criteria_box(
        [
            "PASS: Margin >= 0.10 UI",
            "WARN: Margin >= 0.05 UI",
            "FAIL: Margin < 0.05 UI",
        ]
    )

    # Per-lane eye data
    columns = [
        "Lane",
        "Status",
        "Eye Width (UI)",
        "Eye Height (mV)",
        "Margin R (UI)",
        "Margin L (UI)",
    ]
    rows: list[list[str]] = []
    for step in summary.steps:
        mv = step.measured_values
        if "eye_width_ui" not in mv:
            continue
        lane = step.lane if step.lane is not None else mv.get("lane", "")
        rows.append(
            [
                str(lane),
                step.status.value.upper(),
                f"{float(mv.get('eye_width_ui', 0)):.4f}",
                f"{float(mv.get('eye_height_mv', 0)):.2f}",
                f"{float(mv.get('margin_right_ui', 0)):.4f}",
                f"{float(mv.get('margin_left_ui', 0)):.4f}",
            ]
        )

    eye_table = results_table(columns, rows, status_column=1) if rows else ""

    # Worst margin summary from aggregate step
    agg_step = _find_step_with_key(summary.steps, "worst_lane")
    margin_section = ""
    if agg_step is not None:
        mv = agg_step.measured_values
        worst_lane = mv.get("worst_lane", -1)
        worst_margin = mv.get("worst_margin_ui", 0)
        margin_color = (
            _RED
            if float(str(worst_margin)) < 0.05
            else _YELLOW
            if float(str(worst_margin)) < 0.10
            else _GREEN
        )
        margin_section = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{metric_card('Worst Lane', str(worst_lane), margin_color)}"
            f"{metric_card('Worst Margin', f'{float(str(worst_margin)):.4f} UI', margin_color)}"
            f"</div>"
        )

    metrics = _summary_metrics(summary)
    return f"{header}{criteria}{metrics}{margin_section}{eye_table}"
