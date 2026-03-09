"""Error, health check, debug, and speed test renderers for workflow reports.

Specialized renderers for error_aggregation_sweep, link_health_check,
speed_downshift_test, and ltssm_monitor recipes. Framed around endpoint
(DUT) validation.
"""

from __future__ import annotations

import html

from calypso.workflows.models import RecipeSummary
from calypso.workflows.report_charts import (
    metric_card,
    results_table,
    section_header,
)
from calypso.workflows.recipes.ltssm_monitor import (
    _RECOVERY_WARN_THRESHOLD,
)
from calypso.workflows.report_sections_helpers import (
    BG_CARD,
    BORDER,
    CYAN,
    GREEN,
    RED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    YELLOW,
    criteria_box,
    failure_guidance_box,
    find_step_with_key,
    format_aer_with_decode,
    render_extra_measured_values,
    safe_int,
    summary_metrics,
)


# ---------------------------------------------------------------------------
# Error Aggregation Sweep
# ---------------------------------------------------------------------------


def render_error_aggregation_sweep(summary: RecipeSummary) -> str:
    """Specialized renderer for error_aggregation_sweep results."""
    parts: list[str] = []

    parts.append(
        section_header(
            "Multi-Port Error Aggregation",
            "Error survey across all active ports on your endpoint's link",
        )
    )

    parts.append(
        criteria_box(
            [
                "PASS: Zero AER uncorrectable errors across all ports",
                "WARN: Correctable errors, MCU errors, or elevated recovery counts",
                "FAIL: Any uncorrectable AER error on any port",
            ]
        )
    )

    parts.append(summary_metrics(summary))

    # Overview cards from the enumerate step
    enum_step = find_step_with_key(summary.steps, "total_ports")
    if enum_step is not None:
        mv = enum_step.measured_values
        total_ports = str(safe_int(mv.get("total_ports", 0)))
        active_ports = str(safe_int(mv.get("active_ports", 0)))
        parts.append(
            '<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            + metric_card("Total Ports", total_ports, CYAN)
            + metric_card("Active Ports", active_ports, GREEN)
            + "</div>"
        )

    # Summary cards from aggregate totals
    agg_step = find_step_with_key(summary.steps, "total_ltssm_recoveries")
    if agg_step is not None:
        mv = agg_step.measured_values
        uncorr = safe_int(mv.get("total_aer_uncorrectable", 0))
        corr = safe_int(mv.get("total_aer_correctable", 0))
        mcu = safe_int(mv.get("total_mcu_errors", 0))
        recoveries = safe_int(mv.get("total_ltssm_recoveries", 0))
        uncorr_color = RED if uncorr > 0 else GREEN
        corr_color = YELLOW if corr > 0 else GREEN
        parts.append(
            '<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            + metric_card("AER Uncorrectable", str(uncorr), uncorr_color)
            + metric_card("AER Correctable", str(corr), corr_color)
            + metric_card("MCU Errors", str(mcu), YELLOW if mcu > 0 else GREEN)
            + metric_card("LTSSM Recoveries", str(recoveries), CYAN)
            + "</div>"
        )
        outlier_ports = mv.get("outlier_ports", [])
        if outlier_ports and isinstance(outlier_ports, list):
            port_list = ", ".join(str(p) for p in outlier_ports)
            parts.append(
                f'<div style="margin:8px 0; padding:8px 12px; background:{BG_CARD};'
                f" border:1px solid {YELLOW}; border-radius:4px;"
                f' font-size:13px; color:{YELLOW};">'
                f"Outlier ports (elevated recovery count): {html.escape(port_list)}"
                f"</div>"
            )

    # Per-port table
    port_rows: list[list[str]] = []
    for step in summary.steps:
        if not step.step_name.startswith("Port"):
            continue
        mv = step.measured_values
        port_label = step.step_name.replace(" errors", "")
        recovery = str(safe_int(mv.get("recovery_count", 0)))
        link_down = str(safe_int(mv.get("link_down_count", 0)))
        uncorr_raw = safe_int(mv.get("aer_uncorrectable", 0))
        corr_raw = safe_int(mv.get("aer_correctable", 0))
        mcu_errs = str(safe_int(mv.get("mcu_errors", 0)))
        port_rows.append(
            [
                port_label,
                recovery,
                link_down,
                format_aer_with_decode(uncorr_raw, "uncorrectable"),
                format_aer_with_decode(corr_raw, "correctable"),
                mcu_errs,
            ]
        )

    if port_rows:
        parts.append(section_header("Per-Port Error Breakdown"))
        parts.append(
            results_table(
                ["Port", "Recovery Count", "Link Down", "AER Uncorr", "AER Corr", "MCU Errors"],
                port_rows,
            )
        )

    # Failure guidance
    if summary.status.value == "fail":
        parts.append(failure_guidance_box("aer_uncorrectable"))

    # Catch-all extras
    _rendered: frozenset[str] = frozenset(
        {
            "total_ports",
            "active_ports",
            "active_port_numbers",
            "aer_available",
            "total_aer_uncorrectable",
            "total_aer_correctable",
            "total_mcu_errors",
            "total_ltssm_recoveries",
            "mcu_connected",
            "recovery_count",
            "link_down_count",
            "aer_uncorrectable",
            "aer_correctable",
            "mcu_errors",
            "outlier_ports",
        }
    )
    parts.append(render_extra_measured_values(summary, _rendered))

    return "".join(parts)


