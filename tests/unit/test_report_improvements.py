"""Tests for P1/P2 report improvements.

Covers:
- 4 new specialized renderers (eq_phase_audit, error_recovery_test,
  flit_error_injection, serdes_diagnostics)
- TX EQ coefficients in PHY 64GT audit
- Eye width/height bar charts in eye_quick_scan and pam4_eye_sweep
- Expanded comparison report metrics
- Port sweep reframe for endpoint validation
- Environment metadata in generate_report
- render_step_details helper
"""

from __future__ import annotations

from calypso.workflows.models import RecipeCategory, RecipeResult, RecipeSummary, StepStatus
from calypso.workflows.report_comparison import (
    _extract_key_metrics,
    generate_comparison_report,
)
from calypso.workflows.report_sections import render_recipe_section
from calypso.workflows.report_sections_helpers import render_step_details
from calypso.workflows.workflow_report import generate_report, generate_single_report


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_result(
    name: str = "test_step",
    status: StepStatus = StepStatus.PASS,
    message: str = "ok",
    measured_values: dict | None = None,
    duration_ms: float = 100.0,
    timestamp: str = "2024-01-01T00:00:00Z",
    details: str = "",
    port_number: int | None = None,
    lane: int | None = None,
) -> RecipeResult:
    return RecipeResult(
        step_name=name,
        status=status,
        message=message,
        measured_values=measured_values or {},
        duration_ms=duration_ms,
        timestamp=timestamp,
        details=details,
        port_number=port_number,
        lane=lane,
    )


def make_summary(
    recipe_id: str = "test",
    recipe_name: str = "Test Recipe",
    steps: list[RecipeResult] | None = None,
    status: StepStatus = StepStatus.PASS,
    category: RecipeCategory = RecipeCategory.LINK_HEALTH,
    parameters: dict | None = None,
) -> RecipeSummary:
    steps = steps or [make_result()]
    return RecipeSummary(
        recipe_id=recipe_id,
        recipe_name=recipe_name,
        category=category,
        status=status,
        steps=steps,
        total_pass=sum(1 for s in steps if s.status == StepStatus.PASS),
        total_fail=sum(1 for s in steps if s.status == StepStatus.FAIL),
        total_warn=sum(1 for s in steps if s.status == StepStatus.WARN),
        duration_ms=sum(s.duration_ms for s in steps),
        parameters=parameters or {},
    )


# ===========================================================================
# Item 1a: EQ Phase Audit Renderer
# ===========================================================================


