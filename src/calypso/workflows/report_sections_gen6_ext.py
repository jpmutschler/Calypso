"""Extended Gen6 recipe renderers for workflow reports.

Renderers for EQ phase audit, Flit error injection, and SerDes diagnostics.
Split from report_sections_gen6.py to keep file sizes manageable.
"""

from __future__ import annotations

import html

from calypso.workflows.models import RecipeSummary
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
# EQ Phase Audit
# ---------------------------------------------------------------------------


def render_eq_phase_audit(summary: RecipeSummary) -> str:
    """Specialized renderer for eq_phase_audit -- endpoint EQ negotiation audit."""
    header = section_header(
        "Endpoint EQ Negotiation Audit",
        f"Duration: {summary.duration_ms:.0f}ms | "
        "EQ parameters negotiated between your endpoint and the switch",
    )

    criteria = criteria_box(
        [
            "All EQ phases must complete for a stable Gen6 link",
            "Incomplete EQ at 64GT/s indicates endpoint or channel issues",
            "Per-lane TX presets should be consistent across lanes for uniform signal quality",
        ]
    )

    # Link speed/width cards
    link_step = find_step_with_key(summary.steps, "current_speed")
    link_cards = ""
    if link_step is not None:
        mv = link_step.measured_values
        speed_val = str(mv.get("current_speed", "N/A"))
        width_val = str(mv.get("current_width", "N/A"))
        link_cards = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{metric_card('Link Speed', speed_val, CYAN)}"
            f"{metric_card('Link Width', 'x' + width_val, CYAN)}"
            f"</div>"
        )

    # Per-speed EQ checklist
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
    speed_labels = [
        ("Read 16GT EQ status", "16 GT/s"),
        ("Read 32GT EQ status", "32 GT/s"),
        ("Read 64GT EQ status", "64 GT/s"),
    ]
    for step_name, speed_label in speed_labels:
        for step in summary.steps:
            if step.step_name == step_name and step.measured_values:
                mv = step.measured_values
                checks.append(_check_item(f"{speed_label} EQ Complete", mv.get("eq_complete")))
                checks.append(_check_item(f"{speed_label} Phase 1", mv.get("phase1_ok")))
                checks.append(_check_item(f"{speed_label} Phase 2", mv.get("phase2_ok")))
                checks.append(_check_item(f"{speed_label} Phase 3", mv.get("phase3_ok")))
                if "flit_mode_supported" in mv:
                    checks.append(
                        _check_item(f"{speed_label} Flit Mode", mv.get("flit_mode_supported"))
                    )
                break

    checklist = (
        f'<div style="background:{BG_CARD}; border:1px solid {BORDER}; '
        f'border-radius:8px; overflow:hidden; margin:12px 0;">'
        f"{''.join(checks)}</div>"
        if checks
        else ""
    )

    # Per-lane EQ settings table
    eq_table_section = ""
    eq_step = find_step_with_key(summary.steps, "eq_settings")
    if eq_step is not None:
        eq_settings = eq_step.measured_values.get("eq_settings", [])
        if isinstance(eq_settings, list) and eq_settings:
            eq_header = section_header(
                "Per-Lane EQ Settings",
                "Downstream = endpoint TX | Upstream = switch TX",
            )
            eq_columns = [
                "Lane",
                "DS TX Preset",
                "US TX Preset",
                "DS RX Hint",
                "US RX Hint",
            ]
            eq_rows: list[list[str]] = []
            for lane_info in eq_settings:
                if not isinstance(lane_info, dict):
                    continue
                eq_rows.append(
                    [
                        str(lane_info.get("lane", "")),
                        f"P{lane_info.get('downstream_tx_preset', 'N/A')}",
                        f"P{lane_info.get('upstream_tx_preset', 'N/A')}",
                        str(lane_info.get("downstream_rx_preset_hint", "N/A")),
                        str(lane_info.get("upstream_rx_preset_hint", "N/A")),
                    ]
                )
            if eq_rows:
                eq_table_section = eq_header + results_table(eq_columns, eq_rows)

    # EQ consistency assessment
    consistency_step = find_step_with_key(summary.steps, "eq_incomplete")
    consistency_section = ""
    if consistency_step is not None:
        eq_incomplete = consistency_step.measured_values.get("eq_incomplete", False)
        consistency_color = RED if eq_incomplete else GREEN
        consistency_section = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{metric_card('EQ Status', 'INCOMPLETE' if eq_incomplete else 'COMPLETE', consistency_color)}"
            f"</div>"
        )

    _rendered = frozenset(
        {
            "current_speed",
            "current_width",
            "eq_complete",
            "phase1_ok",
            "phase2_ok",
            "phase3_ok",
            "flit_mode_supported",
            "lanes_read",
            "unique_tx_presets",
            "eq_settings",
            "eq_incomplete",
        }
    )
    extras = render_extra_measured_values(summary, _rendered)
    metrics = summary_metrics(summary)
    return (
        f"{header}{criteria}{metrics}{link_cards}{consistency_section}"
        f"{checklist}{eq_table_section}{extras}"
    )