# ---------------------------------------------------------------------------
# Link Health Check
# ---------------------------------------------------------------------------


def render_link_health_check(summary: RecipeSummary) -> str:
    """Specialized renderer for link_health_check results."""
    parts: list[str] = []

    parts.append(
        section_header(
            "Endpoint Link Health Summary",
            "Quick health assessment of your endpoint's PCIe link",
        )
    )

    parts.append(
        criteria_box(
            [
                "PASS: Link active at target speed/width, zero AER errors, EQ complete",
                "WARN: Degraded speed/width, correctable errors, or elevated recovery counts",
                "FAIL: Link inactive, uncorrectable errors, or EQ incomplete at target speed",
            ]
        )
    )

    parts.append(summary_metrics(summary))

    # Link status cards
    link_step = find_step_with_key(summary.steps, "current_speed")
    has_degradation = False
    if link_step is not None:
        mv = link_step.measured_values
        speed = str(mv.get("current_speed", "N/A"))
        width_val = mv.get("current_width", "N/A")
        width = f"x{width_val}"
        dll_active = mv.get("dll_link_active", False)
        dll_label = "Yes" if dll_active else "No"
        dll_color = GREEN if dll_active else RED
        parts.append(
            '<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            + metric_card("Link Speed", speed, CYAN)
            + metric_card("Link Width", width, CYAN)
            + metric_card("DLL Active", dll_label, dll_color)
            + "</div>"
        )
        speed_degraded = mv.get("speed_degraded", False)
        width_degraded = mv.get("width_degraded", False)
        if speed_degraded or width_degraded:
            has_degradation = True
            warn_parts: list[str] = []
            if speed_degraded:
                max_speed = str(mv.get("max_link_speed", ""))
                warn_parts.append(f"Speed degraded (max: {html.escape(max_speed)})")
            if width_degraded:
                max_width = str(mv.get("max_link_width", ""))
                warn_parts.append(f"Width degraded (max: x{html.escape(max_width)})")
            warn_text = "; ".join(warn_parts)
            parts.append(
                f'<div style="margin:8px 0; padding:8px 12px; background:{BG_CARD};'
                f" border:1px solid {RED}; border-radius:4px;"
                f' font-size:13px; color:{RED};">'
                f"{warn_text}</div>"
            )

    # AER section
    aer_step = find_step_with_key(summary.steps, "uncorrectable_raw")
    has_uncorr = False
    if aer_step is not None:
        mv = aer_step.measured_values
        uncorr_raw = safe_int(mv.get("uncorrectable_raw", 0))
        corr_raw = safe_int(mv.get("correctable_raw", 0))
        if uncorr_raw != 0 or corr_raw != 0:
            has_uncorr = uncorr_raw != 0
            parts.append(section_header("AER Status"))
            uncorr_decoded = format_aer_with_decode(uncorr_raw, "uncorrectable")
            corr_decoded = format_aer_with_decode(corr_raw, "correctable")
            uncorr_color = RED if uncorr_raw != 0 else GREEN
            corr_color = YELLOW if corr_raw != 0 else GREEN
            parts.append(
                '<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
                + metric_card("Uncorrectable", uncorr_decoded, uncorr_color)
                + metric_card("Correctable", corr_decoded, corr_color)
                + "</div>"
            )

    # LTSSM section
    ltssm_step = find_step_with_key(summary.steps, "ltssm_state_name")
    if ltssm_step is not None:
        mv = ltssm_step.measured_values
        state_name = str(mv.get("ltssm_state_name", "Unknown"))
        parts.append(section_header("LTSSM State"))
        parts.append(
            '<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            + metric_card("LTSSM State", state_name, CYAN)
            + "</div>"
        )

    # Recovery count card
    rec_step = find_step_with_key(summary.steps, "rx_eval_count")
    if rec_step is not None:
        mv = rec_step.measured_values
        rec_count = safe_int(mv.get("recovery_count", 0))
        if rec_count > 100:
            rec_color = RED
        elif rec_count > 10:
            rec_color = YELLOW
        else:
            rec_color = GREEN
        parts.append(
            '<div style="display:flex; flex-wrap:wrap; gap:8px; margin:0 0 12px 0;">'
            + metric_card("Recovery Count", str(rec_count), rec_color)
            + "</div>"
        )

    # EQ Phase checklist
    eq_step = find_step_with_key(summary.steps, "eq_16gt_complete")
    if eq_step is not None:
        mv = eq_step.measured_values
        parts.append(section_header("Equalization Phase Status"))

        def _check_item(label: str, passed: object) -> str:
            ok = bool(passed)
            icon = "PASS" if ok else "FAIL"
            color = GREEN if ok else RED
            escaped_label = html.escape(label)
            return (
                f'<div style="margin:2px 0; font-size:13px;">'
                f'<span style="color:{color}; font-weight:600;">{icon}</span> '
                f'<span style="color:{TEXT_SECONDARY};">{escaped_label}</span>'
                f"</div>"
            )

        eq_html: list[str] = []
        for speed in ("16gt", "32gt", "64gt"):
            complete_key = f"eq_{speed}_complete"
            if complete_key not in mv:
                continue
            speed_label = speed.upper().replace("GT", " GT/s")
            eq_html.append(
                f'<div style="margin:8px 0 4px 0; font-size:13px; '
                f'font-weight:600; color:{CYAN};">{speed_label}</div>'
            )
            eq_html.append(_check_item("Complete", mv.get(complete_key)))
            eq_html.append(_check_item("Phase 1", mv.get(f"eq_{speed}_phase1_ok")))
            eq_html.append(_check_item("Phase 2", mv.get(f"eq_{speed}_phase2_ok")))
            eq_html.append(_check_item("Phase 3", mv.get(f"eq_{speed}_phase3_ok")))

        if eq_html:
            parts.append(
                f'<div style="padding:10px 14px; background:{BG_CARD};'
                f" border:1px solid {BORDER}; border-radius:6px;"
                f' margin:8px 0;">' + "".join(eq_html) + "</div>"
            )

    # Flit errors (Gen6)
    flit_step = find_step_with_key(summary.steps, "flit_error_log_entries")
    if flit_step is not None:
        mv = flit_step.measured_values
        flit_entries = str(safe_int(mv.get("flit_error_log_entries", 0)))
        fec_uncorr = str(safe_int(mv.get("fec_uncorrectable_count", 0)))
        fec_corr = str(safe_int(mv.get("fec_correctable_count", 0)))
        parts.append(section_header("Flit Errors (Gen6)"))
        parts.append(
            '<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            + metric_card("Flit Log Entries", flit_entries, CYAN)
            + metric_card("FEC Uncorrectable", fec_uncorr, RED if fec_uncorr != "0" else GREEN)
            + metric_card("FEC Correctable", fec_corr, YELLOW if fec_corr != "0" else GREEN)
            + "</div>"
        )

    # Failure guidance
    eq_incomplete = False
    if eq_step is not None:
        for speed in ("16gt", "32gt", "64gt"):
            key = f"eq_{speed}_complete"
            if key in eq_step.measured_values and not eq_step.measured_values[key]:
                eq_incomplete = True
                break

    if summary.status.value == "fail":
        if has_uncorr:
            parts.append(failure_guidance_box("aer_uncorrectable"))
        elif has_degradation:
            parts.append(failure_guidance_box("link_degraded"))
        elif eq_incomplete:
            parts.append(failure_guidance_box("eq_incomplete"))

    # Catch-all extras
    _rendered: frozenset[str] = frozenset(
        {
            "current_speed",
            "current_width",
            "target_speed",
            "dll_link_active",
            "link_training",
            "max_link_speed",
            "max_link_width",
            "width_degraded",
            "speed_degraded",
            "uncorrectable_raw",
            "correctable_raw",
            "first_error_pointer",
            "ltssm_state",
            "ltssm_state_name",
            "link_speed",
            "link_speed_name",
            "recovery_count",
            "link_down_count",
            "rx_eval_count",
            "eq_16gt_complete",
            "eq_16gt_phase1_ok",
            "eq_16gt_phase2_ok",
            "eq_16gt_phase3_ok",
            "eq_32gt_complete",
            "eq_32gt_phase1_ok",
            "eq_32gt_phase2_ok",
            "eq_32gt_phase3_ok",
            "eq_64gt_complete",
            "eq_64gt_phase1_ok",
            "eq_64gt_phase2_ok",
            "eq_64gt_phase3_ok",
            "eq_64gt_flit_mode_supported",
            "flit_error_log_entries",
            "fec_uncorrectable_count",
            "fec_correctable_count",
            "fber_total_errors",
            "fber_flit_counter",
            "fber_lane_counters",
        }
    )
    parts.append(render_extra_measured_values(summary, _rendered))

    return "".join(parts)


