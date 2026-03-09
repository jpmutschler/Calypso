"""Gen6-specific recipe HTML section renderers for workflow reports.

Renderers for eye scan, link training debug, PHY 64GT audit,
Flit performance measurement, and PAM4 eye sweep.
"""

from __future__ import annotations

import html

from calypso.workflows.models import RecipeSummary

from calypso.workflows.thresholds import PAM4_EYE, get_eye_thresholds
from calypso.workflows.report_charts import (
    bar_chart,
    metric_card,
    results_table,
    section_header,
)
from calypso.workflows.report_sections_helpers import (
    BORDER,
    BG_CARD,
    CYAN,
    GREEN,
    RED,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    YELLOW,
    criteria_box,
    find_step_with_key,
    render_extra_measured_values,
    safe_int,
    summary_metrics,
)


# ---------------------------------------------------------------------------
# Eye Quick Scan
# ---------------------------------------------------------------------------


def render_eye_scan(summary: RecipeSummary) -> str:
    """Specialized renderer for eye_quick_scan results."""
    header = section_header("Eye Quick Scan", f"Duration: {summary.duration_ms:.0f}ms")

    columns = [
        "Lane",
        "Status",
        "Eye Width (UI)",
        "Eye Height (mV)",
        "Margin R (UI)",
        "Margin L (UI)",
        "Margin Up (mV)",
        "Margin Down (mV)",
    ]
    rows: list[list[str]] = []
    link_speed = ""
    link_width = ""
    for step in summary.steps:
        mv = step.measured_values
        if "eye_width_ui" not in mv:
            continue
        if not link_speed:
            link_speed = str(mv.get("link_speed", ""))
            link_width = str(mv.get("link_width", ""))
        lane = step.lane if step.lane is not None else mv.get("lane", "")
        rows.append(
            [
                str(lane),
                step.status.value.upper(),
                f"{float(mv.get('eye_width_ui', 0)):.4f}",
                f"{float(mv.get('eye_height_mv', 0)):.2f}",
                f"{float(mv.get('margin_right_ui', 0)):.4f}",
                f"{float(mv.get('margin_left_ui', 0)):.4f}",
                f"{float(mv.get('margin_up_mv', 0)):.2f}",
                f"{float(mv.get('margin_down_mv', 0)):.2f}",
            ]
        )

    # Select PAM4 or NRZ thresholds based on detected link speed
    is_pam4 = "Gen6" in link_speed if link_speed else False
    eye_th = get_eye_thresholds(is_pam4=is_pam4)
    signal_label = "PAM4" if is_pam4 else "NRZ"

    criteria = criteria_box(
        [
            f"PASS: Eye width >= {eye_th.pass_ui} UI ({signal_label})",
            f"WARN: Eye width >= {eye_th.warn_ui} UI",
            f"FAIL: Eye width < {eye_th.warn_ui} UI",
        ]
    )

    table = results_table(columns, rows, status_column=1)

    # Per-lane eye width/height bar charts for quick visual scanning
    width_chart = ""
    height_chart = ""
    if rows:
        width_data = [(f"Lane {r[0]}", float(r[2])) for r in rows]
        height_data = [(f"Lane {r[0]}", float(r[3])) for r in rows]
        if width_data:
            width_chart = (
                section_header("Eye Width per Lane (UI)", "")
                + bar_chart(width_data, bar_color=CYAN, height_px=16)
                + f'<div style="font-size:11px; color:{TEXT_SECONDARY}; '
                f'margin:4px 0 8px 0;">PASS \u2265 {eye_th.pass_ui} UI | '
                f"WARN \u2265 {eye_th.warn_ui} UI | FAIL &lt; {eye_th.warn_ui} UI</div>"
            )
        if height_data:
            height_chart = section_header("Eye Height per Lane (mV)", "") + bar_chart(
                height_data, bar_color=GREEN, height_px=16
            )

    # Link info cards
    link_cards = ""
    if link_speed:
        link_cards = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{metric_card('Link Speed', link_speed, CYAN)}"
            f"{metric_card('Link Width', f'x{link_width}' if link_width else 'N/A', CYAN)}"
            f"</div>"
        )

    _rendered = frozenset(
        {
            "eye_width_ui",
            "eye_height_mv",
            "margin_right_ui",
            "margin_left_ui",
            "margin_up_mv",
            "margin_down_mv",
            "link_speed",
            "link_width",
            "lane",
        }
    )
    extras = render_extra_measured_values(summary, _rendered)
    metrics = summary_metrics(summary)
    return f"{header}{criteria}{metrics}{link_cards}{width_chart}{height_chart}{table}{extras}"