class TestEqPhaseAuditRenderer:
    def test_dispatches_to_specialized_renderer(self):
        summary = make_summary(
            recipe_id="eq_phase_audit",
            recipe_name="EQ Phase Audit",
        )
        result = render_recipe_section(summary)
        assert "Endpoint EQ Negotiation Audit" in result
        assert len(result) > 100

    def test_renders_per_speed_eq_status(self):
        steps = [
            make_result(
                name="Read link status",
                measured_values={"current_speed": "64 GT/s", "current_width": 16},
            ),
            make_result(
                name="Read 16GT EQ status",
                measured_values={
                    "eq_complete": True,
                    "phase1_ok": True,
                    "phase2_ok": True,
                    "phase3_ok": True,
                },
            ),
            make_result(
                name="Read 64GT EQ status",
                measured_values={
                    "eq_complete": True,
                    "phase1_ok": True,
                    "phase2_ok": True,
                    "phase3_ok": True,
                    "flit_mode_supported": True,
                },
            ),
            make_result(
                name="Analyze EQ consistency",
                measured_values={"eq_incomplete": False},
            ),
        ]
        summary = make_summary(recipe_id="eq_phase_audit", steps=steps)
        result = render_recipe_section(summary)
        assert "PASS" in result
        assert "16 GT/s" in result
        assert "64 GT/s" in result
        assert "Flit Mode" in result

    def test_renders_per_lane_eq_settings(self):
        steps = [
            make_result(
                name="Read 16GT per-lane EQ settings",
                measured_values={
                    "lanes_read": 2,
                    "unique_tx_presets": 1,
                    "eq_settings": [
                        {
                            "lane": 0,
                            "downstream_tx_preset": 5,
                            "upstream_tx_preset": 7,
                            "downstream_rx_preset_hint": 0,
                            "upstream_rx_preset_hint": 0,
                        },
                        {
                            "lane": 1,
                            "downstream_tx_preset": 5,
                            "upstream_tx_preset": 7,
                            "downstream_rx_preset_hint": 0,
                            "upstream_rx_preset_hint": 0,
                        },
                    ],
                },
            ),
        ]
        summary = make_summary(recipe_id="eq_phase_audit", steps=steps)
        result = render_recipe_section(summary)
        assert "Per-Lane EQ Settings" in result
        assert "DS TX Preset" in result
        assert "Downstream = endpoint TX" in result

    def test_handles_missing_eq_data(self):
        summary = make_summary(recipe_id="eq_phase_audit", steps=[make_result()])
        result = render_recipe_section(summary)
        assert "Endpoint EQ Negotiation Audit" in result

    def test_eq_incomplete_status(self):
        steps = [
            make_result(
                name="Analyze EQ consistency",
                measured_values={"eq_incomplete": True},
            ),
        ]
        summary = make_summary(recipe_id="eq_phase_audit", steps=steps)
        result = render_recipe_section(summary)
        assert "INCOMPLETE" in result


# ===========================================================================
# Item 1b: Error Recovery Test Renderer
# ===========================================================================


class TestErrorRecoveryRenderer:
    def test_dispatches_to_specialized_renderer(self):
        summary = make_summary(
            recipe_id="error_recovery_test",
            recipe_name="Error Recovery Test",
        )
        result = render_recipe_section(summary)
        assert "Endpoint Error Recovery Test" in result

    def test_renders_baseline_info(self):
        steps = [
            make_result(
                name="Record baseline",
                measured_values={
                    "baseline_speed": "64 GT/s",
                    "baseline_width": 16,
                    "baseline_recovery_count": 0,
                },
            ),
        ]
        summary = make_summary(recipe_id="error_recovery_test", steps=steps)
        result = render_recipe_section(summary)
        assert "Baseline Speed" in result
        assert "64 GT/s" in result

    def test_renders_per_attempt_results(self):
        steps = [
            make_result(
                name="Record baseline",
                measured_values={
                    "baseline_speed": "64 GT/s",
                    "baseline_width": 16,
                    "baseline_recovery_count": 0,
                },
            ),
            make_result(
                name="Recovery attempt 1",
                measured_values={
                    "attempt": 1,
                    "post_speed": "64 GT/s",
                    "post_width": 16,
                    "recovery_delta": 1,
                    "has_uncorrectable": False,
                    "has_correctable": False,
                },
            ),
            make_result(
                name="Recovery attempt 2",
                status=StepStatus.WARN,
                measured_values={
                    "attempt": 2,
                    "post_speed": "64 GT/s",
                    "post_width": 16,
                    "recovery_delta": 1,
                    "has_uncorrectable": False,
                    "has_correctable": True,
                },
            ),
            make_result(
                name="Final assessment",
                measured_values={
                    "total_attempts": 2,
                    "clean_count": 1,
                    "transient_error_count": 1,
                    "degraded_count": 0,
                },
            ),
        ]
        summary = make_summary(recipe_id="error_recovery_test", steps=steps)
        result = render_recipe_section(summary)
        assert "Per-Attempt Results" in result
        assert "1/2" in result  # clean/total
        assert "Transient Errors" in result
        assert "Degraded" in result

    def test_dut_framing_language(self):
        summary = make_summary(recipe_id="error_recovery_test")
        result = render_recipe_section(summary)
        assert "endpoint" in result.lower()
        assert "forced link retraining" in result.lower()