# ---------------------------------------------------------------------------
# Speed Downshift Test
# ---------------------------------------------------------------------------


def render_speed_downshift_test(summary: RecipeSummary) -> str:
    """Specialized renderer for speed_downshift_test results."""
    parts: list[str] = []

    parts.append(
        section_header(
            "Endpoint Speed Downshift Test",
            "Validates your endpoint negotiates correctly at each PCIe speed tier",
        )
    )

    parts.append(
        criteria_box(
            [
                "PASS: Endpoint successfully negotiates at each target speed",
                "WARN: Speed negotiation succeeded but AER correctable errors detected",
                "FAIL: Speed mismatch or uncorrectable AER errors at any speed tier",
            ]
        )
    )

    parts.append(summary_metrics(summary))

    # Baseline cards
    baseline_step = find_step_with_key(summary.steps, "baseline_speed")
    baseline_speed = ""
    if baseline_step is not None:
        mv = baseline_step.measured_values
        baseline_speed = str(mv.get("baseline_speed", "N/A"))
        baseline_width = str(mv.get("baseline_width", "N/A"))
        parts.append(
            section_header("Baseline")
            + '<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            + metric_card("Baseline Speed", baseline_speed, CYAN)
            + metric_card("Baseline Width", f"x{baseline_width}", CYAN)
            + "</div>"
        )

    # Per-speed results table
    speed_rows: list[list[str]] = []
    for step in summary.steps:
        mv = step.measured_values
        if "target_speed" not in mv:
            continue
        # Skip the baseline step which also has target_speed as a different meaning
        if "baseline_speed" in mv:
            continue
        target = str(mv.get("target_speed", ""))
        actual_speed = str(mv.get("actual_speed", "N/A"))
        actual_width = str(mv.get("actual_width", "N/A"))
        matched = mv.get("speed_matched", False)
        match_status = "pass" if matched else "fail"
        uncorr_raw = safe_int(mv.get("aer_uncorrectable", 0))
        corr_raw = safe_int(mv.get("aer_correctable", 0))
        speed_rows.append(
            [
                target,
                actual_speed,
                f"x{actual_width}",
                match_status,
                format_aer_with_decode(uncorr_raw, "uncorrectable"),
                format_aer_with_decode(corr_raw, "correctable"),
            ]
        )

    if speed_rows:
        parts.append(section_header("Speed Negotiation Results"))
        parts.append(
            results_table(
                ["Target", "Actual Speed", "Width", "Match", "AER Uncorr", "AER Corr"],
                speed_rows,
                status_column=3,
            )
        )

    # Restore section
    restore_step = find_step_with_key(summary.steps, "restored_speed")
    if restore_step is not None:
        mv = restore_step.measured_values
        restored_speed = str(mv.get("restored_speed", "N/A"))
        restored_width = str(mv.get("restored_width", "N/A"))
        restore_ok = restored_speed == baseline_speed if baseline_speed else True
        restore_color = GREEN if restore_ok else RED
        parts.append(
            section_header("Speed Restore")
            + '<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            + metric_card("Restored Speed", restored_speed, restore_color)
            + metric_card("Restored Width", f"x{restored_width}", restore_color)
            + "</div>"
        )

    # Failure guidance
    if summary.status.value == "fail":
        parts.append(failure_guidance_box("aer_uncorrectable"))

    # Catch-all extras
    _rendered: frozenset[str] = frozenset(
        {
            "baseline_speed",
            "baseline_width",
            "original_speed_code",
            "target_speed",
            "actual_speed",
            "actual_width",
            "speed_matched",
            "aer_uncorrectable",
            "aer_correctable",
            "restored_speed",
            "restored_width",
        }
    )
    parts.append(render_extra_measured_values(summary, _rendered))

    return "".join(parts)