# ---------------------------------------------------------------------------
# Flit Error Injection
# ---------------------------------------------------------------------------


def render_flit_error_injection(summary: RecipeSummary) -> str:
    """Specialized renderer for flit_error_injection -- endpoint error detection verification."""
    header = section_header(
        "Flit Error Injection Verification",
        f"Duration: {summary.duration_ms:.0f}ms | "
        "Validates your endpoint detects and logs injected Flit errors",
    )

    criteria = criteria_box(
        [
            "PASS: All injected errors appear in the Flit Error Log",
            "WARN: Partial match (some entries missing)",
            "FAIL: No log entries detected for injected errors",
        ]
    )

    # Injection config
    config_step = find_step_with_key(summary.steps, "num_errors")
    config_section = ""
    if config_step is not None:
        mv = config_step.measured_values
        error_type_labels = {0: "CRC", 1: "Seq Num", 2: "Reserved", 3: "Reserved"}
        etype = safe_int(mv.get("error_type", 0))
        etype_label = str(etype) + " (" + error_type_labels.get(etype, "Unknown") + ")"
        config_section = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{metric_card('Errors Injected', str(mv.get('num_errors', 0)), CYAN)}"
            f"{metric_card('Error Type', etype_label, CYAN)}"
            f"{metric_card('TX Path', 'Yes' if mv.get('inject_tx') else 'No', CYAN)}"
            f"{metric_card('RX Path', 'Yes' if mv.get('inject_rx') else 'No', CYAN)}"
            f"</div>"
        )

    # Injection results -- entries detected vs injected
    verdict_step = find_step_with_key(summary.steps, "entries_detected")
    verdict_section = ""
    if verdict_step is not None:
        mv = verdict_step.measured_values
        detected = safe_int(mv.get("entries_detected", 0))
        injected = safe_int(mv.get("errors_injected", 0))
        match = mv.get("match", False)
        match_color = GREEN if match else RED
        verdict_section = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{metric_card('Log Entries', str(detected), match_color)}"
            f"{metric_card('Expected', str(injected), CYAN)}"
            f"{metric_card('Match', 'YES' if match else 'NO', match_color)}"
            f"</div>"
        )

    # Post-injection AER status
    aer_step = find_step_with_key(summary.steps, "uncorrectable_raw")
    aer_section = ""
    if aer_step is not None:
        mv = aer_step.measured_values
        uncorr = safe_int(mv.get("uncorrectable_raw", 0))
        corr = safe_int(mv.get("correctable_raw", 0))
        uncorr_hex = f"0x{uncorr:08X}"
        corr_hex = f"0x{corr:08X}"
        aer_section = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{metric_card('Uncorrectable AER', uncorr_hex, RED if uncorr else GREEN)}"
            f"{metric_card('Correctable AER', corr_hex, YELLOW if corr else GREEN)}"
            f"</div>"
        )

    # Flit Error Log drain count
    drain_step = find_step_with_key(summary.steps, "entries_read")
    drain_section = ""
    if drain_step is not None:
        mv = drain_step.measured_values
        entries_read = safe_int(mv.get("entries_read", 0))
        expected = safe_int(mv.get("expected_entries", 0))
        drain_section = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{metric_card('Log Entries Read', str(entries_read), CYAN)}"
            f"{metric_card('Expected Entries', str(expected), CYAN)}"
            f"</div>"
        )

    # Injection status registers
    status_step = find_step_with_key(summary.steps, "flit_tx_status")
    status_section = ""
    if status_step is not None:
        mv = status_step.measured_values
        status_section = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{metric_card('Flit TX Status', str(mv.get('flit_tx_status', 'N/A')), TEXT_SECONDARY)}"
            f"{metric_card('Flit RX Status', str(mv.get('flit_rx_status', 'N/A')), TEXT_SECONDARY)}"
            f"</div>"
        )

    _rendered = frozenset(
        {
            "cap_offset",
            "num_errors",
            "error_type",
            "inject_tx",
            "inject_rx",
            "flit_tx_status",
            "flit_rx_status",
            "entries_read",
            "expected_entries",
            "uncorrectable_raw",
            "correctable_raw",
            "entries_detected",
            "errors_injected",
            "match",
        }
    )
    extras = render_extra_measured_values(summary, _rendered)
    metrics = summary_metrics(summary)
    return (
        f"{header}{criteria}{metrics}{config_section}{verdict_section}"
        f"{drain_section}{aer_section}{status_section}{extras}"
    )


# ---------------------------------------------------------------------------
# SerDes Diagnostics
# ---------------------------------------------------------------------------