# ===========================================================================
# Item 1c: Flit Error Injection Renderer
# ===========================================================================


class TestFlitErrorInjectionRenderer:
    def test_dispatches_to_specialized_renderer(self):
        summary = make_summary(
            recipe_id="flit_error_injection",
            recipe_name="Flit Error Injection",
        )
        result = render_recipe_section(summary)
        assert "Flit Error Injection Verification" in result

    def test_renders_injection_config(self):
        steps = [
            make_result(
                name="Configure injection",
                measured_values={
                    "num_errors": 5,
                    "error_type": 0,
                    "inject_tx": True,
                    "inject_rx": False,
                },
            ),
        ]
        summary = make_summary(recipe_id="flit_error_injection", steps=steps)
        result = render_recipe_section(summary)
        assert "Errors Injected" in result
        assert "CRC" in result
        assert "TX Path" in result

    def test_renders_injection_verdict(self):
        steps = [
            make_result(
                name="Verify injection results",
                measured_values={
                    "entries_detected": 5,
                    "errors_injected": 5,
                    "match": True,
                },
            ),
        ]
        summary = make_summary(recipe_id="flit_error_injection", steps=steps)
        result = render_recipe_section(summary)
        assert "Match" in result
        assert "YES" in result

    def test_renders_aer_status(self):
        steps = [
            make_result(
                name="Check post-injection AER",
                measured_values={
                    "uncorrectable_raw": 0,
                    "correctable_raw": 0,
                },
            ),
        ]
        summary = make_summary(recipe_id="flit_error_injection", steps=steps)
        result = render_recipe_section(summary)
        assert "Uncorrectable AER" in result
        assert "0x00000000" in result

    def test_dut_framing_language(self):
        summary = make_summary(recipe_id="flit_error_injection")
        result = render_recipe_section(summary)
        assert "endpoint" in result.lower()


# ===========================================================================
# Item 1d: SerDes Diagnostics Renderer
# ===========================================================================


class TestSerDesDiagnosticsRenderer:
    def test_dispatches_to_specialized_renderer(self):
        summary = make_summary(
            recipe_id="serdes_diagnostics",
            recipe_name="SerDes Diagnostics",
        )
        result = render_recipe_section(summary)
        assert "Endpoint SerDes Diagnostics" in result

    def test_renders_per_lane_utp_table(self):
        steps = [
            make_result(
                name="Read SerDes diagnostics",
                measured_values={
                    "lane_count": 2,
                    "lanes_with_errors": 1,
                    "lanes": [
                        {
                            "lane": 0,
                            "utp_sync": True,
                            "utp_error_count": 0,
                            "utp_expected_data": "0xAAAA",
                            "utp_actual_data": "0xAAAA",
                        },
                        {
                            "lane": 1,
                            "utp_sync": True,
                            "utp_error_count": 5,
                            "utp_expected_data": "0xAAAA",
                            "utp_actual_data": "0xBBBB",
                        },
                    ],
                },
            ),
        ]
        summary = make_summary(recipe_id="serdes_diagnostics", steps=steps)
        result = render_recipe_section(summary)
        assert "Per-Lane UTP Status" in result
        assert "UTP Sync" in result
        assert "Error Count" in result

    def test_renders_eq_settings(self):
        steps = [
            make_result(
                name="Read TX EQ coefficients",
                measured_values={
                    "lanes_read": 2,
                    "eq_settings": [
                        {
                            "lane": 0,
                            "downstream_tx_preset": 5,
                            "upstream_tx_preset": 7,
                        },
                    ],
                },
            ),
        ]
        summary = make_summary(recipe_id="serdes_diagnostics", steps=steps)
        result = render_recipe_section(summary)
        assert "Endpoint TX EQ Settings" in result
        assert "DS TX Preset" in result

    def test_renders_fber_counters(self):
        steps = [
            make_result(
                name="Read FBER lane counters",
                measured_values={
                    "fber_total": 0,
                    "flit_counter": 1000,
                    "lane_counters": [0, 0, 0, 0],
                },
            ),
        ]
        summary = make_summary(recipe_id="serdes_diagnostics", steps=steps)
        result = render_recipe_section(summary)
        assert "FBER Total" in result
        assert "Flit Counter" in result

    def test_dut_framing_language(self):
        summary = make_summary(recipe_id="serdes_diagnostics")
        result = render_recipe_section(summary)
        assert "endpoint" in result.lower()


