"""Specialized recipe HTML section renderers for workflow reports.

Renderers for port sweep, BER (soak + multi-speed), bandwidth baseline,
and FBER measurement. Gen6-specific renderers are in report_sections_gen6.py.
"""

from __future__ import annotations

import math

from calypso.workflows.models import RecipeSummary
from calypso.workflows.report_charts import (
    bar_chart,
    metric_card,
    results_table,
    section_header,
)
from calypso.workflows.report_sections_helpers import (
    CYAN,
    GREEN,
    RED,
    TEXT_MUTED,
    TEXT_SECONDARY,
    YELLOW,
    ber_confidence_interval,
    criteria_box,
    find_step_with_key,
    format_ber,
    render_extra_measured_values,
    safe_int,
    summary_metrics,
)


# ---------------------------------------------------------------------------
# Port Sweep
# ---------------------------------------------------------------------------


def render_port_sweep(summary: RecipeSummary) -> str:
    """Specialized renderer for all_port_sweep results.

    Reframed for endpoint validation: active downstream links to the DUT
    are shown prominently; inactive switch ports are collapsed.
    """
    header = section_header(
        "Endpoint Link Status",
        f"Duration: {summary.duration_ms:.0f}ms | "
        "Active links to your endpoint device are shown first",
    )

    columns = ["Port", "Status", "Link", "Speed", "Width", "Role", "Station"]
    downstream_rows: list[list[str]] = []
    upstream_rows: list[list[str]] = []
    down_rows: list[list[str]] = []

    for step in summary.steps:
        mv = step.measured_values
        port_num = mv.get("port_number", step.port_number or "")
        station = safe_int(port_num) // 16 if port_num != "" else ""
        row = [
            str(port_num),
            step.status.value.upper(),
            "UP" if mv.get("is_link_up") else "DOWN",
            str(mv.get("link_speed", "")),
            f"x{mv.get('link_width', '')}" if mv.get("link_width") else "",
            str(mv.get("role", "")),
            str(station),
        ]
        if not mv.get("is_link_up"):
            down_rows.append(row)
        elif str(mv.get("role", "")).lower() in ("downstream", "ds"):
            downstream_rows.append(row)
        else:
            upstream_rows.append(row)

    total = len(summary.steps)
    metrics = (
        f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
        f"{metric_card('Downstream Links', str(len(downstream_rows)), GREEN if downstream_rows else TEXT_MUTED)}"
        f"{metric_card('Upstream Links', str(len(upstream_rows)), CYAN if upstream_rows else TEXT_MUTED)}"
        f"{metric_card('Inactive Ports', str(len(down_rows)), TEXT_MUTED)}"
        f"{metric_card('Total Ports', str(total), CYAN)}"
        f"</div>"
    )

    # Single-device prominent display: if exactly 1 downstream link, highlight it
    single_device_highlight = ""
    if len(downstream_rows) == 1:
        r = downstream_rows[0]
        single_device_highlight = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{metric_card('DUT Port', r[0], GREEN)}"
            f"{metric_card('Speed', r[3], GREEN)}"
            f"{metric_card('Width', r[4], GREEN)}"
            f"</div>"
        )

    # Active downstream links table (DUT connections)
    ds_section = ""
    if downstream_rows:
        ds_header = section_header("Active Downstream Links (DUT)", "")
        ds_section = ds_header + results_table(columns, downstream_rows, status_column=1)

    # Active upstream links table
    us_section = ""
    if upstream_rows:
        us_header = section_header("Active Upstream Links", "")
        us_section = us_header + results_table(columns, upstream_rows, status_column=1)

    # Down ports in collapsible section
    down_section = ""
    if down_rows:
        down_table = results_table(columns, down_rows, status_column=1)
        down_section = (
            f'<details style="margin:12px 0;">'
            f'<summary style="color:{TEXT_SECONDARY}; cursor:pointer; '
            f'font-size:13px; font-weight:600;">Inactive Ports ({len(down_rows)})</summary>'
            f"{down_table}</details>"
        )

    _rendered = frozenset(
        {
            "port_number",
            "is_link_up",
            "link_speed",
            "link_width",
            "role",
            "degraded",
            "total_ports",
            "ports_up",
            "ports_down",
            "ports_degraded",
        }
    )
    extras = render_extra_measured_values(summary, _rendered)
    return (
        f"{header}{metrics}{single_device_highlight}{ds_section}{us_section}{down_section}{extras}"
    )


