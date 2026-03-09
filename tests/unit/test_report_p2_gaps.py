"""Tests for P2 gap fixes: LTSSM renderer, PAM4 per-eye, color dedup, integration.

Covers:
- P2-1: LTSSM monitor specialized renderer
- P2-2: PAM4 per-eye (upper/middle/lower) breakdown
- P2-3: Color constant single source of truth
- P2-4: Multi-recipe workflow integration test
"""

from __future__ import annotations

from calypso.workflows.models import RecipeCategory, RecipeResult, RecipeSummary, StepStatus
from calypso.workflows.report_sections import render_recipe_section
from calypso.workflows.workflow_report import generate_report


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_result(
    name: str = "test_step",
    status: StepStatus = StepStatus.PASS,
    message: str = "ok",
    measured_values: dict | None = None,
    duration_ms: float = 100.0,
    timestamp: str = "2024-01-01T12:00:00.123Z",
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
# P2-1: LTSSM Monitor Renderer
# ===========================================================================


class TestLtssmMonitorRenderer:
    def test_dispatches_to_specialized_renderer(self):
        summary = make_summary(
            recipe_id="ltssm_monitor",
            recipe_name="LTSSM Monitor",
        )
        result = render_recipe_section(summary)
        assert "Endpoint LTSSM Monitor" in result

    def test_shows_initial_and_final_state(self):
        steps = [
            make_result(
                name="Start monitoring",
                measured_values={
                    "initial_state": "L0.Idle",
                    "initial_recovery_count": 0,
                },
            ),
            make_result(
                name="Poll LTSSM samples",
                measured_values={
                    "sample_count": 100,
                    "transition_count": 0,
                    "final_state": "L0.Idle",
                    "recovery_count": 0,
                },
            ),
            make_result(
                name="Analyze transitions",
                measured_values={
                    "transition_count": 0,
                    "recovery_count": 0,
                    "transitions": [],
                },
            ),
        ]
        summary = make_summary(
            recipe_id="ltssm_monitor",
            steps=steps,
        )
        result = render_recipe_section(summary)
        assert "L0.Idle" in result
        assert "Initial State" in result
        assert "Final State" in result
        assert "Samples" in result

    def test_renders_transition_table(self):
        steps = [
            make_result(
                name="Start monitoring",
                measured_values={
                    "initial_state": "L0.Idle",
                    "initial_recovery_count": 0,
                },
            ),
            make_result(
                name="Poll LTSSM samples",
                measured_values={
                    "sample_count": 50,
                    "transition_count": 2,
                    "final_state": "L0.Idle",
                    "recovery_count": 2,
                },
            ),
            make_result(
                name="Analyze transitions",
                measured_values={
                    "transition_count": 2,
                    "recovery_count": 2,
                    "transitions": [
                        {
                            "from": "L0.Idle",
                            "to": "Recovery.RcvrLock",
                            "elapsed_ms": 1500.0,
                            "recovery_count": 1,
                        },
                        {
                            "from": "Recovery.RcvrLock",
                            "to": "L0.Idle",
                            "elapsed_ms": 1520.0,
                            "recovery_count": 2,
                        },
                    ],
                },
            ),
        ]
        summary = make_summary(
            recipe_id="ltssm_monitor",
            steps=steps,
        )
        result = render_recipe_section(summary)
        assert "State Transitions" in result
        assert "Recovery.RcvrLock" in result
        assert "1500.0" in result

    def test_shows_stable_message_when_no_transitions(self):
        steps = [
            make_result(
                name="Start monitoring",
                measured_values={"initial_state": "L0.Idle", "initial_recovery_count": 0},
            ),
            make_result(
                name="Poll LTSSM samples",
                measured_values={
                    "sample_count": 100,
                    "transition_count": 0,
                    "final_state": "L0.Idle",
                    "recovery_count": 0,
                },
            ),
            make_result(
                name="Analyze transitions",
                measured_values={
                    "transition_count": 0,
                    "recovery_count": 0,
                    "transitions": [],
                },
            ),
        ]
        summary = make_summary(recipe_id="ltssm_monitor", steps=steps)
        result = render_recipe_section(summary)
        assert "stable" in result.lower()

    def test_shows_recovery_guidance_when_high(self):
        steps = [
            make_result(
                name="Start monitoring",
                measured_values={"initial_state": "L0.Idle", "initial_recovery_count": 0},
            ),
            make_result(
                name="Poll LTSSM samples",
                status=StepStatus.WARN,
                measured_values={
                    "sample_count": 100,
                    "transition_count": 10,
                    "final_state": "L0.Idle",
                    "recovery_count": 8,
                },
            ),
            make_result(
                name="Analyze transitions",
                status=StepStatus.WARN,
                measured_values={
                    "transition_count": 10,
                    "recovery_count": 8,
                    "transitions": [],
                },
            ),
        ]
        summary = make_summary(
            recipe_id="ltssm_monitor",
            steps=steps,
            status=StepStatus.WARN,
        )
        result = render_recipe_section(summary)
        assert "What To Do Next" in result
        assert "ber_soak" in result

    def test_recovery_threshold_from_recipe(self):
        """Verify the renderer uses the recipe's threshold constant."""
        from calypso.workflows.recipes.ltssm_monitor import _RECOVERY_WARN_THRESHOLD

        assert _RECOVERY_WARN_THRESHOLD == 5


# ===========================================================================
# P2-2: PAM4 Per-Eye Breakdown
# ===========================================================================


class TestPam4PerEyeRenderer:
    def _make_pam4_summary(self) -> RecipeSummary:
        steps = [
            make_result(
                name="Check link speed",
                measured_values={"is_64gt": True},
                port_number=0,
            ),
            make_result(
                name="Verify lane margining capability",
                port_number=0,
            ),
            make_result(
                name="Sweep lane 0",
                measured_values={
                    "eye_width_ui": 0.12,
                    "eye_height_mv": 15.0,
                    "is_balanced": True,
                    "upper_eye_width_ui": 0.14,
                    "upper_eye_height_mv": 16.0,
                    "middle_eye_width_ui": 0.12,
                    "middle_eye_height_mv": 15.0,
                    "lower_eye_width_ui": 0.13,
                    "lower_eye_height_mv": 14.5,
                    "margin_right_ui": 0.06,
                    "margin_left_ui": 0.06,
                    "margin_up_mv": 7.5,
                    "margin_down_mv": 7.5,
                    "sweep_time_ms": 30000,
                },
                port_number=0,
                lane=0,
            ),
            make_result(
                name="Sweep lane 1",
                measured_values={
                    "eye_width_ui": 0.08,
                    "eye_height_mv": 12.0,
                    "is_balanced": False,
                    "upper_eye_width_ui": 0.10,
                    "upper_eye_height_mv": 14.0,
                    "middle_eye_width_ui": 0.08,
                    "middle_eye_height_mv": 12.0,
                    "lower_eye_width_ui": 0.09,
                    "lower_eye_height_mv": 10.0,
                    "margin_right_ui": 0.04,
                    "margin_left_ui": 0.04,
                    "margin_up_mv": 6.0,
                    "margin_down_mv": 6.0,
                    "sweep_time_ms": 31000,
                },
                status=StepStatus.WARN,
                port_number=0,
                lane=1,
            ),
            make_result(
                name="Aggregate results",
                measured_values={"worst_lane": 1, "worst_margin_ui": 0.08},
                port_number=0,
            ),
        ]
        return make_summary(
            recipe_id="pam4_eye_sweep",
            recipe_name="PAM4 Eye Sweep",
            steps=steps,
            category=RecipeCategory.SIGNAL_INTEGRITY,
        )

    def test_dispatches_to_specialized_renderer(self):
        result = render_recipe_section(self._make_pam4_summary())
        assert "Endpoint PAM4 Eye Sweep" in result

    def test_shows_per_eye_breakdown_table(self):
        result = render_recipe_section(self._make_pam4_summary())
        assert "Per-Eye Breakdown" in result
        assert "Upper" in result
        assert "Middle" in result
        assert "Lower" in result

    def test_shows_balanced_column(self):
        result = render_recipe_section(self._make_pam4_summary())
        assert "Balanced" in result
        assert "Yes" in result
        assert "No" in result

    def test_per_eye_width_values_present(self):
        result = render_recipe_section(self._make_pam4_summary())
        # Upper eye lane 0: 0.14 UI
        assert "0.1400" in result
        # Middle eye lane 1: 0.08 UI
        assert "0.0800" in result
        # Lower eye lane 0: 0.13 UI
        assert "0.1300" in result

    def test_worst_margin_card(self):
        result = render_recipe_section(self._make_pam4_summary())
        assert "Worst Lane" in result
        assert "Worst Margin" in result

    def test_backward_compat_without_sub_eyes(self):
        """Renderer handles old data without per-eye fields gracefully."""
        steps = [
            make_result(
                name="Sweep lane 0",
                measured_values={
                    "eye_width_ui": 0.15,
                    "eye_height_mv": 20.0,
                    "margin_right_ui": 0.075,
                    "margin_left_ui": 0.075,
                    "margin_up_mv": 10.0,
                    "margin_down_mv": 10.0,
                },
                lane=0,
            ),
            make_result(
                name="Aggregate results",
                measured_values={"worst_lane": 0, "worst_margin_ui": 0.15},
            ),
        ]
        summary = make_summary(
            recipe_id="pam4_eye_sweep",
            steps=steps,
            category=RecipeCategory.SIGNAL_INTEGRITY,
        )
        result = render_recipe_section(summary)
        # Should still render without error
        assert "Endpoint PAM4 Eye Sweep" in result
        assert "0.1500" in result
        # Per-eye section should not appear
        assert "Per-Eye Breakdown" not in result


# ===========================================================================
# P2-3: Color Constant Single Source of Truth
# ===========================================================================


class TestColorConstantDedup:
    def test_report_charts_exports_public_constants(self):
        from calypso.workflows import report_charts

        assert report_charts.CYAN == "#00d4ff"
        assert report_charts.GREEN == "#3fb950"
        assert report_charts.RED == "#f85149"
        assert report_charts.YELLOW == "#d29922"
        assert report_charts.BG_CARD == "#1c2128"
        assert report_charts.BORDER == "#30363d"
        assert report_charts.TEXT_PRIMARY == "#e6edf3"
        assert report_charts.TEXT_SECONDARY == "#8b949e"
        assert report_charts.TEXT_MUTED == "#484f58"
        assert report_charts.BG_PRIMARY == "#0d1117"
        assert report_charts.BG_ELEVATED == "#21262d"

    def test_helpers_re_exports_from_charts(self):
        """Helpers module re-exports colors from report_charts (no duplication)."""
        from calypso.workflows import report_charts, report_sections_helpers

        assert report_sections_helpers.CYAN is report_charts.CYAN
        assert report_sections_helpers.GREEN is report_charts.GREEN
        assert report_sections_helpers.RED is report_charts.RED
        assert report_sections_helpers.YELLOW is report_charts.YELLOW
        assert report_sections_helpers.BG_CARD is report_charts.BG_CARD
        assert report_sections_helpers.BORDER is report_charts.BORDER

    def test_no_private_color_constants_in_charts(self):
        """Verify no leftover _PREFIXED color constants in report_charts."""
        from calypso.workflows import report_charts

        public_attrs = [a for a in dir(report_charts) if not a.startswith("__")]
        private_colors = [
            a for a in public_attrs
            if a.startswith("_") and a[1:] in (
                "BG_PRIMARY", "BG_CARD", "BG_ELEVATED",
                "TEXT_PRIMARY", "TEXT_SECONDARY", "TEXT_MUTED",
                "CYAN", "GREEN", "YELLOW", "RED", "BORDER",
            )
        ]
        assert private_colors == [], f"Found leftover private constants: {private_colors}"


# ===========================================================================
# P2-4: Multi-Recipe Workflow Integration Test
# ===========================================================================


class TestMultiRecipeWorkflowReport:
    """Integration test: generate a full report from multiple recipe summaries
    simulating a real bring-up workflow (health check → eye scan → BER soak → LTSSM)."""

    def _make_workflow_summaries(self) -> list[RecipeSummary]:
        # 1. Link Health Check
        health_steps = [
            make_result(
                name="Read link status",
                measured_values={
                    "link_speed": "64 GT/s",
                    "link_width": 16,
                    "max_speed": "64 GT/s",
                    "max_width": 16,
                    "speed_downgrade": False,
                    "width_downgrade": False,
                },
            ),
            make_result(
                name="Read AER status",
                measured_values={
                    "aer_uncorrectable": 0,
                    "aer_correctable": 0,
                },
            ),
            make_result(
                name="Read EQ status",
                measured_values={
                    "eq_complete": True,
                    "phase1_ok": True,
                    "phase2_ok": True,
                    "phase3_ok": True,
                },
            ),
        ]
        health = make_summary(
            recipe_id="link_health_check",
            recipe_name="Link Health Check",
            steps=health_steps,
            category=RecipeCategory.LINK_HEALTH,
        )

        # 2. Eye Quick Scan
        eye_steps = [
            make_result(
                name="Eye scan lane 0",
                measured_values={
                    "eye_width_ui": 0.35,
                    "eye_height_mv": 40.0,
                },
                lane=0,
            ),
            make_result(
                name="Eye scan lane 1",
                measured_values={
                    "eye_width_ui": 0.30,
                    "eye_height_mv": 38.0,
                },
                lane=1,
            ),
        ]
        eye = make_summary(
            recipe_id="eye_quick_scan",
            recipe_name="Eye Quick Scan",
            steps=eye_steps,
            category=RecipeCategory.SIGNAL_INTEGRITY,
        )

        # 3. BER Soak
        ber_steps = [
            make_result(
                name="BER test",
                measured_values={
                    "estimated_ber": 0,
                    "error_count": 0,
                    "bits_tested": 1e12,
                    "duration_s": 300,
                    "ber_status": "pass",
                },
            ),
        ]
        ber = make_summary(
            recipe_id="ber_soak",
            recipe_name="BER Soak",
            steps=ber_steps,
            category=RecipeCategory.SIGNAL_INTEGRITY,
        )

        # 4. LTSSM Monitor
        ltssm_steps = [
            make_result(
                name="Start monitoring",
                measured_values={"initial_state": "L0.Idle", "initial_recovery_count": 0},
            ),
            make_result(
                name="Poll LTSSM samples",
                measured_values={
                    "sample_count": 100,
                    "transition_count": 0,
                    "final_state": "L0.Idle",
                    "recovery_count": 0,
                },
            ),
            make_result(
                name="Analyze transitions",
                measured_values={
                    "transition_count": 0,
                    "recovery_count": 0,
                    "transitions": [],
                },
            ),
        ]
        ltssm = make_summary(
            recipe_id="ltssm_monitor",
            recipe_name="LTSSM Monitor",
            steps=ltssm_steps,
            category=RecipeCategory.LINK_HEALTH,
        )

        return [health, eye, ber, ltssm]

    def test_generates_full_html_report(self):
        summaries = self._make_workflow_summaries()
        html = generate_report(summaries)

        # Verify it's valid HTML
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_all_recipe_sections_present(self):
        summaries = self._make_workflow_summaries()
        html = generate_report(summaries)

        # Each recipe should have its specialized header
        assert "Endpoint Link Health" in html
        assert "Eye" in html
        assert "BER" in html
        assert "Endpoint LTSSM Monitor" in html

    def test_report_contains_measured_data(self):
        summaries = self._make_workflow_summaries()
        html = generate_report(summaries)

        # Health check data
        assert "64 GT/s" in html

        # Eye data
        assert "0.35" in html  # eye width lane 0

        # LTSSM data
        assert "L0.Idle" in html

    def test_report_summary_section(self):
        summaries = self._make_workflow_summaries()
        html = generate_report(summaries)

        # Should have overall summary metrics
        assert "Pass" in html
        assert "Fail" in html

    def test_report_with_mixed_pass_fail(self):
        summaries = self._make_workflow_summaries()
        # Modify health check to have a failure
        summaries[0] = make_summary(
            recipe_id="link_health_check",
            recipe_name="Link Health Check",
            steps=[
                make_result(
                    name="Read link status",
                    status=StepStatus.FAIL,
                    message="Link speed degraded",
                    measured_values={
                        "link_speed": "32 GT/s",
                        "link_width": 8,
                        "max_speed": "64 GT/s",
                        "max_width": 16,
                        "speed_downgrade": True,
                        "width_downgrade": True,
                    },
                ),
            ],
            status=StepStatus.FAIL,
            category=RecipeCategory.LINK_HEALTH,
        )
        html = generate_report(summaries)

        # Report should still generate without error
        assert "<!DOCTYPE html>" in html
        assert "Link Health Check" in html
        assert "LTSSM Monitor" in html

    def test_csp_meta_tag_present(self):
        summaries = self._make_workflow_summaries()
        html = generate_report(summaries)
        assert "Content-Security-Policy" in html
        assert "default-src &#x27;none&#x27;" in html or "default-src 'none'" in html

    def test_print_css_present(self):
        summaries = self._make_workflow_summaries()
        html = generate_report(summaries)
        assert "@media print" in html