# ===========================================================================
# Item 2: TX EQ Coefficients in PHY 64GT Audit
# ===========================================================================


class TestPhyAuditTxEq:
    def test_renders_tx_eq_table(self):
        steps = [
            make_result(
                name="Read link capabilities",
                measured_values={
                    "gen6_supported": True,
                    "gen5_supported": True,
                    "gen4_supported": True,
                },
            ),
            make_result(
                name="Read TX EQ coefficients",
                measured_values={
                    "tx_eq_lanes": [
                        {
                            "lane": 0,
                            "downstream_tx_preset": 5,
                            "upstream_tx_preset": 7,
                            "downstream_pre_cursor": -3.5,
                            "downstream_cursor": 24.0,
                            "downstream_post_cursor": -6.0,
                            "upstream_pre_cursor": 0.0,
                            "upstream_cursor": 24.0,
                            "upstream_post_cursor": 0.0,
                        },
                    ]
                },
            ),
        ]
        summary = make_summary(recipe_id="phy_64gt_audit", steps=steps)
        result = render_recipe_section(summary)
        assert "Endpoint TX EQ Coefficients" in result
        assert "DS TX Preset" in result
        assert "DS Pre" in result
        assert "DS Cursor" in result
        assert "DS Post" in result
        assert "P5" in result  # preset value
        assert "-3.5" in result  # pre_cursor coefficient
        # Should NOT be in "Additional Measurements" anymore
        assert (
            "tx_eq_lanes" not in result.split("Additional Measurements")[-1]
            if "Additional Measurements" in result
            else True
        )

    def test_no_tx_eq_data_graceful(self):
        steps = [
            make_result(
                name="Read link capabilities",
                measured_values={"gen6_supported": True},
            ),
        ]
        summary = make_summary(recipe_id="phy_64gt_audit", steps=steps)
        result = render_recipe_section(summary)
        assert "PHY 64GT Audit" in result
        # No crash when tx_eq_lanes is missing


# ===========================================================================
# Item 3: Eye Width/Height Bar Charts
# ===========================================================================


class TestEyeBarCharts:
    def _eye_steps(self) -> list[RecipeResult]:
        return [
            make_result(
                name="Lane 0 eye scan",
                measured_values={
                    "eye_width_ui": 0.20,
                    "eye_height_mv": 50.0,
                    "margin_right_ui": 0.10,
                    "margin_left_ui": 0.10,
                    "margin_up_mv": 25.0,
                    "margin_down_mv": 25.0,
                    "link_speed": "64 GT/s",
                    "link_width": 16,
                    "lane": 0,
                },
                lane=0,
            ),
            make_result(
                name="Lane 1 eye scan",
                measured_values={
                    "eye_width_ui": 0.15,
                    "eye_height_mv": 40.0,
                    "margin_right_ui": 0.08,
                    "margin_left_ui": 0.07,
                    "margin_up_mv": 20.0,
                    "margin_down_mv": 20.0,
                    "lane": 1,
                },
                lane=1,
            ),
        ]

    def test_eye_scan_has_width_chart(self):
        summary = make_summary(recipe_id="eye_quick_scan", steps=self._eye_steps())
        result = render_recipe_section(summary)
        assert "Eye Width per Lane (UI)" in result
        assert "Lane 0" in result

    def test_eye_scan_has_height_chart(self):
        summary = make_summary(recipe_id="eye_quick_scan", steps=self._eye_steps())
        result = render_recipe_section(summary)
        assert "Eye Height per Lane (mV)" in result

    def test_eye_scan_thresholds_shown(self):
        summary = make_summary(recipe_id="eye_quick_scan", steps=self._eye_steps())
        result = render_recipe_section(summary)
        assert "0.15 UI" in result
        assert "0.08 UI" in result

    def test_pam4_has_width_chart(self):
        summary = make_summary(recipe_id="pam4_eye_sweep", steps=self._eye_steps())
        result = render_recipe_section(summary)
        assert "Eye Width per Lane (UI)" in result

    def test_pam4_has_height_chart(self):
        summary = make_summary(recipe_id="pam4_eye_sweep", steps=self._eye_steps())
        result = render_recipe_section(summary)
        assert "Eye Height per Lane (mV)" in result

    def test_pam4_thresholds_shown(self):
        summary = make_summary(recipe_id="pam4_eye_sweep", steps=self._eye_steps())
        result = render_recipe_section(summary)
        assert "0.10 UI" in result
        assert "0.05 UI" in result

    def test_no_eye_data_no_charts(self):
        summary = make_summary(recipe_id="eye_quick_scan", steps=[make_result()])
        result = render_recipe_section(summary)
        assert "Eye Width per Lane" not in result