# ---------------------------------------------------------------------------
# BER (ber_soak + multi_speed_ber)
# ---------------------------------------------------------------------------


def render_ber(summary: RecipeSummary) -> str:
    """Specialized renderer for BER results (ber_soak, multi_speed_ber)."""
    header = section_header(summary.recipe_name, f"Duration: {summary.duration_ms:.0f}ms")

    criteria = criteria_box(
        [
            "PASS: BER < 1e-12",
            "WARN: BER < 1e-9",
            "FAIL: BER >= 1e-9",
            "BER measures raw bit errors via User Test Pattern (UTP)"
            " comparison or Flit BER (FBER) counters at 64GT/s.",
        ]
    )

    # Find the analysis step containing 'lanes' key
    lane_step = find_step_with_key(summary.steps, "lanes")

    chart = ""
    lane_table = ""
    extra_metrics = ""
    link_cards = ""

    if lane_step is not None:
        mv = lane_step.measured_values
        lanes = mv.get("lanes", [])
        total_errors = mv.get("total_errors", 0)
        mode = mv.get("mode", "unknown")
        link_speed = str(mv.get("link_speed", ""))
        link_width = mv.get("link_width", "")
        bits_tested_val = float(mv.get("bits_tested", 0))

        extra_metrics = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{metric_card('Total Errors', str(total_errors), RED if safe_int(total_errors) > 0 else GREEN)}"
            f"{metric_card('Mode', str(mode).upper(), CYAN)}"
            f"{metric_card('Lanes', str(len(lanes)), CYAN)}"
            f"</div>"
        )

        # Link speed/width cards (Issue #5)
        if link_speed:
            link_cards = (
                f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
                f"{metric_card('Link Speed', link_speed, CYAN)}"
                f"{metric_card('Link Width', f'x{link_width}' if link_width else 'N/A', CYAN)}"
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

                # Confidence interval with rule-of-three for zero errors
                ci_str = ""
                ci = ber_confidence_interval(
                    error_count,
                    estimated_ber,
                    bits_tested=bits_tested_val,
                )
                if ci is not None:
                    if error_count == 0:
                        ci_str = ci  # "< X" format
                    else:
                        ci_str = f"{format_ber(estimated_ber)} {ci}"

                rows.append(
                    [
                        str(lane_idx),
                        lane_status.upper(),
                        str(error_count),
                        format_ber(estimated_ber),
                        ci_str,
                    ]
                )

            if ber_data:
                chart = bar_chart(ber_data, max_value=15, bar_color=GREEN, height_px=16)
                chart += (
                    f'<div style="font-size:11px; color:{TEXT_SECONDARY}; '
                    f'margin:4px 0 8px 0;">Chart shows -log\u2081\u2080(BER). '
                    f"Value of 15 = zero errors (display floor 1e-15).</div>"
                )
            lane_table = results_table(columns, rows, status_column=1)

    # Handle multi_speed_ber per-speed steps
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

    # Handle multi_speed_ber lane_counters (Issue #1)
    lane_counter_section = ""
    if lane_step is None:
        # No 'lanes' key found — check for lane_counters from multi_speed_ber
        lc_parts: list[str] = []
        for step in summary.steps:
            mv = step.measured_values
            lane_counters = mv.get("lane_counters")
            if isinstance(lane_counters, list) and lane_counters:
                speed_label = str(mv.get("speed", step.step_name))
                lc_columns = ["Lane", "Error Count"]
                lc_rows: list[list[str]] = []
                for lane_idx, count in enumerate(lane_counters):
                    count_int = safe_int(count)
                    lc_rows.append([str(lane_idx), str(count_int)])
                if lc_rows:
                    lc_parts.append(
                        section_header(f"Lane Errors at {speed_label}", "")
                        + results_table(lc_columns, lc_rows)
                    )
        if lc_parts:
            lane_counter_section = "".join(lc_parts)

    _rendered = frozenset(
        {
            "lanes",
            "total_errors",
            "mode",
            "link_speed",
            "link_width",
            "bits_tested",
            "flit_counter",
            "all_synced",
            "speed",
            "actual_speed",
            "lane_counters",
            "lanes_tested",
        }
    )
    extras = render_extra_measured_values(summary, _rendered)
    metrics = summary_metrics(summary)
    return (
        f"{header}{criteria}{metrics}{link_cards}{extra_metrics}"
        f"{chart}{lane_table}{speed_table}{lane_counter_section}{extras}"
    )


# ---------------------------------------------------------------------------
# Bandwidth Baseline
# ---------------------------------------------------------------------------


def render_bandwidth(summary: RecipeSummary) -> str:
    """Specialized renderer for bandwidth_baseline results."""
    header = section_header("Endpoint Bandwidth Baseline", f"Duration: {summary.duration_ms:.0f}ms")

    criteria = criteria_box(
        [
            "WARN: Port utilization > 90%",
        ]
    )

    baseline_step = find_step_with_key(summary.steps, "port_baselines")

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

                # Convert bps to MB/s (SI decimal, per PCIe industry convention)
                ingress_avg_mb = ingress_avg / 1e6
                egress_avg_mb = egress_avg / 1e6
                ingress_max_mb = ingress_max / 1e6

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

    _rendered = frozenset(
        {
            "port_baselines",
            "total_ports",
            "high_utilization_ports",
            "theoretical_max_bps",
        }
    )
    extras = render_extra_measured_values(summary, _rendered)
    metrics = summary_metrics(summary)
    return f"{header}{criteria}{metrics}{chart}{port_table}{extras}"


# ---------------------------------------------------------------------------
# FBER Measurement
# ---------------------------------------------------------------------------


def render_fber_measurement(summary: RecipeSummary) -> str:
    """Specialized renderer for fber_measurement results."""
    header = section_header("FBER Measurement", f"Duration: {summary.duration_ms:.0f}ms")

    criteria = criteria_box(
        [
            "PASS: BER = 0 (zero Flit CRC errors)",
            "WARN: BER >= 1e-10",
            "FAIL: BER >= 1e-8",
            "FBER measures Flit CRC errors (Gen6 64GT/s only). Thresholds differ"
            " from raw BER because Flit CRC errors occur at the transport layer"
            " after FEC correction.",
        ]
    )

    lane_step = find_step_with_key(summary.steps, "lanes")

    lane_table = ""
    extra_metrics = ""
    context_cards = ""
    if lane_step is not None:
        mv = lane_step.measured_values
        lanes = mv.get("lanes", [])
        total_errors = mv.get("total_errors", 0)

        # Context metrics (Issue #3)
        soak_s = mv.get("soak_duration_s", 0)
        bits = mv.get("bits_tested", 0)
        link_speed = str(mv.get("link_speed", ""))
        link_width = mv.get("link_width", "")

        extra_metrics = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{metric_card('Total Errors', str(total_errors), RED if safe_int(total_errors) > 0 else GREEN)}"
            f"{metric_card('Flit Counter', str(mv.get('flit_counter', 0)), CYAN)}"
            f"</div>"
        )

        context_parts: list[str] = []
        if link_speed:
            context_parts.append(metric_card("Link Speed", link_speed, CYAN))
        if link_width:
            context_parts.append(metric_card("Link Width", f"x{link_width}", CYAN))
        if soak_s:
            context_parts.append(metric_card("Soak Duration", f"{float(soak_s):.1f}s", CYAN))
        if bits:
            context_parts.append(metric_card("Bits Tested", f"{float(bits):.2e}", CYAN))
        if context_parts:
            context_cards = (
                f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
                f"{''.join(context_parts)}</div>"
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

    _rendered = frozenset(
        {
            "lanes",
            "total_errors",
            "flit_counter",
            "soak_duration_s",
            "bits_tested",
            "link_speed",
            "link_width",
        }
    )
    extras = render_extra_measured_values(summary, _rendered)
    metrics = summary_metrics(summary)
    return f"{header}{criteria}{metrics}{extra_metrics}{context_cards}{lane_table}{extras}"


# ---------------------------------------------------------------------------
# Error Recovery Test
# ---------------------------------------------------------------------------


def render_error_recovery(summary: RecipeSummary) -> str:
    """Specialized renderer for error_recovery_test results.

    Framed for endpoint validation: tests whether the endpoint recovers
    cleanly after forced link retraining.
    """
    header = section_header(
        "Endpoint Error Recovery Test",
        f"Duration: {summary.duration_ms:.0f}ms | "
        "Verifies your endpoint recovers cleanly after forced link retraining",
    )

    criteria = criteria_box(
        [
            "PASS: All retrain cycles recover to baseline speed/width with no AER errors",
            "WARN: Correctable errors detected after retrain (transient)",
            "FAIL: Link degradation or uncorrectable errors after retrain",
        ]
    )

    # Baseline info
    baseline_step = find_step_with_key(summary.steps, "baseline_speed")
    baseline_section = ""
    if baseline_step is not None:
        mv = baseline_step.measured_values
        base_speed = str(mv.get("baseline_speed", "N/A"))
        base_width = str(mv.get("baseline_width", "N/A"))
        base_recovery = str(mv.get("baseline_recovery_count", 0))
        baseline_section = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{metric_card('Baseline Speed', base_speed, CYAN)}"
            f"{metric_card('Baseline Width', 'x' + base_width, CYAN)}"
            f"{metric_card('Initial Recoveries', base_recovery, TEXT_SECONDARY)}"
            f"</div>"
        )

    # Final assessment cards
    assessment_step = find_step_with_key(summary.steps, "total_attempts")
    assessment_section = ""
    if assessment_step is not None:
        mv = assessment_step.measured_values
        total = safe_int(mv.get("total_attempts", 0))
        clean = safe_int(mv.get("clean_count", 0))
        transient = safe_int(mv.get("transient_error_count", 0))
        degraded = safe_int(mv.get("degraded_count", 0))

        clean_color = GREEN if clean == total else YELLOW if clean > 0 else RED
        assessment_section = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{metric_card('Clean', f'{clean}/{total}', clean_color)}"
            f"{metric_card('Transient Errors', str(transient), YELLOW if transient > 0 else GREEN)}"
            f"{metric_card('Degraded', str(degraded), RED if degraded > 0 else GREEN)}"
            f"</div>"
        )

    # Per-attempt results table
    attempt_columns = [
        "Attempt",
        "Status",
        "Post Speed",
        "Post Width",
        "Recovery \u0394",
        "Uncorrectable",
        "Correctable",
    ]
    attempt_rows: list[list[str]] = []
    for step in summary.steps:
        mv = step.measured_values
        if "attempt" not in mv:
            continue
        attempt_rows.append(
            [
                str(mv.get("attempt", "")),
                step.status.value.upper(),
                str(mv.get("post_speed", "")),
                f"x{mv.get('post_width', '')}" if mv.get("post_width") else "",
                str(mv.get("recovery_delta", "")),
                "YES"
                if mv.get("has_uncorrectable")
                else "NO"
                if mv.get("has_uncorrectable") is not None
                else "",
                "YES"
                if mv.get("has_correctable")
                else "NO"
                if mv.get("has_correctable") is not None
                else "",
            ]
        )

    attempt_table = ""
    if attempt_rows:
        attempt_header = section_header("Per-Attempt Results", "")
        attempt_table = attempt_header + results_table(
            attempt_columns, attempt_rows, status_column=1
        )

    _rendered = frozenset(
        {
            "baseline_speed",
            "baseline_width",
            "baseline_recovery_count",
            "attempt",
            "post_speed",
            "post_width",
            "recovery_delta",
            "speed_degraded",
            "width_degraded",
            "has_uncorrectable",
            "has_correctable",
            "total_attempts",
            "clean_count",
            "transient_error_count",
            "degraded_count",
        }
    )
    extras = render_extra_measured_values(summary, _rendered)
    metrics = summary_metrics(summary)
    return (
        f"{header}{criteria}{metrics}{baseline_section}{assessment_section}{attempt_table}{extras}"
    )