# ---------------------------------------------------------------------------
# Link Training Debug
# ---------------------------------------------------------------------------


def render_link_training_debug(summary: RecipeSummary) -> str:
    """Specialized renderer for link_training_debug results."""
    header = section_header(
        "Endpoint Link Training Debug", f"Duration: {summary.duration_ms:.0f}ms"
    )

    # LTSSM transition timeline
    transition_step = find_step_with_key(summary.steps, "transitions")
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
    aer_step = find_step_with_key(summary.steps, "uncorrectable_raw")
    aer_section = ""
    if aer_step is not None:
        mv = aer_step.measured_values
        uncorr = safe_int(mv.get("uncorrectable_raw", 0))
        corr = safe_int(mv.get("correctable_raw", 0))
        uncorr_hex = f"0x{uncorr:08X}"
        corr_hex = f"0x{corr:08X}"
        uncorr_color = RED if uncorr != 0 else GREEN
        corr_color = YELLOW if corr != 0 else GREEN
        aer_section = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{metric_card('Uncorrectable AER', uncorr_hex, uncorr_color)}"
            f"{metric_card('Correctable AER', corr_hex, corr_color)}"
            f"</div>"
        )

    # Post-retrain link status
    link_step = find_step_with_key(summary.steps, "current_speed")
    link_section = ""
    if link_step is not None:
        mv = link_step.measured_values
        speed_val = str(mv.get("current_speed", ""))
        width_val = "x" + str(mv.get("current_width", ""))
        dll_active = mv.get("dll_link_active", False)
        dll_color = GREEN if dll_active else RED
        link_section = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{metric_card('Speed', speed_val, CYAN)}"
            f"{metric_card('Width', width_val, CYAN)}"
            f"{metric_card('DLL Active', str(dll_active), dll_color)}"
            f"</div>"
        )

    # EQ Phase data (Issue #2)
    eq_step = find_step_with_key(summary.steps, "eq_16gt_complete")
    eq_section = ""
    if eq_step is not None:
        mv = eq_step.measured_values
        eq_header = section_header("Equalization Phase Status", "")
        eq_columns = ["Speed", "Complete", "Phase 1", "Phase 2", "Phase 3", "Flit Mode"]
        eq_rows: list[list[str]] = []
        for speed_prefix, speed_label in [
            ("eq_16gt", "16 GT/s"),
            ("eq_32gt", "32 GT/s"),
            ("eq_64gt", "64 GT/s"),
        ]:
            complete_key = f"{speed_prefix}_complete"
            if complete_key not in mv:
                continue
            complete = mv.get(complete_key, False)
            p1 = mv.get(f"{speed_prefix}_phase1", None)
            p2 = mv.get(f"{speed_prefix}_phase2", None)
            p3 = mv.get(f"{speed_prefix}_phase3", None)
            flit = mv.get(f"{speed_prefix}_flit_mode", None)
            eq_rows.append(
                [
                    speed_label,
                    "YES" if complete else "NO",
                    "OK" if p1 else ("FAIL" if p1 is False else "N/A"),
                    "OK" if p2 else ("FAIL" if p2 is False else "N/A"),
                    "OK" if p3 else ("FAIL" if p3 is False else "N/A"),
                    "YES" if flit else ("NO" if flit is False else "N/A"),
                ]
            )
        if eq_rows:
            eq_section = eq_header + results_table(eq_columns, eq_rows)

    # Flit Error Log data (Issue #2)
    flit_step = find_step_with_key(summary.steps, "valid_entries")
    flit_section = ""
    if flit_step is not None:
        mv = flit_step.measured_values
        valid = safe_int(mv.get("valid_entries", 0))
        uncorr_count = safe_int(mv.get("uncorrectable_count", 0))
        flit_header = section_header("Flit Error Log", "")
        flit_cards = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{metric_card('Valid Entries', str(valid), CYAN)}"
            f"{metric_card('Uncorrectable', str(uncorr_count), RED if uncorr_count > 0 else GREEN)}"
            f"</div>"
        )

        entries = mv.get("entries", [])
        flit_table = ""
        if isinstance(entries, list) and entries:
            entry_columns = [
                "Link Width",
                "Flit Offset",
                "Consecutive",
                "Unrecognized",
                "FEC Uncorr.",
                "Syndrome 0",
                "Syndrome 1",
                "Syndrome 2",
            ]
            entry_rows: list[list[str]] = []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                entry_rows.append(
                    [
                        str(entry.get("link_width", "")),
                        str(entry.get("flit_offset", "")),
                        str(entry.get("consecutive_errors", "")),
                        str(entry.get("unrecognized_flit", "")),
                        str(entry.get("fec_uncorrectable", "")),
                        str(entry.get("syndrome_0", "")),
                        str(entry.get("syndrome_1", "")),
                        str(entry.get("syndrome_2", "")),
                    ]
                )
            if entry_rows:
                flit_table = results_table(entry_columns, entry_rows)

        flit_section = flit_header + flit_cards + flit_table

    _rendered = frozenset(
        {
            "transitions",
            "final_state",
            "uncorrectable_raw",
            "correctable_raw",
            "current_speed",
            "current_width",
            "dll_link_active",
            "target_speed",
            "link_training",
            "pre_retrain_ltssm",
            "eq_16gt_complete",
            "eq_16gt_phase1",
            "eq_16gt_phase2",
            "eq_16gt_phase3",
            "eq_16gt_flit_mode",
            "eq_16gt_raw",
            "eq_16gt_raw_status",
            "eq_32gt_complete",
            "eq_32gt_phase1",
            "eq_32gt_phase2",
            "eq_32gt_phase3",
            "eq_32gt_flit_mode",
            "eq_32gt_raw",
            "eq_32gt_raw_status",
            "eq_32gt_no_eq_needed",
            "eq_64gt_complete",
            "eq_64gt_phase1",
            "eq_64gt_phase2",
            "eq_64gt_phase3",
            "eq_64gt_flit_mode",
            "eq_64gt_raw",
            "eq_64gt_raw_status",
            "eq_64gt_no_eq_needed",
            "valid_entries",
            "uncorrectable_count",
            "entries",
        }
    )
    extras = render_extra_measured_values(summary, _rendered)
    metrics = summary_metrics(summary)
    return (
        f"{header}{metrics}{link_section}{aer_section}{eq_section}{flit_section}{timeline}{extras}"
    )