# ===========================================================================
# Item 4: Expanded Comparison Report Metrics
# ===========================================================================


class TestExpandedComparisonMetrics:
    def test_extracts_eye_width_from_per_lane_steps(self):
        steps = [
            make_result(
                name="Lane 0", measured_values={"eye_width_ui": 0.20, "eye_height_mv": 50.0}, lane=0
            ),
            make_result(
                name="Lane 1", measured_values={"eye_width_ui": 0.15, "eye_height_mv": 40.0}, lane=1
            ),
        ]
        summary = make_summary(steps=steps)
        metrics = _extract_key_metrics(summary)
        assert "worst_eye_width" in metrics
        assert metrics["worst_eye_width"] == 0.15
        assert "worst_eye_height" in metrics
        assert metrics["worst_eye_height"] == 40.0

    def test_extracts_recovery_metrics(self):
        steps = [
            make_result(
                name="Final assessment",
                measured_values={
                    "clean_count": 3,
                    "degraded_count": 0,
                    "transient_error_count": 1,
                },
            ),
        ]
        summary = make_summary(steps=steps)
        metrics = _extract_key_metrics(summary)
        assert "clean_count" in metrics
        assert metrics["clean_count"] == 3.0
        assert "degraded_count" in metrics
        assert "transient_error_count" in metrics

    def test_extracts_fber_metrics(self):
        steps = [
            make_result(
                name="Read FBER",
                measured_values={"fber_total": 5, "lanes_with_errors": 2},
            ),
        ]
        summary = make_summary(steps=steps)
        metrics = _extract_key_metrics(summary)
        assert "fber_total" in metrics
        assert metrics["fber_total"] == 5.0
        assert "lanes_with_errors" in metrics

    def test_walks_all_steps_not_just_richest(self):
        steps = [
            make_result(name="Step A", measured_values={"total_errors": 0}),
            make_result(name="Step B", measured_values={"clean_count": 3, "degraded_count": 1}),
        ]
        summary = make_summary(steps=steps)
        metrics = _extract_key_metrics(summary)
        # Should find both total_errors from step A and clean_count from step B
        assert "total_errors" in metrics
        assert "clean_count" in metrics

    def test_aggregates_recovery_delta(self):
        steps = [
            make_result(name="Attempt 1", measured_values={"recovery_delta": 2}),
            make_result(name="Attempt 2", measured_values={"recovery_delta": 3}),
        ]
        summary = make_summary(steps=steps)
        metrics = _extract_key_metrics(summary)
        assert "total_recovery_delta" in metrics
        assert metrics["total_recovery_delta"] == 5.0

    def test_backward_compatible_with_old_format(self):
        """Old-style summaries without new keys still extract correctly."""
        steps = [
            make_result(
                name="Analysis",
                measured_values={
                    "total_errors": 0,
                    "estimated_ber": 1e-12,
                    "bits_tested": 1e12,
                    "lanes": [
                        {"lane": 0, "estimated_ber": 1e-13},
                        {"lane": 1, "estimated_ber": 5e-13},
                    ],
                },
            ),
        ]
        summary = make_summary(steps=steps)
        metrics = _extract_key_metrics(summary)
        assert "total_errors" in metrics
        assert "estimated_ber" in metrics
        assert "worst_lane_ber" in metrics
        assert metrics["worst_lane_ber"] == 5e-13

    def test_comparison_report_renders_new_metrics(self):
        baseline = [
            make_summary(
                recipe_id="eye_quick_scan",
                recipe_name="Eye Quick Scan",
                steps=[
                    make_result(measured_values={"eye_width_ui": 0.20, "eye_height_mv": 50.0}),
                ],
            ),
        ]
        current = [
            make_summary(
                recipe_id="eye_quick_scan",
                recipe_name="Eye Quick Scan",
                steps=[
                    make_result(measured_values={"eye_width_ui": 0.18, "eye_height_mv": 45.0}),
                ],
            ),
        ]
        result = generate_comparison_report(baseline, current)
        assert "<!DOCTYPE html>" in result
        assert "Eye Quick Scan" in result


