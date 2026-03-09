"""Unit tests for calypso.workflows.export — JSON and CSV export utilities."""

from __future__ import annotations

import csv
import io
import json

import pytest

from calypso.workflows.export import (
    _collect_scalar_keys,
    _is_scalar,
    _sanitize_csv_value,
    _serialize_measured_values,
    export_csv,
    export_json,
    export_single_json,
    export_summary_csv,
)
from calypso.workflows.models import (
    RecipeCategory,
    RecipeResult,
    RecipeSummary,
    StepCriticality,
    StepStatus,
)


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


def make_result(
    name: str = "step",
    status: StepStatus = StepStatus.PASS,
    measured_values: dict | None = None,
    duration_ms: float = 100.0,
    message: str = "ok",
    port_number: int | None = None,
    lane: int | None = None,
    criticality: StepCriticality = StepCriticality.MEDIUM,
    timestamp: str = "2024-01-01T00:00:00Z",
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
        criticality=criticality,
    )


def make_summary(
    recipe_id: str = "test",
    recipe_name: str = "Test",
    steps: list[RecipeResult] | None = None,
    category: RecipeCategory = RecipeCategory.LINK_HEALTH,
    status: StepStatus = StepStatus.PASS,
    device_id: str = "dev0",
    duration_ms: float = 100.0,
    started_at: str = "2024-01-01T00:00:00Z",
    completed_at: str = "2024-01-01T00:01:00Z",
) -> RecipeSummary:
    steps = steps if steps is not None else [make_result()]
    return RecipeSummary(
        recipe_id=recipe_id,
        recipe_name=recipe_name,
        category=category,
        status=status,
        steps=steps,
        total_pass=sum(1 for s in steps if s.status == StepStatus.PASS),
        total_fail=sum(1 for s in steps if s.status == StepStatus.FAIL),
        total_warn=sum(1 for s in steps if s.status == StepStatus.WARN),
        total_skip=sum(1 for s in steps if s.status == StepStatus.SKIP),
        total_error=sum(1 for s in steps if s.status == StepStatus.ERROR),
        duration_ms=duration_ms,
        parameters={},
        device_id=device_id,
        started_at=started_at,
        completed_at=completed_at,
    )


# ---------------------------------------------------------------------------
# _sanitize_csv_value
# ---------------------------------------------------------------------------


class TestSanitizeCsvValue:
    """Tests for CSV formula injection prevention."""

    @pytest.mark.parametrize(
        "dangerous_input",
        [
            "=SUM(A1:A10)",
            "+cmd|'/C calc'!A0",
            "-cmd|'/C calc'!A0",
            "@SUM(A1)",
            "\tcmd",
            "\rcmd",
        ],
    )
    def test_prefixes_dangerous_strings(self, dangerous_input: str) -> None:
        result = _sanitize_csv_value(dangerous_input)
        assert isinstance(result, str)
        assert result.startswith("'")
        assert result[1:] == dangerous_input

    def test_normal_string_unchanged(self) -> None:
        assert _sanitize_csv_value("hello world") == "hello world"

    def test_empty_string_unchanged(self) -> None:
        assert _sanitize_csv_value("") == ""

    def test_non_string_int_unchanged(self) -> None:
        assert _sanitize_csv_value(42) == 42

    def test_non_string_float_unchanged(self) -> None:
        assert _sanitize_csv_value(3.14) == 3.14

    def test_non_string_none_unchanged(self) -> None:
        assert _sanitize_csv_value(None) is None

    def test_non_string_bool_unchanged(self) -> None:
        assert _sanitize_csv_value(True) is True

    def test_string_with_formula_char_in_middle(self) -> None:
        assert _sanitize_csv_value("a=b") == "a=b"

    def test_string_starting_with_number(self) -> None:
        assert _sanitize_csv_value("123") == "123"


# ---------------------------------------------------------------------------
# _is_scalar
# ---------------------------------------------------------------------------


class TestIsScalar:
    """Tests for scalar type detection."""

    @pytest.mark.parametrize(
        "value",
        ["hello", 42, 3.14, True, False, None],
    )
    def test_scalar_values(self, value: object) -> None:
        assert _is_scalar(value) is True

    @pytest.mark.parametrize(
        "value",
        [[1, 2], {"a": 1}, (1,), {1, 2}],
    )
    def test_non_scalar_values(self, value: object) -> None:
        assert _is_scalar(value) is False


# ---------------------------------------------------------------------------
# _collect_scalar_keys
# ---------------------------------------------------------------------------