# ---------------------------------------------------------------------------
# LTSSM Monitor
# ---------------------------------------------------------------------------


def render_ltssm_monitor(summary: RecipeSummary) -> str:
    """Specialized renderer for ltssm_monitor results.

    Shows LTSSM state timeline, transition table, and recovery count
    with threshold from the recipe as single source of truth.
    """
    header = section_header(
        "Endpoint LTSSM Monitor",
        f"Category: {summary.category.value} | Duration: {summary.duration_ms:.0f}ms",
    )
    metrics = summary_metrics(summary)

    # Extract key data from steps
    init_step = find_step_with_key(summary.steps, "initial_state")
    poll_step = find_step_with_key(summary.steps, "sample_count")
    analysis_step = find_step_with_key(summary.steps, "transitions")

    # Summary metric cards
    cards: list[str] = []
    initial_state = ""
    if init_step:
        mv = init_step.measured_values
        initial_state = str(mv.get("initial_state", ""))
        cards.append(metric_card("Initial State", initial_state, CYAN))

    final_state = ""
    recovery_count = 0
    sample_count = 0
    if poll_step:
        mv = poll_step.measured_values
        final_state = str(mv.get("final_state", ""))
        recovery_count = safe_int(mv.get("recovery_count", 0))
        sample_count = safe_int(mv.get("sample_count", 0))
        cards.append(metric_card("Final State", final_state, CYAN))
        cards.append(metric_card("Samples", str(sample_count), TEXT_PRIMARY))

        recovery_color = RED if recovery_count >= _RECOVERY_WARN_THRESHOLD else GREEN
        cards.append(metric_card("Recovery Count", str(recovery_count), recovery_color))

    cards_html = ""
    if cards:
        cards_html = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{''.join(cards)}</div>"
        )

    # Criteria box
    criteria = criteria_box(
        [
            "PASS: No transitions or expected transitions only",
            f"WARN: Recovery count >= {_RECOVERY_WARN_THRESHOLD} during monitoring",
            "Monitors endpoint LTSSM state/substate at configurable poll interval",
        ]
    )

    # Transition timeline table
    transition_table = ""
    if analysis_step:
        transitions = analysis_step.measured_values.get("transitions", [])
        if isinstance(transitions, list) and transitions:
            columns = ["Time (ms)", "From", "To", "Recovery Count"]
            rows: list[list[str]] = []
            for t in transitions:
                if not isinstance(t, dict):
                    continue
                rows.append(
                    [
                        f"{float(t.get('elapsed_ms', 0)):.1f}",
                        str(t.get("from", "")),
                        str(t.get("to", "")),
                        str(safe_int(t.get("recovery_count", 0))),
                    ]
                )
            if rows:
                table_header = (
                    f'<div style="font-size:15px; font-weight:600; color:{TEXT_PRIMARY}; '
                    f'margin:20px 0 8px 0;">State Transitions</div>'
                )
                transition_table = table_header + results_table(columns, rows)
        elif isinstance(transitions, list) and not transitions:
            transition_table = (
                f'<div style="margin:16px 0; padding:12px; background:{BG_CARD}; '
                f"border:1px solid {BORDER}; border-radius:6px; "
                f'color:{GREEN}; font-size:13px; font-weight:500;">'
                f"No state transitions detected — link remained stable in "
                f"{html.escape(final_state or initial_state or 'unknown')}</div>"
            )

    # Guidance if recovery is high
    guidance = ""
    if recovery_count >= _RECOVERY_WARN_THRESHOLD:
        guidance = failure_guidance_box("recovery_high")

    # Catch-all extras
    _rendered = frozenset(
        {
            "initial_state",
            "initial_recovery_count",
            "sample_count",
            "transition_count",
            "final_state",
            "recovery_count",
            "transitions",
        }
    )
    extras = render_extra_measured_values(summary, _rendered)

    return f"{header}{criteria}{metrics}{cards_html}{transition_table}{guidance}{extras}"