# ===========================================================================
# Item 5: Port Sweep Reframe
# ===========================================================================


class TestPortSweepReframe:
    def test_header_says_endpoint_link_status(self):
        steps = [
            make_result(
                name="Port 0",
                measured_values={
                    "port_number": 0,
                    "is_link_up": True,
                    "link_speed": "64 GT/s",
                    "link_width": 16,
                    "role": "downstream",
                },
            ),
        ]
        summary = make_summary(recipe_id="all_port_sweep", steps=steps)
        result = render_recipe_section(summary)
        assert "Endpoint Link Status" in result

    def test_single_device_prominent_display(self):
        steps = [
            make_result(
                name="Port 0",
                measured_values={
                    "port_number": 0,
                    "is_link_up": True,
                    "link_speed": "64 GT/s",
                    "link_width": 16,
                    "role": "downstream",
                },
            ),
            make_result(
                name="Port 1",
                measured_values={
                    "port_number": 1,
                    "is_link_up": False,
                    "link_speed": "",
                    "link_width": 0,
                    "role": "",
                },
            ),
        ]
        summary = make_summary(recipe_id="all_port_sweep", steps=steps)
        result = render_recipe_section(summary)
        assert "DUT Port" in result  # single-device highlight
        assert "Active Downstream Links (DUT)" in result

    def test_downstream_upstream_separation(self):
        steps = [
            make_result(
                name="Port 0",
                measured_values={
                    "port_number": 0,
                    "is_link_up": True,
                    "link_speed": "64 GT/s",
                    "link_width": 16,
                    "role": "downstream",
                },
            ),
            make_result(
                name="Port 16",
                measured_values={
                    "port_number": 16,
                    "is_link_up": True,
                    "link_speed": "16 GT/s",
                    "link_width": 16,
                    "role": "upstream",
                },
            ),
        ]
        summary = make_summary(recipe_id="all_port_sweep", steps=steps)
        result = render_recipe_section(summary)
        assert "Active Downstream Links" in result
        assert "Active Upstream Links" in result

    def test_inactive_ports_collapsed(self):
        steps = [
            make_result(
                name="Port 0",
                measured_values={
                    "port_number": 0,
                    "is_link_up": False,
                    "link_speed": "",
                    "link_width": 0,
                    "role": "",
                },
            ),
        ]
        summary = make_summary(recipe_id="all_port_sweep", steps=steps)
        result = render_recipe_section(summary)
        assert "Inactive Ports" in result
        assert "<details" in result

    def test_station_column_present(self):
        steps = [
            make_result(
                name="Port 32",
                measured_values={
                    "port_number": 32,
                    "is_link_up": True,
                    "link_speed": "64 GT/s",
                    "link_width": 16,
                    "role": "downstream",
                },
            ),
        ]
        summary = make_summary(recipe_id="all_port_sweep", steps=steps)
        result = render_recipe_section(summary)
        assert "Station" in result