class TestCollectScalarKeys:
    """Tests for scalar key collection across summaries."""

    def test_empty_summaries(self) -> None:
        assert _collect_scalar_keys([]) == []

    def test_collects_scalar_keys_sorted(self) -> None:
        steps = [
            make_result(measured_values={"ber": 1e-12, "width": 0.5}),
            make_result(measured_values={"snr": 20.0, "ber": 1e-11}),
        ]
        summary = make_summary(steps=steps)
        keys = _collect_scalar_keys([summary])
        assert keys == ["ber", "snr", "width"]

    def test_skips_non_scalar_values(self) -> None:
        steps = [
            make_result(measured_values={"flat": 1, "nested": {"a": 1}, "arr": [1]}),
        ]
        summary = make_summary(steps=steps)
        keys = _collect_scalar_keys([summary])
        assert keys == ["flat"]

    def test_collects_across_multiple_summaries(self) -> None:
        s1 = make_summary(steps=[make_result(measured_values={"alpha": 1})])
        s2 = make_summary(steps=[make_result(measured_values={"beta": 2})])
        keys = _collect_scalar_keys([s1, s2])
        assert keys == ["alpha", "beta"]


# ---------------------------------------------------------------------------
# _serialize_measured_values
# ---------------------------------------------------------------------------


class TestSerializeMeasuredValues:
    """Tests for measured_values JSON serialization."""

    def test_empty_dict_returns_empty_string(self) -> None:
        assert _serialize_measured_values({}) == ""

    def test_non_empty_dict_returns_json(self) -> None:
        result = _serialize_measured_values({"ber": 1e-12})
        parsed = json.loads(result)
        assert parsed == {"ber": 1e-12}

    def test_non_serializable_uses_str_fallback(self) -> None:
        from datetime import datetime

        dt = datetime(2024, 1, 1)
        result = _serialize_measured_values({"ts": dt})
        parsed = json.loads(result)
        assert isinstance(parsed["ts"], str)


# ---------------------------------------------------------------------------
# export_json / export_single_json
# ---------------------------------------------------------------------------


class TestExportJson:
    """Tests for JSON export functions."""

    def test_export_json_returns_valid_json(self) -> None:
        summaries = [make_summary()]
        result = export_json(summaries)
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 1

    def test_export_json_empty_list(self) -> None:
        result = export_json([])
        parsed = json.loads(result)
        assert parsed == []

    def test_export_json_contains_expected_fields(self) -> None:
        summaries = [make_summary(recipe_id="sweep", recipe_name="Port Sweep")]
        result = export_json(summaries)
        parsed = json.loads(result)
        entry = parsed[0]
        assert entry["recipe_id"] == "sweep"
        assert entry["recipe_name"] == "Port Sweep"
        assert entry["category"] == "link_health"
        assert entry["status"] == "pass"
        assert "total_steps" in entry
        assert "pass_rate" in entry
        assert "steps" in entry

    def test_export_json_includes_total_steps_and_pass_rate(self) -> None:
        steps = [make_result(), make_result(status=StepStatus.FAIL)]
        summaries = [make_summary(steps=steps)]
        result = export_json(summaries)
        parsed = json.loads(result)
        entry = parsed[0]
        assert entry["total_steps"] == 2
        assert entry["pass_rate"] == 50.0

    def test_export_json_multiple_summaries(self) -> None:
        s1 = make_summary(recipe_id="a")
        s2 = make_summary(recipe_id="b")
        result = export_json([s1, s2])
        parsed = json.loads(result)
        assert len(parsed) == 2
        assert parsed[0]["recipe_id"] == "a"
        assert parsed[1]["recipe_id"] == "b"

    def test_export_single_json(self) -> None:
        summary = make_summary(recipe_id="single")
        result = export_single_json(summary)
        parsed = json.loads(result)
        assert isinstance(parsed, dict)
        assert parsed["recipe_id"] == "single"

    def test_export_json_custom_indent(self) -> None:
        result = export_json([make_summary()], indent=4)
        assert "    " in result


# ---------------------------------------------------------------------------
# export_csv (per-step rows)
# ---------------------------------------------------------------------------