# ---------------------------------------------------------------------------
# PTrace Capture
# ---------------------------------------------------------------------------


def render_ptrace_capture(summary: RecipeSummary) -> str:
    """Specialized renderer for ptrace_capture results."""
    parts: list[str] = []

    parts.append(
        section_header(
            "PTrace Capture",
            f"Duration: {summary.duration_ms:.0f}ms",
        )
    )

    parts.append(
        criteria_box(
            [
                "Captures packet trace buffer entries from the switch ASIC",
                "DW occupancy distribution reveals traffic composition",
                "Non-standard DW values may indicate anomalous packets",
            ]
        )
    )

    parts.append(summary_metrics(summary))

    # Capture configuration cards
    config_step = find_step_with_key(summary.steps, "capture_mode")
    if config_step is not None:
        mv = config_step.measured_values
        mode = str(mv.get("capture_mode", "unknown"))
        parts.append(
            '<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            + metric_card("Capture Mode", mode, CYAN)
            + "</div>"
        )

    # Buffer stats
    buf_step = find_step_with_key(summary.steps, "total_rows_read")
    if buf_step is not None:
        mv = buf_step.measured_values
        rows = str(safe_int(mv.get("total_rows_read", 0)))
        triggered = "Yes" if mv.get("triggered") else "No"
        wrapped = "Yes" if mv.get("tbuf_wrapped") else "No"
        parts.append(
            '<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            + metric_card("Rows Read", rows, CYAN)
            + metric_card("Triggered", triggered, GREEN if triggered == "Yes" else TEXT_SECONDARY)
            + metric_card("Buffer Wrapped", wrapped, YELLOW if wrapped == "Yes" else GREEN)
            + "</div>"
        )

    # Analysis results
    analysis_step = find_step_with_key(summary.steps, "entry_count")
    if analysis_step is not None:
        mv = analysis_step.measured_values
        entry_count = str(safe_int(mv.get("entry_count", 0)))
        direction = str(mv.get("direction", ""))
        anomalous = safe_int(mv.get("anomalous_rows", 0))
        anomalous_color = YELLOW if anomalous > 0 else GREEN
        parts.append(
            '<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            + metric_card("Trace Entries", entry_count, CYAN)
            + metric_card("Direction", direction, TEXT_SECONDARY)
            + metric_card("Anomalous DW Rows", str(anomalous), anomalous_color)
            + "</div>"
        )

        # DW occupancy distribution as table
        dw_dist = mv.get("dw_occupancy_distribution")
        if isinstance(dw_dist, dict) and dw_dist:
            dw_header = section_header("DW Occupancy Distribution", "")
            dw_columns = ["DW Occupancy", "Count"]
            dw_rows: list[list[str]] = [
                [str(dw), str(count)]
                for dw, count in sorted(dw_dist.items(), key=lambda x: int(str(x[0])))
            ]
            parts.append(dw_header + results_table(dw_columns, dw_rows))

    _rendered: frozenset[str] = frozenset(
        {
            "capture_mode",
            "total_rows_read",
            "triggered",
            "tbuf_wrapped",
            "entry_count",
            "direction",
            "actual_duration_s",
            "anomalous_rows",
            "dw_occupancy_distribution",
            "trigger_row_addr",
            "wrapped",
        }
    )
    parts.append(render_extra_measured_values(summary, _rendered))

    return "".join(parts)