# ===========================================================================
# Item 6: Environment Metadata
# ===========================================================================


class TestEnvironmentMetadata:
    def test_environment_rendered_in_report(self):
        result = generate_report(
            [make_summary()],
            environment={
                "os": "Windows",
                "os_version": "11.0.26200",
                "sdk_version": "23.2.44.0",
                "board_profile": "PEX90096 B0",
            },
        )
        assert "Test Environment" in result
        assert "Operating System" in result
        assert "Windows" in result
        assert "PLX SDK Version" in result
        assert "23.2.44.0" in result

    def test_environment_none_no_section(self):
        result = generate_report([make_summary()], environment=None)
        assert "Test Environment" not in result

    def test_environment_empty_values_filtered(self):
        result = generate_report(
            [make_summary()],
            environment={"os": "Linux", "sdk_version": ""},
        )
        assert "Linux" in result
        assert "PLX SDK Version" not in result

    def test_single_report_passes_environment(self):
        result = generate_single_report(
            make_summary(),
            environment={"os": "Linux", "driver_version": "1.2.3"},
        )
        assert "Test Environment" in result
        assert "Driver Version" in result

    def test_downstream_device_info(self):
        result = generate_report(
            [make_summary()],
            environment={
                "downstream_bdf": "0000:03:00.0",
                "downstream_vendor_id": "0x1234",
                "downstream_device_id": "0x5678",
            },
        )
        assert "Downstream BDF" in result
        assert "0000:03:00.0" in result
        assert "Downstream Vendor ID" in result


# ===========================================================================
# Item 7: render_step_details
# ===========================================================================


class TestRenderStepDetails:
    def test_renders_details_field(self):
        steps = [
            make_result(
                name="Register dump",
                details="REG 0x100: 0xDEADBEEF\nREG 0x104: 0xCAFEBABE",
            ),
        ]
        result = render_step_details(steps)
        assert "Diagnostic Details" in result
        assert "Register dump" in result
        assert "0xDEADBEEF" in result
        assert "<pre" in result

    def test_no_details_returns_empty(self):
        steps = [make_result(details="")]
        result = render_step_details(steps)
        assert result == ""

    def test_html_escapes_details(self):
        steps = [make_result(details="<script>alert(1)</script>")]
        result = render_step_details(steps)
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_multiple_steps_with_details(self):
        steps = [
            make_result(name="Step A", details="Detail A"),
            make_result(name="Step B", details="Detail B"),
            make_result(name="Step C", details=""),
        ]
        result = render_step_details(steps)
        assert "Step A" in result
        assert "Step B" in result
        assert "Step C" not in result
        assert "Detail A" in result
        assert "Detail B" in result

    def test_details_appended_by_render_recipe_section(self):
        steps = [
            make_result(
                name="Diagnostic step",
                details="Raw register data: 0xFF",
            ),
        ]
        summary = make_summary(recipe_id="unregistered", steps=steps)
        result = render_recipe_section(summary)
        assert "Diagnostic Details" in result
        assert "Raw register data: 0xFF" in result

    def test_details_appended_to_specialized_renderers(self):
        steps = [
            make_result(
                name="Read link capabilities",
                measured_values={"gen6_supported": True},
                details="Extended cap at 0x100",
            ),
        ]
        summary = make_summary(recipe_id="phy_64gt_audit", steps=steps)
        result = render_recipe_section(summary)
        assert "Diagnostic Details" in result
        assert "Extended cap at 0x100" in result