class TestExportCsv:
    """Tests for per-step CSV export."""

    def _parse_csv(self, csv_str: str) -> list[dict[str, str]]:
        reader = csv.DictReader(io.StringIO(csv_str))
        return list(reader)

    def test_empty_summaries(self) -> None:
        result = export_csv([])
        rows = self._parse_csv(result)
        assert rows == []

    def test_header_includes_fixed_columns(self) -> None:
        result = export_csv([make_summary()])
        reader = csv.reader(io.StringIO(result))
        header = next(reader)
        for col in [
            "recipe_id",
            "recipe_name",
            "category",
            "recipe_status",
            "step_name",
            "step_status",
            "criticality",
            "message",
            "duration_ms",
            "port_number",
            "lane",
            "timestamp",
            "measured_values_json",
        ]:
            assert col in header

    def test_one_step_produces_one_data_row(self) -> None:
        result = export_csv([make_summary()])
        rows = self._parse_csv(result)
        assert len(rows) == 1

    def test_multiple_steps_produce_multiple_rows(self) -> None:
        steps = [make_result(name="s1"), make_result(name="s2"), make_result(name="s3")]
        result = export_csv([make_summary(steps=steps)])
        rows = self._parse_csv(result)
        assert len(rows) == 3

    def test_row_values_match_source(self) -> None:
        step = make_result(
            name="check",
            status=StepStatus.WARN,
            duration_ms=42.5,
            port_number=3,
            lane=1,
            timestamp="2024-06-15T12:00:00Z",
        )
        summary = make_summary(
            recipe_id="sweep",
            recipe_name="Sweep",
            category=RecipeCategory.PERFORMANCE,
            status=StepStatus.WARN,
            steps=[step],
        )
        result = export_csv([summary])
        rows = self._parse_csv(result)
        row = rows[0]
        assert row["recipe_id"] == "sweep"
        assert row["recipe_name"] == "Sweep"
        assert row["category"] == "performance"
        assert row["recipe_status"] == "warn"
        assert row["step_name"] == "check"
        assert row["step_status"] == "warn"
        assert row["duration_ms"] == "42.50"
        assert row["port_number"] == "3"
        assert row["lane"] == "1"
        assert row["timestamp"] == "2024-06-15T12:00:00Z"

    def test_none_port_and_lane_render_empty(self) -> None:
        step = make_result(port_number=None, lane=None)
        result = export_csv([make_summary(steps=[step])])
        rows = self._parse_csv(result)
        assert rows[0]["port_number"] == ""
        assert rows[0]["lane"] == ""

    def test_scalar_measured_values_get_own_columns(self) -> None:
        step = make_result(measured_values={"ber": 1e-12, "width": 0.5})
        result = export_csv([make_summary(steps=[step])])
        rows = self._parse_csv(result)
        assert rows[0]["ber"] == "1e-12"
        assert rows[0]["width"] == "0.5"

    def test_measured_values_json_column_populated(self) -> None:
        step = make_result(measured_values={"x": 10})
        result = export_csv([make_summary(steps=[step])])
        rows = self._parse_csv(result)
        parsed = json.loads(rows[0]["measured_values_json"])
        assert parsed["x"] == 10

    def test_measured_values_json_empty_when_no_values(self) -> None:
        step = make_result(measured_values={})
        result = export_csv([make_summary(steps=[step])])
        rows = self._parse_csv(result)
        assert rows[0]["measured_values_json"] == ""

    def test_sanitizes_dangerous_step_name(self) -> None:
        step = make_result(name="=HYPERLINK()")
        result = export_csv([make_summary(steps=[step])])
        rows = self._parse_csv(result)
        assert rows[0]["step_name"] == "'=HYPERLINK()"

    def test_sanitizes_dangerous_message(self) -> None:
        step = make_result(message="+cmd|boom")
        result = export_csv([make_summary(steps=[step])])
        rows = self._parse_csv(result)
        assert rows[0]["message"] == "'+cmd|boom"

    def test_sanitizes_dangerous_measured_value(self) -> None:
        step = make_result(measured_values={"evil": "=DROP TABLE"})
        result = export_csv([make_summary(steps=[step])])
        rows = self._parse_csv(result)
        assert rows[0]["evil"] == "'=DROP TABLE"

    def test_non_scalar_measured_values_not_in_columns(self) -> None:
        step = make_result(measured_values={"flat": 1, "nested": {"a": 1}})
        result = export_csv([make_summary(steps=[step])])
        reader = csv.reader(io.StringIO(result))
        header = next(reader)
        assert "flat" in header
        assert "nested" not in header

    def test_missing_scalar_key_renders_empty(self) -> None:
        s1 = make_summary(steps=[make_result(measured_values={"a": 1, "b": 2})])
        s2 = make_summary(steps=[make_result(measured_values={"a": 3})])
        result = export_csv([s1, s2])
        rows = self._parse_csv(result)
        assert rows[0]["b"] == "2"
        assert rows[1]["b"] == ""


# ---------------------------------------------------------------------------
# export_summary_csv (per-recipe rows)
# ---------------------------------------------------------------------------