# ---------------------------------------------------------------------------
# PHY 64GT Audit
# ---------------------------------------------------------------------------


def render_phy_64gt_audit(summary: RecipeSummary) -> str:
    """Specialized renderer for phy_64gt_audit -- Gen6 capability checklist."""
    header = section_header("Endpoint PHY 64GT/s Audit", f"Duration: {summary.duration_ms:.0f}ms")

    # Gather capability flags from steps
    cap_step = find_step_with_key(summary.steps, "gen6_supported")
    link_step = find_step_with_key(summary.steps, "is_at_64gt")
    eq_step = find_step_with_key(summary.steps, "eq_complete")

    def _check_item(label: str, value: object) -> str:
        if value is True:
            icon_color = GREEN
            icon = "PASS"
        elif value is False:
            icon_color = RED
            icon = "FAIL"
        else:
            icon_color = TEXT_MUTED
            icon = "N/A"
        return (
            f'<div style="display:flex; align-items:center; gap:8px; '
            f'padding:6px 12px; border-bottom:1px solid {BORDER};">'
            f'<span style="color:{icon_color}; font-weight:600; '
            f'font-size:12px; min-width:40px;">{icon}</span>'
            f'<span style="color:{TEXT_PRIMARY}; font-size:13px;">'
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
        f'<div style="background:{BG_CARD}; border:1px solid {BORDER}; '
        f'border-radius:8px; overflow:hidden; margin:12px 0;">'
        f"{''.join(checks)}</div>"
        if checks
        else ""
    )

    # TX EQ Coefficients per lane (endpoint's negotiated TX settings)
    tx_eq_section = ""
    tx_step = find_step_with_key(summary.steps, "tx_eq_lanes")
    if tx_step is not None:
        tx_lanes = tx_step.measured_values.get("tx_eq_lanes", [])
        if isinstance(tx_lanes, list) and tx_lanes:
            tx_header = section_header(
                "Endpoint TX EQ Coefficients",
                "Per-lane transmitter presets and coefficients negotiated with your endpoint",
            )
            tx_columns = [
                "Lane",
                "DS TX Preset",
                "US TX Preset",
                "DS Pre",
                "DS Cursor",
                "DS Post",
                "US Pre",
                "US Cursor",
                "US Post",
            ]
            tx_rows: list[list[str]] = []
            for lane_data in tx_lanes:
                if not isinstance(lane_data, dict):
                    continue
                tx_rows.append(
                    [
                        str(lane_data.get("lane", "")),
                        f"P{lane_data.get('downstream_tx_preset', '')}"
                        if lane_data.get("downstream_tx_preset") is not None
                        else "N/A",
                        f"P{lane_data.get('upstream_tx_preset', '')}"
                        if lane_data.get("upstream_tx_preset") is not None
                        else "N/A",
                        str(lane_data.get("downstream_pre_cursor", "N/A")),
                        str(lane_data.get("downstream_cursor", "N/A")),
                        str(lane_data.get("downstream_post_cursor", "N/A")),
                        str(lane_data.get("upstream_pre_cursor", "N/A")),
                        str(lane_data.get("upstream_cursor", "N/A")),
                        str(lane_data.get("upstream_post_cursor", "N/A")),
                    ]
                )
            if tx_rows:
                tx_eq_section = tx_header + results_table(tx_columns, tx_rows)

    _rendered = frozenset(
        {
            "gen6_supported",
            "gen5_supported",
            "gen4_supported",
            "gen3_supported",
            "is_at_64gt",
            "current_speed",
            "current_width",
            "max_link_speed",
            "max_link_width",
            "eq_complete",
            "phase1_ok",
            "phase2_ok",
            "phase3_ok",
            "flit_mode_supported",
            "tx_eq_lanes",
            "eq_16gt_complete",
            "eq_32gt_complete",
        }
    )
    extras = render_extra_measured_values(summary, _rendered)
    metrics = summary_metrics(summary)
    return f"{header}{metrics}{checklist}{tx_eq_section}{extras}"