def render_serdes_diagnostics(summary: RecipeSummary) -> str:
    """Specialized renderer for serdes_diagnostics -- per-lane signal analysis."""
    header = section_header(
        "Endpoint SerDes Diagnostics",
        f"Duration: {summary.duration_ms:.0f}ms | "
        "Per-lane signal analysis of your endpoint's SerDes interface",
    )

    criteria = criteria_box(
        [
            "PASS: Zero UTP errors and zero FBER errors across all lanes",
            "WARN: UTP errors detected on one or more lanes",
            "UTP = User Test Pattern comparison (SerDes-level bit errors)",
        ]
    )

    # Summary cards
    diag_step = find_step_with_key(summary.steps, "lane_count")
    diag_cards = ""
    if diag_step is not None:
        mv = diag_step.measured_values
        lane_count = safe_int(mv.get("lane_count", 0))
        error_lanes = safe_int(mv.get("lanes_with_errors", 0))
        error_color = RED if error_lanes > 0 else GREEN
        diag_cards = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{metric_card('Total Lanes', str(lane_count), CYAN)}"
            f"{metric_card('Lanes with Errors', str(error_lanes), error_color)}"
            f"</div>"
        )

    # Per-lane SerDes diagnostic table
    lane_table = ""
    lanes_step = find_step_with_key(summary.steps, "lanes")
    if lanes_step is not None:
        lanes = lanes_step.measured_values.get("lanes", [])
        if isinstance(lanes, list) and lanes:
            lane_header = section_header("Per-Lane UTP Status", "")
            columns = ["Lane", "UTP Sync", "Error Count", "Expected Data", "Actual Data"]
            rows: list[list[str]] = []
            for lane_info in lanes:
                if not isinstance(lane_info, dict):
                    continue
                error_count = safe_int(lane_info.get("utp_error_count", 0))
                sync = lane_info.get("utp_sync", False)
                rows.append(
                    [
                        str(lane_info.get("lane", "")),
                        "SYNC" if sync else "NO_SYNC",
                        str(error_count),
                        str(lane_info.get("utp_expected_data", "")),
                        str(lane_info.get("utp_actual_data", "")),
                    ]
                )
            if rows:
                lane_table = lane_header + results_table(columns, rows, status_column=1)

    # EQ settings table
    eq_section = ""
    eq_step = find_step_with_key(summary.steps, "eq_settings")
    if eq_step is not None:
        eq_settings = eq_step.measured_values.get("eq_settings", [])
        if isinstance(eq_settings, list) and eq_settings:
            eq_header = section_header(
                "Endpoint TX EQ Settings",
                "Downstream = endpoint TX | Upstream = switch TX",
            )
            eq_columns = ["Lane", "DS TX Preset", "US TX Preset", "DS RX Hint", "US RX Hint"]
            eq_rows: list[list[str]] = []
            for lane_info in eq_settings:
                if not isinstance(lane_info, dict):
                    continue
                eq_rows.append(
                    [
                        str(lane_info.get("lane", "")),
                        f"P{lane_info.get('downstream_tx_preset', 'N/A')}",
                        f"P{lane_info.get('upstream_tx_preset', 'N/A')}",
                        str(lane_info.get("downstream_rx_preset_hint", "N/A")),
                        str(lane_info.get("upstream_rx_preset_hint", "N/A")),
                    ]
                )
            if eq_rows:
                eq_section = eq_header + results_table(eq_columns, eq_rows)

    # FBER lane counters (Gen6 only)
    fber_section = ""
    fber_step = find_step_with_key(summary.steps, "fber_total")
    if fber_step is not None:
        mv = fber_step.measured_values
        fber_total = safe_int(mv.get("fber_total", 0))
        flit_counter = mv.get("flit_counter", 0)
        fber_color = RED if fber_total > 0 else GREEN
        fber_cards = (
            f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin:12px 0;">'
            f"{metric_card('FBER Total', str(fber_total), fber_color)}"
            f"{metric_card('Flit Counter', str(flit_counter), CYAN)}"
            f"</div>"
        )

        lane_counters = mv.get("lane_counters", [])
        fber_chart = ""
        if isinstance(lane_counters, list) and lane_counters:
            chart_data = [(f"Lane {i}", float(c)) for i, c in enumerate(lane_counters)]
            fber_chart = section_header("FBER Errors per Lane", "") + bar_chart(
                chart_data, bar_color=RED if fber_total > 0 else GREEN, height_px=16
            )

        fber_section = fber_cards + fber_chart

    _rendered = frozenset(
        {
            "lane_count",
            "lanes_with_errors",
            "lanes",
            "lanes_read",
            "eq_settings",
            "fber_total",
            "flit_counter",
            "lane_counters",
        }
    )
    extras = render_extra_measured_values(summary, _rendered)
    metrics = summary_metrics(summary)
    return f"{header}{criteria}{metrics}{diag_cards}{lane_table}{eq_section}{fber_section}{extras}"