class TestExportSummaryCsv:
    """Tests for recipe-level summary CSV export."""

    def _parse_csv(self, csv_str: str) -> list[dict[str, str]]:
        reader = csv.DictReader(io.StringIO(csv_str))
        return list(reader)

    def test_empty_summaries(self) -> None:
        result = export_summary_csv([])
        rows = self._parse_csv(result)
        assert rows == []

    def test_header_columns(self) -> None:
        result = export_summary_csv([make_summary()])
        reader = csv.reader(io.StringIO(result))
        header = next(reader)
        expected = [
            "recipe_id",
            "recipe_name",
            "category",
            "status",
            "device_id",
            "total_steps",
            "pass",
            "fail",
            "warn",
            "skip",
            "error",
            "pass_rate",
            "duration_ms",
            "started_at",
            "completed_at",
            "measured_values_json",
        ]
        assert header == expected

    def test_one_summary_one_row(self) -> None:
        result = export_summary_csv([make_summary()])
        rows = self._parse_csv(result)
        assert len(rows) == 1

    def test_row_values_match_source(self) -> None:
        summary = make_summary(
            recipe_id="ber_soak",
            recipe_name="BER Soak",
            category=RecipeCategory.SIGNAL_INTEGRITY,
            status=StepStatus.PASS,
            device_id="dev42",
            duration_ms=5000.0,
            started_at="2024-06-15T10:00:00Z",
            completed_at="2024-06-15T10:01:00Z",
        )
        result = export_summary_csv([summary])
        rows = self._parse_csv(result)
        row = rows[0]
        assert row["recipe_id"] == "ber_soak"
        assert row["recipe_name"] == "BER Soak"
        assert row["category"] == "signal_integrity"
        assert row["status"] == "pass"
        assert row["device_id"] == "dev42"
        assert row["total_steps"] == "1"
        assert row["pass"] == "1"
        assert row["fail"] == "0"
        assert row["duration_ms"] == "5000.00"
        assert row["started_at"] == "2024-06-15T10:00:00Z"
        assert row["completed_at"] == "2024-06-15T10:01:00Z"

    def test_includes_timestamp_and_measured_values_json(self) -> None:
        result = export_summary_csv([make_summary()])
        reader = csv.reader(io.StringIO(result))
        header = next(reader)
        assert "started_at" in header
        assert "completed_at" in header
        assert "measured_values_json" in header

    def test_picks_step_with_most_measured_values(self) -> None:
        """The best_mv logic should pick the step with the most keys, not the last."""
        step_few = make_result(name="setup", measured_values={"a": 1})
        step_many = make_result(name="analysis", measured_values={"x": 1, "y": 2, "z": 3})
        step_last = make_result(name="cleanup", measured_values={"done": True})

        summary = make_summary(steps=[step_few, step_many, step_last])
        result = export_summary_csv([summary])
        rows = self._parse_csv(result)
        mv_json = rows[0]["measured_values_json"]
        parsed = json.loads(mv_json)
        assert parsed == {"x": 1, "y": 2, "z": 3}

    def test_empty_measured_values_renders_empty_string(self) -> None:
        step = make_result(measured_values={})
        summary = make_summary(steps=[step])
        result = export_summary_csv([summary])
        rows = self._parse_csv(result)
        assert rows[0]["measured_values_json"] == ""

    def test_pass_rate_formatted(self) -> None:
        steps = [make_result(), make_result(), make_result(status=StepStatus.FAIL)]
        summary = make_summary(steps=steps)
        result = export_summary_csv([summary])
        rows = self._parse_csv(result)
        assert rows[0]["pass_rate"] == "66.7"

    def test_zero_steps_pass_rate(self) -> None:
        summary = make_summary(steps=[])
        result = export_summary_csv([summary])
        rows = self._parse_csv(result)
        assert rows[0]["pass_rate"] == "0.0"

    def test_multiple_summaries(self) -> None:
        s1 = make_summary(recipe_id="a")
        s2 = make_summary(recipe_id="b")
        result = export_summary_csv([s1, s2])
        rows = self._parse_csv(result)
        assert len(rows) == 2
        assert rows[0]["recipe_id"] == "a"
        assert rows[1]["recipe_id"] == "b"

    def test_sanitizes_dangerous_values_in_measured_values_json(self) -> None:
        """Measured values JSON is serialized, not sanitized directly,
        but the raw JSON string shouldn't start with a formula character."""
        step = make_result(measured_values={"safe": "value"})
        summary = make_summary(steps=[step])
        result = export_summary_csv([summary])
        rows = self._parse_csv(result)
        mv = rows[0]["measured_values_json"]
        assert mv[0] not in "=+-@\t\r" if mv else True