# ---------------------------------------------------------------------------
# Flit Performance Measurement
# ---------------------------------------------------------------------------


def render_flit_perf_measurement(summary: RecipeSummary) -> str:
    """Specialized renderer for flit_perf_measurement results."""
    header = section_header(
        "Endpoint Flit Throughput",
        f"Duration: {summary.duration_ms:.0f}ms",
    )

    results_step = find_step_with_key(summary.steps, "flits_tracked")
    flit_metrics = ""
    ltssm_table = ""

    if results_step is not None:
        mv = results_step.measured_values
        flits = mv.get("flits_tracked", 0)
        ltssm_counter = mv.get("ltssm_counter", 0)

        # Compute throughput rate (Issue #10)
        soak_step = find_step_with_key(summary.steps, "actual_soak_s")
        throughput_cards = ""
        if soak_step is not None:
            soak_s = float(soak_step.measured_values.get("actual_soak_s", 0))
            if soak_s > 0:
                flits_int = safe_int(flits)
                flits_per_sec = flits_int / soak_s
                # 256 bytes per Flit at Gen6
                effective_gbps = flits_int * 256 / soak_s / 1e9
                throughput_cards = (
                    f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
                    f"{metric_card('Flits/s', f'{flits_per_sec:,.0f}', CYAN)}"
                    f"{metric_card('~Effective GB/s', f'{effective_gbps:.1f}', GREEN)}"
                    f"</div>"
                )

        flit_metrics = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{metric_card('Flits Tracked', str(flits), GREEN if safe_int(flits) > 0 else YELLOW)}"
            f"{metric_card('LTSSM Counter', str(ltssm_counter), CYAN)}"
            f"</div>"
            f"{throughput_cards}"
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
    cap_step = find_step_with_key(summary.steps, "cap_offset")
    cap_section = ""
    if cap_step is not None:
        mv = cap_step.measured_values
        cap_hex = f"0x{safe_int(mv.get('cap_offset', 0)):04X}"
        cap_section = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{metric_card('Cap Offset', cap_hex, TEXT_SECONDARY)}"
            f"</div>"
        )

    _rendered_keys: set[str] = {
        "flits_tracked",
        "ltssm_counter",
        "actual_soak_s",
        "cap_offset",
    }
    # Include dynamically-named ltssm keys
    if results_step is not None:
        idx = 0
        mv = results_step.measured_values
        while f"ltssm_{idx}_counter" in mv:
            _rendered_keys.update(
                {
                    f"ltssm_{idx}_counter",
                    f"ltssm_{idx}_tracking_status",
                    f"ltssm_{idx}_tracking_count",
                }
            )
            idx += 1
    extras = render_extra_measured_values(summary, frozenset(_rendered_keys))
    metrics = summary_metrics(summary)
    return f"{header}{metrics}{flit_metrics}{cap_section}{ltssm_table}{extras}"


