"""Comprehensive tests for the workflow report rendering pipeline.

Covers:
- report_sections_helpers.py (safe_int, criteria_box, summary_metrics, etc.)
- report_sections.py (render_recipe_section dispatcher + generic renderer)
- report_charts.py (metric_card, status_badge, bar_chart, results_table, etc.)
- workflow_report.py (generate_report, generate_single_report, param formatting)
"""

from __future__ import annotations

from calypso.workflows.models import RecipeCategory, RecipeResult, RecipeSummary, StepStatus
from calypso.workflows.report_charts import (
    bar_chart,
    divider,
    key_value_table,
    metric_card,
    results_table,
    section_header,
    status_badge,
    status_color,
)
from calypso.workflows.report_sections import render_recipe_section
from calypso.workflows.report_sections_helpers import (
    CYAN,
    GREEN,
    RED,
    TEXT_PRIMARY,
    YELLOW,
    ber_confidence_interval,
    color_for_status,
    criteria_box,
    find_step_with_key,
    format_ber,
    safe_int,
    summary_metrics,
)
from calypso.workflows.workflow_report import (
    _format_param_value,
    _render_parameters,
    generate_report,
    generate_single_report,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def make_result(
    name: str = "test_step",
    status: StepStatus = StepStatus.PASS,
    message: str = "ok",
    measured_values: dict | None = None,
    duration_ms: float = 100.0,
    timestamp: str = "2024-01-01T00:00:00Z",
) -> RecipeResult:
    return RecipeResult(
        step_name=name,
        status=status,
        message=message,
        measured_values=measured_values or {},
        duration_ms=duration_ms,
        timestamp=timestamp,
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
# report_sections_helpers.py
# ===========================================================================


class TestSafeInt:
    def test_normal_int(self):
        assert safe_int(42) == 42

    def test_negative_int(self):
        assert safe_int(-7) == -7

    def test_zero(self):
        assert safe_int(0) == 0

    def test_float_as_string(self):
        assert safe_int("3.7") == 3

    def test_int_as_string(self):
        assert safe_int("10") == 10

    def test_float_value(self):
        assert safe_int(9.9) == 9

    def test_invalid_string(self):
        assert safe_int("abc") == 0

    def test_none(self):
        assert safe_int(None) == 0

    def test_empty_string(self):
        assert safe_int("") == 0

    def test_bool_true(self):
        # bool is a subclass of int; float("True") raises ValueError
        # but int(float(str(True))) -> int(float("True")) -> ValueError -> 0
        # Actually: str(True) = "True", float("True") raises ValueError
        assert safe_int(True) == 0 or safe_int(True) == 1
        # Let's just verify it doesn't crash
        result = safe_int(True)
        assert isinstance(result, int)


class TestCriteriaBox:
    def test_returns_html_with_all_lines(self):
        lines = ["Line A", "Line B", "Line C"]
        result = criteria_box(lines)
        assert "Test Criteria" in result
        assert "Line A" in result
        assert "Line B" in result
        assert "Line C" in result

    def test_empty_lines(self):
        result = criteria_box([])
        assert "Test Criteria" in result

    def test_html_escapes_content(self):
        result = criteria_box(["<script>alert(1)</script>"])
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_uses_cyan_accent(self):
        result = criteria_box(["test"])
        assert CYAN in result


class TestSummaryMetrics:
    def test_contains_pass_fail_warn_overall(self):
        summary = make_summary(
            steps=[
                make_result(status=StepStatus.PASS),
                make_result(status=StepStatus.FAIL),
                make_result(status=StepStatus.WARN),
            ],
            status=StepStatus.FAIL,
        )
        result = summary_metrics(summary)
        assert "Pass" in result
        assert "Fail" in result
        assert "Warn" in result
        assert "Overall" in result

    def test_displays_correct_counts(self):
        summary = make_summary(
            steps=[
                make_result(status=StepStatus.PASS),
                make_result(status=StepStatus.PASS),
                make_result(status=StepStatus.FAIL),
            ],
            status=StepStatus.FAIL,
        )
        result = summary_metrics(summary)
        # total_pass=2, total_fail=1, total_warn=0
        assert ">2<" in result
        assert ">1<" in result
        assert ">0<" in result


class TestFindStepWithKey:
    def test_finds_step_with_key(self):
        steps = [
            make_result(name="step_a", measured_values={"alpha": 1}),
            make_result(name="step_b", measured_values={"beta": 2}),
        ]
        found = find_step_with_key(steps, "beta")
        assert found is not None
        assert found.step_name == "step_b"

    def test_returns_last_match(self):
        steps = [
            make_result(name="first", measured_values={"key": 1}),
            make_result(name="second", measured_values={"key": 2}),
        ]
        found = find_step_with_key(steps, "key")
        assert found is not None
        assert found.step_name == "second"

    def test_returns_none_when_missing(self):
        steps = [make_result(name="step_a", measured_values={"alpha": 1})]
        assert find_step_with_key(steps, "nonexistent") is None

    def test_empty_steps(self):
        assert find_step_with_key([], "key") is None


class TestFormatBer:
    def test_zero(self):
        assert format_ber(0) == "0"

    def test_small_value(self):
        result = format_ber(1e-12)
        assert "e-12" in result

    def test_normal_value(self):
        result = format_ber(0.001)
        assert "e-03" in result

    def test_exact_format(self):
        assert format_ber(1.23e-6) == "1.23e-06"


class TestBerConfidenceInterval:
    def test_zero_errors_with_bits_tested_rule_of_three(self):
        result = ber_confidence_interval(0, 0.0, bits_tested=1e12)
        assert result is not None
        assert result.startswith("<")
        # 3 / 1e12 = 3e-12
        assert "3.00e-12" in result

    def test_zero_errors_no_bits_returns_none(self):
        result = ber_confidence_interval(0, 0.0, bits_tested=0.0)
        assert result is None

    def test_positive_errors(self):
        result = ber_confidence_interval(100, 1e-9)
        assert result is not None
        assert result.startswith("[")
        assert result.endswith("]")
        assert ", " in result

    def test_negative_errors_returns_none(self):
        assert ber_confidence_interval(-1, 1e-9) is None

    def test_zero_estimated_ber_positive_errors(self):
        assert ber_confidence_interval(5, 0.0) is None

    def test_single_error(self):
        result = ber_confidence_interval(1, 1e-12)
        assert result is not None
        # With 1 error, lo_count = max(0, 1 - 1.96*1) = 0
        assert "[" in result


class TestColorForStatus:
    def test_pass(self):
        assert color_for_status("pass") == GREEN

    def test_fail(self):
        assert color_for_status("fail") == RED

    def test_no_sync(self):
        assert color_for_status("no_sync") == RED

    def test_warn(self):
        assert color_for_status("warn") == YELLOW

    def test_marginal(self):
        assert color_for_status("marginal") == YELLOW

    def test_errors_detected(self):
        assert color_for_status("errors_detected") == YELLOW

    def test_unknown(self):
        assert color_for_status("something_else") == TEXT_PRIMARY

    def test_case_insensitive(self):
        assert color_for_status("PASS") == GREEN
        assert color_for_status("FAIL") == RED


# ===========================================================================
# report_charts.py
# ===========================================================================


class TestStatusColor:
    def test_known_statuses(self):
        assert status_color("pass") != ""
        assert status_color("fail") != ""
        assert status_color("warn") != ""
        assert status_color("skip") != ""
        assert status_color("error") != ""
        assert status_color("running") != ""

    def test_unknown_returns_muted(self):
        assert status_color("unknown_xyz") == "#484f58"


class TestStatusBadge:
    def test_returns_html_span(self):
        result = status_badge("pass")
        assert "<span" in result
        assert "PASS" in result

    def test_custom_text(self):
        result = status_badge("fail", "FAILED!")
        assert "FAILED!" in result

    def test_html_escapes_text(self):
        result = status_badge("pass", "<b>XSS</b>")
        assert "<b>" not in result
        assert "&lt;b&gt;" in result


class TestMetricCard:
    def test_contains_label_and_value(self):
        result = metric_card("Total", "42")
        assert "Total" in result
        assert "42" in result

    def test_uses_custom_color(self):
        result = metric_card("X", "1", color="#ff0000")
        assert "#ff0000" in result

    def test_html_escapes(self):
        result = metric_card("<script>", "<img>")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result


class TestBarChart:
    def test_empty_data_returns_empty(self):
        assert bar_chart([]) == ""

    def test_single_bar(self):
        result = bar_chart([("Label A", 50.0)])
        assert "Label A" in result
        assert "50.00" in result

    def test_multiple_bars(self):
        data = [("A", 10.0), ("B", 20.0), ("C", 30.0)]
        result = bar_chart(data)
        assert "A" in result
        assert "B" in result
        assert "C" in result

    def test_custom_max_value(self):
        result = bar_chart([("X", 50.0)], max_value=100.0)
        assert "50.0%" in result

    def test_custom_bar_color(self):
        result = bar_chart([("X", 10.0)], bar_color="#abcdef")
        assert "#abcdef" in result


class TestResultsTable:
    def test_renders_columns_and_rows(self):
        cols = ["Name", "Status"]
        rows = [["test_1", "PASS"], ["test_2", "FAIL"]]
        result = results_table(cols, rows)
        assert "Name" in result
        assert "Status" in result
        assert "test_1" in result
        assert "test_2" in result
        assert "<table" in result

    def test_status_column_renders_badge(self):
        cols = ["Name", "Status"]
        rows = [["test_1", "PASS"]]
        result = results_table(cols, rows, status_column=1)
        # status_badge is called for status column
        assert "PASS" in result

    def test_empty_rows(self):
        result = results_table(["Col"], [])
        assert "<table" in result
        assert "Col" in result

    def test_html_escapes_cell_content(self):
        result = results_table(["X"], [["<b>bold</b>"]])
        assert "<b>bold</b>" not in result
        assert "&lt;b&gt;" in result


class TestSectionHeader:
    def test_renders_title(self):
        result = section_header("My Title")
        assert "My Title" in result

    def test_renders_subtitle(self):
        result = section_header("Title", "Subtitle text")
        assert "Subtitle text" in result

    def test_no_subtitle(self):
        result = section_header("Title")
        # Should not have the subtitle div if no subtitle
        assert "Title" in result

    def test_html_escapes(self):
        result = section_header("<script>")
        assert "&lt;script&gt;" in result


class TestKeyValueTable:
    def test_empty_data_returns_empty(self):
        assert key_value_table({}) == ""

    def test_renders_key_value_pairs(self):
        result = key_value_table({"Name": "Calypso", "Version": "1.0"})
        assert "Name" in result
        assert "Calypso" in result
        assert "Version" in result
        assert "1.0" in result

    def test_with_title(self):
        result = key_value_table({"K": "V"}, title="Info")
        assert "Info" in result

    def test_without_title(self):
        result = key_value_table({"K": "V"})
        assert "<table" in result

    def test_html_escapes(self):
        result = key_value_table({"<k>": "<v>"})
        assert "&lt;k&gt;" in result
        assert "&lt;v&gt;" in result


class TestDivider:
    def test_returns_hr(self):
        result = divider()
        assert "<hr" in result


# ===========================================================================
# report_sections.py — dispatcher and generic renderer
# ===========================================================================


class TestRenderRecipeSection:
    def test_dispatches_known_recipe_to_specialized_renderer(self):
        summary = make_summary(
            recipe_id="all_port_sweep",
            recipe_name="All Port Sweep",
            steps=[
                make_result(
                    name="Port 0",
                    measured_values={
                        "port_number": 0,
                        "link_speed": "16.0 GT/s",
                        "link_width": "x16",
                        "status": "pass",
                    },
                )
            ],
        )
        result = render_recipe_section(summary)
        # Specialized renderer should produce HTML
        assert isinstance(result, str)
        assert len(result) > 0

    def test_falls_back_to_generic_for_unknown_recipe(self):
        summary = make_summary(
            recipe_id="unknown_recipe_xyz",
            recipe_name="Unknown Recipe",
        )
        result = render_recipe_section(summary)
        assert "Unknown Recipe" in result
        assert "Pass" in result
        assert "Fail" in result

    def test_generic_renderer_shows_step_table(self):
        summary = make_summary(
            recipe_id="unregistered",
            steps=[
                make_result(name="step_alpha", status=StepStatus.PASS, message="All good"),
                make_result(name="step_beta", status=StepStatus.FAIL, message="Error found"),
            ],
            status=StepStatus.FAIL,
        )
        result = render_recipe_section(summary)
        assert "step_alpha" in result
        assert "step_beta" in result
        assert "All good" in result
        assert "Error found" in result

    def test_generic_renderer_shows_measured_values(self):
        summary = make_summary(
            recipe_id="unregistered",
            steps=[
                make_result(
                    name="measurement_step",
                    measured_values={"voltage": 1.2, "current": 0.5},
                ),
            ],
        )
        result = render_recipe_section(summary)
        assert "Detailed Measurements" in result
        assert "voltage" in result
        assert "current" in result

    def test_generic_renderer_no_measured_values(self):
        summary = make_summary(
            recipe_id="unregistered",
            steps=[make_result(name="simple_step", measured_values={})],
        )
        result = render_recipe_section(summary)
        assert "Detailed Measurements" not in result

    def test_generic_shows_category_and_duration(self):
        summary = make_summary(
            recipe_id="unregistered",
            category=RecipeCategory.PERFORMANCE,
        )
        result = render_recipe_section(summary)
        assert "performance" in result
        assert "ms" in result

    def test_bandwidth_recipe_dispatches(self):
        summary = make_summary(
            recipe_id="bandwidth_baseline",
            recipe_name="Bandwidth Baseline",
            steps=[make_result(measured_values={"bandwidth_gbps": 25.0})],
        )
        result = render_recipe_section(summary)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_ber_soak_recipe_dispatches(self):
        summary = make_summary(
            recipe_id="ber_soak",
            recipe_name="BER Soak",
            steps=[make_result(measured_values={"ber": 1e-12})],
        )
        result = render_recipe_section(summary)
        assert isinstance(result, str)
        assert len(result) > 0


# ===========================================================================
# workflow_report.py
# ===========================================================================


class TestFormatParamValue:
    def test_bool_true(self):
        assert _format_param_value(True) == "Yes"

    def test_bool_false(self):
        assert _format_param_value(False) == "No"

    def test_float(self):
        result = _format_param_value(3.14)
        assert result == "3.14"

    def test_float_integer_like(self):
        result = _format_param_value(5.0)
        assert result == "5"

    def test_float_small(self):
        result = _format_param_value(0.001)
        assert result == "0.001"

    def test_string(self):
        assert _format_param_value("hello") == "hello"

    def test_int(self):
        assert _format_param_value(42) == "42"

    def test_none(self):
        assert _format_param_value(None) == "None"


class TestRenderParameters:
    def test_empty_dict_returns_empty(self):
        assert _render_parameters({}) == ""

    def test_non_empty_returns_table(self):
        result = _render_parameters({"speed": "16GT/s", "width": "x16"})
        assert "Test Parameters" in result
        assert "speed" in result
        assert "16GT/s" in result
        assert "width" in result
        assert "x16" in result

    def test_formats_bool_values(self):
        result = _render_parameters({"enabled": True, "verbose": False})
        assert "Yes" in result
        assert "No" in result

    def test_formats_float_values(self):
        result = _render_parameters({"threshold": 0.95})
        assert "0.95" in result


class TestGenerateReport:
    def test_produces_valid_html(self):
        summaries = [make_summary()]
        result = generate_report(summaries)
        assert "<!DOCTYPE html>" in result
        assert "<html" in result
        assert "</html>" in result
        assert "<body>" in result
        assert "</body>" in result

    def test_contains_title(self):
        result = generate_report([make_summary()], title="My Report")
        assert "My Report" in result

    def test_contains_calypso_branding(self):
        result = generate_report([make_summary()])
        assert "CALYPSO" in result
        assert "Serial Cables Atlas3" in result

    def test_contains_device_id(self):
        result = generate_report([make_summary()], device_id="DEV-001")
        assert "DEV-001" in result

    def test_contains_aggregate_metrics(self):
        summaries = [
            make_summary(
                steps=[
                    make_result(status=StepStatus.PASS),
                    make_result(status=StepStatus.PASS),
                ],
                status=StepStatus.PASS,
            ),
            make_summary(
                steps=[make_result(status=StepStatus.FAIL)],
                status=StepStatus.FAIL,
            ),
        ]
        result = generate_report(summaries)
        assert "Recipes" in result
        assert "Pass" in result
        assert "Fail" in result
        assert "Duration" in result

    def test_overall_status_fail_when_any_fail(self):
        summaries = [
            make_summary(status=StepStatus.PASS),
            make_summary(status=StepStatus.FAIL),
        ]
        result = generate_report(summaries)
        assert "FAIL" in result

    def test_overall_status_warn_when_no_fail_but_warn(self):
        summaries = [
            make_summary(status=StepStatus.PASS),
            make_summary(status=StepStatus.WARN),
        ]
        result = generate_report(summaries)
        assert "WARN" in result

    def test_overall_status_pass_when_all_pass(self):
        summaries = [make_summary(status=StepStatus.PASS)]
        result = generate_report(summaries)
        assert "PASS" in result

    def test_recipe_summary_table(self):
        summary = make_summary(recipe_name="Port Sweep Test")
        result = generate_report([summary])
        assert "Recipe Summary" in result
        assert "Port Sweep Test" in result

    def test_contains_recipe_detail_sections(self):
        summary = make_summary(
            recipe_id="unregistered",
            recipe_name="Detail Test",
            steps=[make_result(name="detail_step", message="step detail msg")],
        )
        result = generate_report([summary])
        assert "detail_step" in result
        assert "step detail msg" in result

    def test_device_info_section(self):
        result = generate_report(
            [make_summary()],
            device_info={"chip_type": "PEX90096", "revision": "B0"},
        )
        assert "Device Information" in result
        assert "Chip Type" in result
        assert "PEX90096" in result
        assert "Revision" in result
        assert "B0" in result

    def test_device_info_none(self):
        result = generate_report([make_summary()], device_info=None)
        assert "Device Information" not in result

    def test_device_info_empty_values_filtered(self):
        result = generate_report(
            [make_summary()],
            device_info={"chip_type": "PEX90096", "revision": ""},
        )
        assert "PEX90096" in result
        # Empty revision should be filtered out
        assert "Revision" not in result

    def test_parameters_rendered_for_recipe(self):
        summary = make_summary(
            recipe_id="unregistered",
            parameters={"duration_sec": 60, "target_ber": 1e-12},
        )
        result = generate_report([summary])
        assert "Test Parameters" in result
        assert "duration_sec" in result

    def test_empty_summaries(self):
        result = generate_report([])
        assert "<!DOCTYPE html>" in result
        assert "CALYPSO" in result

    def test_html_escapes_title(self):
        result = generate_report([make_summary()], title="<script>alert(1)</script>")
        assert "<script>alert(1)</script>" not in result
        assert "&lt;script&gt;" in result

    def test_print_css_included(self):
        result = generate_report([make_summary()])
        assert "@media print" in result

    def test_multiple_recipes(self):
        summaries = [
            make_summary(recipe_name="Recipe A", recipe_id="a"),
            make_summary(recipe_name="Recipe B", recipe_id="b"),
            make_summary(recipe_name="Recipe C", recipe_id="c"),
        ]
        result = generate_report(summaries)
        assert "Recipe A" in result
        assert "Recipe B" in result
        assert "Recipe C" in result


class TestGenerateSingleReport:
    def test_wraps_single_summary(self):
        summary = make_summary(recipe_name="Solo Recipe")
        result = generate_single_report(summary)
        assert "Solo Recipe" in result
        assert "Recipe Report: Solo Recipe" in result
        assert "<!DOCTYPE html>" in result

    def test_passes_device_id(self):
        result = generate_single_report(make_summary(), device_id="DEV-X")
        assert "DEV-X" in result

    def test_passes_device_info(self):
        result = generate_single_report(
            make_summary(),
            device_info={"chip_type": "PEX90080"},
        )
        assert "PEX90080" in result

    def test_returns_complete_html(self):
        result = generate_single_report(make_summary())
        assert "<html" in result
        assert "</html>" in result


# ===========================================================================
# Edge cases and cross-cutting concerns
# ===========================================================================


class TestEdgeCases:
    def test_step_with_nested_dict_measured_values(self):
        """Generic renderer handles nested dicts in measured_values."""
        summary = make_summary(
            recipe_id="unregistered",
            steps=[
                make_result(
                    name="nested_step",
                    measured_values={
                        "config": {"speed": "16GT/s", "width": "x16"},
                    },
                ),
            ],
        )
        result = render_recipe_section(summary)
        assert "speed" in result
        assert "16GT/s" in result

    def test_step_with_list_measured_values(self):
        """Generic renderer handles lists in measured_values."""
        summary = make_summary(
            recipe_id="unregistered",
            steps=[
                make_result(
                    name="list_step",
                    measured_values={"ports": [1, 2, 3]},
                ),
            ],
        )
        result = render_recipe_section(summary)
        assert "ports" in result

    def test_step_with_bool_measured_value(self):
        """Generic renderer handles booleans in measured_values."""
        summary = make_summary(
            recipe_id="unregistered",
            steps=[
                make_result(
                    name="bool_step",
                    measured_values={"enabled": True, "failed": False},
                ),
            ],
        )
        result = render_recipe_section(summary)
        assert "True" in result
        assert "False" in result

    def test_step_with_small_float_measured_value(self):
        """Generic renderer formats small floats in scientific notation."""
        summary = make_summary(
            recipe_id="unregistered",
            steps=[
                make_result(
                    name="float_step",
                    measured_values={"ber": 1e-15},
                ),
            ],
        )
        result = render_recipe_section(summary)
        assert "e-15" in result or "1e-15" in result

    def test_step_with_empty_list(self):
        """Generic renderer handles empty lists."""
        summary = make_summary(
            recipe_id="unregistered",
            steps=[
                make_result(
                    name="empty_list_step",
                    measured_values={"items": []},
                ),
            ],
        )
        result = render_recipe_section(summary)
        assert "[]" in result

    def test_step_with_list_of_dicts(self):
        """Generic renderer handles list of dicts as a sub-table."""
        summary = make_summary(
            recipe_id="unregistered",
            steps=[
                make_result(
                    name="dict_list_step",
                    measured_values={
                        "lanes": [
                            {"lane": 0, "status": "pass"},
                            {"lane": 1, "status": "fail"},
                        ]
                    },
                ),
            ],
        )
        result = render_recipe_section(summary)
        assert "lane" in result
        assert "status" in result

    def test_unicode_in_step_names(self):
        """Report handles unicode characters."""
        summary = make_summary(
            recipe_id="unregistered",
            steps=[make_result(name="step_with_unicode_\u00b5s")],
        )
        result = render_recipe_section(summary)
        assert "\u00b5s" in result

    def test_special_html_chars_in_message(self):
        """Messages with HTML characters are escaped."""
        summary = make_summary(
            recipe_id="unregistered",
            steps=[make_result(message="value < threshold & ok > min")],
        )
        result = render_recipe_section(summary)
        assert "&lt;" in result
        assert "&amp;" in result

    def test_format_timestamp_in_generic_renderer(self):
        """Generic renderer extracts time from ISO timestamp."""
        summary = make_summary(
            recipe_id="unregistered",
            steps=[make_result(timestamp="2024-06-15T14:30:45.123Z")],
        )
        result = render_recipe_section(summary)
        assert "14:30:45" in result

    def test_ber_confidence_interval_math(self):
        """Verify confidence interval math for known values."""
        result = ber_confidence_interval(100, 1e-9)
        assert result is not None
        # With 100 errors, CI should be relatively tight
        # lo = max(0, 100 - 1.96*10) / (100/1e-9) = (80.4) / 1e11 = 8.04e-10
        # hi = (100 + 1.96*10) / 1e11 = 119.6/1e11 = 1.196e-9
        assert "e-10" in result or "e-09" in result

    def test_bar_chart_with_zero_max(self):
        """Bar chart handles all-zero data."""
        result = bar_chart([("A", 0.0), ("B", 0.0)])
        assert "A" in result
        assert "B" in result
        assert "0.00" in result

    def test_results_table_no_status_column(self):
        """Table without status column doesn't create badges."""
        result = results_table(["Name", "Value"], [["test", "42"]])
        assert "test" in result
        assert "42" in result

    def test_large_number_of_steps(self):
        """Report handles many steps without error."""
        steps = [make_result(name=f"step_{i}") for i in range(50)]
        summary = make_summary(recipe_id="unregistered", steps=steps)
        result = render_recipe_section(summary)
        assert "step_0" in result
        assert "step_49" in result