# ---------------------------------------------------------------------------
# PAM4 Eye Sweep
# ---------------------------------------------------------------------------


def render_pam4_eye_sweep(summary: RecipeSummary) -> str:
    """Specialized renderer for pam4_eye_sweep results with per-eye breakdown."""
    header = section_header("Endpoint PAM4 Eye Sweep", f"Duration: {summary.duration_ms:.0f}ms")

    criteria = criteria_box(
        [
            f"PASS: Worst sub-eye margin >= {PAM4_EYE.pass_ui} UI",
            f"WARN: Worst sub-eye margin >= {PAM4_EYE.fail_ui} UI",
            f"FAIL: Worst sub-eye margin < {PAM4_EYE.fail_ui} UI",
            "PAM4 signaling uses 3 sub-eyes (upper/middle/lower) per lane.",
        ]
    )

    # Per-lane worst-of-3-eyes summary table
    summary_columns = ["Lane", "Status", "Worst Width (UI)", "Worst Height (mV)", "Balanced"]
    summary_rows: list[list[str]] = []

    # Per-lane per-eye detail table
    eye_columns = [
        "Lane",
        "Eye",
        "Status",
        "Width (UI)",
        "Height (mV)",
    ]
    eye_rows: list[list[str]] = []

    for step in summary.steps:
        mv = step.measured_values
        if "eye_width_ui" not in mv:
            continue
        lane = step.lane if step.lane is not None else mv.get("lane", "")
        lane_str = str(lane)

        # Summary row (worst-of-3)
        is_balanced = mv.get("is_balanced")
        balanced_str = "Yes" if is_balanced else "No" if is_balanced is not None else ""
        summary_rows.append(
            [
                lane_str,
                step.status.value.upper(),
                f"{float(mv.get('eye_width_ui', 0)):.4f}",
                f"{float(mv.get('eye_height_mv', 0)):.2f}",
                balanced_str,
            ]
        )

        # Per-eye rows (if sub-eye data present)
        has_sub_eyes = "upper_eye_width_ui" in mv
        if has_sub_eyes:
            for eye_name, prefix in [("Upper", "upper"), ("Middle", "middle"), ("Lower", "lower")]:
                w = float(mv.get(f"{prefix}_eye_width_ui", 0))
                h = float(mv.get(f"{prefix}_eye_height_mv", 0))
                if w >= PAM4_EYE.pass_ui:
                    eye_status = "PASS"
                elif w >= PAM4_EYE.fail_ui:
                    eye_status = "WARN"
                else:
                    eye_status = "FAIL"
                eye_rows.append([lane_str, eye_name, eye_status, f"{w:.4f}", f"{h:.2f}"])

    summary_table = (
        results_table(summary_columns, summary_rows, status_column=1) if summary_rows else ""
    )

    # Per-eye detail table
    eye_detail_section = ""
    if eye_rows:
        eye_header = (
            f'<div style="font-size:15px; font-weight:600; color:{TEXT_PRIMARY}; '
            f'margin:20px 0 8px 0;">Per-Eye Breakdown (Upper / Middle / Lower)</div>'
        )
        eye_detail_section = eye_header + results_table(eye_columns, eye_rows, status_column=2)

    # Per-lane eye width bar charts (worst-of-3)
    width_chart = ""
    height_chart = ""
    if summary_rows:
        width_data = [(f"Lane {r[0]}", float(r[2])) for r in summary_rows]
        height_data = [(f"Lane {r[0]}", float(r[3])) for r in summary_rows]
        if width_data:
            width_chart = (
                section_header("Worst Eye Width per Lane (UI)", "")
                + bar_chart(width_data, bar_color=CYAN, height_px=16)
                + f'<div style="font-size:11px; color:{TEXT_SECONDARY}; '
                f'margin:4px 0 8px 0;">PASS \u2265 {PAM4_EYE.pass_ui} UI | '
                f"WARN \u2265 {PAM4_EYE.fail_ui} UI | FAIL &lt; {PAM4_EYE.fail_ui} UI</div>"
            )
        if height_data:
            height_chart = section_header("Worst Eye Height per Lane (mV)", "") + bar_chart(
                height_data, bar_color=GREEN, height_px=16
            )

    # Worst margin summary from aggregate step
    agg_step = find_step_with_key(summary.steps, "worst_lane")
    margin_section = ""
    if agg_step is not None:
        mv = agg_step.measured_values
        worst_lane = mv.get("worst_lane", -1)
        worst_margin = float(str(mv.get("worst_margin_ui", 0)))
        margin_color = (
            RED
            if worst_margin < PAM4_EYE.fail_ui
            else YELLOW
            if worst_margin < PAM4_EYE.pass_ui
            else GREEN
        )
        margin_section = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{metric_card('Worst Lane', str(worst_lane), margin_color)}"
            f"{metric_card('Worst Margin', f'{worst_margin:.4f} UI', margin_color)}"
            f"</div>"
        )

    _rendered = frozenset(
        {
            "eye_width_ui",
            "eye_height_mv",
            "is_balanced",
            "upper_eye_width_ui",
            "upper_eye_height_mv",
            "middle_eye_width_ui",
            "middle_eye_height_mv",
            "lower_eye_width_ui",
            "lower_eye_height_mv",
            "margin_right_ui",
            "margin_left_ui",
            "margin_up_mv",
            "margin_down_mv",
            "sweep_time_ms",
            "lane",
            "worst_lane",
            "worst_margin_ui",
        }
    )
    extras = render_extra_measured_values(summary, _rendered)
    metrics = summary_metrics(summary)
    return (
        f"{header}{criteria}{metrics}{margin_section}"
        f"{width_chart}{height_chart}{summary_table}{eye_detail_section}{extras}"
    )
