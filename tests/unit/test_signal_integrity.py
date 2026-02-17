"""Unit tests for calypso.compliance.tests.signal_integrity — PAM4 + NRZ compliance."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from calypso.compliance.models import PortConfig, TestRunConfig, Verdict
from calypso.compliance.tests.signal_integrity import (
    _pct_below,
    _t4_2_spec_minimum_check,
    _t4_3_lane_comparison,
    _t4_4_pam4_balance_check,
    _worst_case_per_lane,
    run_signal_integrity_tests,
)
from calypso.models.phy_api import (
    EyeSweepResult,
    LaneMarginCapabilitiesResponse,
    PAM4SweepResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_port(port_number: int = 0, num_lanes: int = 4) -> PortConfig:
    return PortConfig(port_number=port_number, num_lanes=num_lanes)


def _make_nrz_measurement(
    lane: int,
    eye_width_ui: float = 0.30,
    eye_height_mv: float = 15.0,
) -> dict[str, object]:
    return {
        "lane": lane,
        "eye_width_ui": eye_width_ui,
        "eye_height_mv": eye_height_mv,
        "eye_width_steps": 10,
        "eye_height_steps": 8,
    }


def _make_pam4_measurement(
    lane: int,
    eye: str,
    eye_width_ui: float = 0.20,
    eye_height_mv: float = 10.0,
) -> dict[str, object]:
    return {
        "lane": lane,
        "eye": eye,
        "eye_width_ui": eye_width_ui,
        "eye_height_mv": eye_height_mv,
        "eye_width_steps": 6,
        "eye_height_steps": 4,
    }


def _make_eye_sweep_result(
    lane: int = 0,
    receiver: int = 0,
    eye_width_ui: float = 0.30,
    eye_height_mv: float = 15.0,
    sweep_time_ms: int = 100,
) -> EyeSweepResult:
    return EyeSweepResult(
        lane=lane,
        receiver=receiver,
        timing_points=[],
        voltage_points=[],
        capabilities=LaneMarginCapabilitiesResponse(
            max_timing_offset=25,
            max_voltage_offset=50,
            num_timing_steps=4,
            num_voltage_steps=4,
            ind_up_down_voltage=True,
            ind_left_right_timing=True,
        ),
        eye_width_steps=10,
        eye_height_steps=8,
        eye_width_ui=eye_width_ui,
        eye_height_mv=eye_height_mv,
        sweep_time_ms=sweep_time_ms,
    )


# ---------------------------------------------------------------------------
# _pct_below
# ---------------------------------------------------------------------------


class TestPctBelow:
    def test_50_percent_below(self):
        assert _pct_below(5.0, 10.0) == pytest.approx(50.0)

    def test_zero_avg(self):
        assert _pct_below(5.0, 0.0) == 0.0

    def test_equal_values(self):
        assert _pct_below(10.0, 10.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _t4_2_spec_minimum_check
# ---------------------------------------------------------------------------


class TestT42SpecMinimumCheck:
    def test_gen4_pass(self):
        """Gen4 threshold: 0.25 UI, 15 mV — measurements above threshold pass."""
        measurements = [_make_nrz_measurement(0, 0.30, 20.0)]
        results = _t4_2_spec_minimum_check(measurements, 4, _make_port())
        assert len(results) == 1
        assert results[0].verdict == Verdict.PASS
        assert results[0].test_id == "T4.2"

    def test_gen4_fail_width(self):
        """Width below threshold fails."""
        measurements = [_make_nrz_measurement(0, 0.10, 20.0)]
        results = _t4_2_spec_minimum_check(measurements, 4, _make_port())
        assert results[0].verdict == Verdict.FAIL
        assert "width" in results[0].message

    def test_gen4_fail_height(self):
        """Height below threshold fails."""
        measurements = [_make_nrz_measurement(0, 0.30, 5.0)]
        results = _t4_2_spec_minimum_check(measurements, 4, _make_port())
        assert results[0].verdict == Verdict.FAIL
        assert "height" in results[0].message

    def test_gen4_fail_both(self):
        """Both below threshold fails with both mentioned."""
        measurements = [_make_nrz_measurement(0, 0.10, 5.0)]
        results = _t4_2_spec_minimum_check(measurements, 4, _make_port())
        assert results[0].verdict == Verdict.FAIL
        assert "width" in results[0].message
        assert "height" in results[0].message

    def test_gen6_pam4_with_eye_label(self):
        """PAM4 measurement with eye label included in test name."""
        measurements = [_make_pam4_measurement(0, "upper", 0.20, 10.0)]
        results = _t4_2_spec_minimum_check(measurements, 6, _make_port())
        assert len(results) == 1
        assert results[0].verdict == Verdict.PASS
        assert "upper" in results[0].test_name

    def test_gen6_pam4_fail(self):
        """Gen6 threshold: 0.15 UI, 8 mV — below threshold fails."""
        measurements = [_make_pam4_measurement(0, "lower", 0.10, 5.0)]
        results = _t4_2_spec_minimum_check(measurements, 6, _make_port())
        assert results[0].verdict == Verdict.FAIL

    def test_unknown_speed_skips(self):
        """No threshold for speed gen 7 → SKIP."""
        measurements = [_make_nrz_measurement(0)]
        results = _t4_2_spec_minimum_check(measurements, 7, _make_port())
        assert len(results) == 1
        assert results[0].verdict == Verdict.SKIP

    def test_multiple_lanes(self):
        """Each measurement produces its own result."""
        measurements = [
            _make_nrz_measurement(0, 0.30, 20.0),
            _make_nrz_measurement(1, 0.30, 20.0),
            _make_nrz_measurement(2, 0.10, 5.0),
        ]
        results = _t4_2_spec_minimum_check(measurements, 4, _make_port())
        assert len(results) == 3
        assert results[0].verdict == Verdict.PASS
        assert results[1].verdict == Verdict.PASS
        assert results[2].verdict == Verdict.FAIL

    def test_gen5_threshold(self):
        """Gen5 threshold: 0.20 UI, 10 mV."""
        measurements = [_make_nrz_measurement(0, 0.20, 10.0)]
        results = _t4_2_spec_minimum_check(measurements, 5, _make_port())
        assert results[0].verdict == Verdict.PASS

    def test_gen3_threshold(self):
        """Gen3 threshold: 0.30 UI, 15 mV."""
        measurements = [_make_nrz_measurement(0, 0.30, 15.0)]
        results = _t4_2_spec_minimum_check(measurements, 3, _make_port())
        assert results[0].verdict == Verdict.PASS

    def test_gen4_at_exact_boundary_passes(self):
        """Exactly at threshold (>=) should pass."""
        measurements = [_make_nrz_measurement(0, 0.25, 15.0)]
        results = _t4_2_spec_minimum_check(measurements, 4, _make_port())
        assert results[0].verdict == Verdict.PASS


# ---------------------------------------------------------------------------
# _t4_3_lane_comparison
# ---------------------------------------------------------------------------


class TestT43LaneComparison:
    def test_similar_lanes_pass(self):
        """All lanes within 30% of average → PASS."""
        measurements = [
            _make_nrz_measurement(0, 0.30, 15.0),
            _make_nrz_measurement(1, 0.28, 14.0),
            _make_nrz_measurement(2, 0.32, 16.0),
        ]
        results = _t4_3_lane_comparison(measurements, _make_port())
        assert len(results) == 1
        assert results[0].verdict == Verdict.PASS

    def test_outlier_warns(self):
        """One lane significantly worse → WARN."""
        measurements = [
            _make_nrz_measurement(0, 0.30, 15.0),
            _make_nrz_measurement(1, 0.30, 15.0),
            _make_nrz_measurement(2, 0.10, 5.0),  # way below avg
        ]
        results = _t4_3_lane_comparison(measurements, _make_port())
        assert results[0].verdict == Verdict.WARN
        assert "outlier" in results[0].message

    def test_single_lane_skips(self):
        """Need at least 2 lanes → SKIP."""
        measurements = [_make_nrz_measurement(0)]
        results = _t4_3_lane_comparison(measurements, _make_port())
        assert len(results) == 1
        assert results[0].verdict == Verdict.SKIP

    def test_zero_lanes_skips(self):
        results = _t4_3_lane_comparison([], _make_port())
        assert results[0].verdict == Verdict.SKIP

    def test_two_identical_lanes_pass(self):
        measurements = [
            _make_nrz_measurement(0, 0.25, 15.0),
            _make_nrz_measurement(1, 0.25, 15.0),
        ]
        results = _t4_3_lane_comparison(measurements, _make_port())
        assert results[0].verdict == Verdict.PASS


# ---------------------------------------------------------------------------
# _t4_4_pam4_balance_check
# ---------------------------------------------------------------------------


class TestT44PAM4BalanceCheck:
    def test_balanced_pass(self):
        """All 3 eyes within 20% of average → PASS."""
        measurements = [
            _make_pam4_measurement(0, "upper", eye_height_mv=10.0),
            _make_pam4_measurement(0, "middle", eye_height_mv=10.0),
            _make_pam4_measurement(0, "lower", eye_height_mv=10.0),
        ]
        results = _t4_4_pam4_balance_check(measurements, _make_port())
        assert len(results) == 1
        assert results[0].verdict == Verdict.PASS
        assert "balanced" in results[0].message

    def test_imbalanced_warn(self):
        """One eye much smaller → WARN."""
        measurements = [
            _make_pam4_measurement(0, "upper", eye_height_mv=10.0),
            _make_pam4_measurement(0, "middle", eye_height_mv=10.0),
            _make_pam4_measurement(0, "lower", eye_height_mv=3.0),  # way below
        ]
        results = _t4_4_pam4_balance_check(measurements, _make_port())
        assert results[0].verdict == Verdict.WARN
        assert "imbalanced" in results[0].message

    def test_all_zero_heights_skipped(self):
        """All zeros are skipped (no result produced for that lane)."""
        measurements = [
            _make_pam4_measurement(0, "upper", eye_height_mv=0.0),
            _make_pam4_measurement(0, "middle", eye_height_mv=0.0),
            _make_pam4_measurement(0, "lower", eye_height_mv=0.0),
        ]
        results = _t4_4_pam4_balance_check(measurements, _make_port())
        # All zeros are filtered out → falls through to "No PAM4 eye height data" SKIP
        assert len(results) == 1
        assert results[0].verdict == Verdict.SKIP

    def test_no_data_skip(self):
        """Empty measurements → SKIP."""
        results = _t4_4_pam4_balance_check([], _make_port())
        assert len(results) == 1
        assert results[0].verdict == Verdict.SKIP

    def test_multiple_lanes(self):
        """Two lanes: one balanced, one not."""
        measurements = [
            _make_pam4_measurement(0, "upper", eye_height_mv=10.0),
            _make_pam4_measurement(0, "middle", eye_height_mv=10.0),
            _make_pam4_measurement(0, "lower", eye_height_mv=10.0),
            _make_pam4_measurement(1, "upper", eye_height_mv=10.0),
            _make_pam4_measurement(1, "middle", eye_height_mv=10.0),
            _make_pam4_measurement(1, "lower", eye_height_mv=2.0),
        ]
        results = _t4_4_pam4_balance_check(measurements, _make_port())
        assert len(results) == 2
        assert results[0].verdict == Verdict.PASS  # lane 0
        assert results[1].verdict == Verdict.WARN  # lane 1

    def test_within_20_percent_boundary(self):
        """Heights exactly at 20% boundary → PASS."""
        # avg = 10, 20% of 10 = 2, so 8.0 is exactly at boundary
        measurements = [
            _make_pam4_measurement(0, "upper", eye_height_mv=12.0),
            _make_pam4_measurement(0, "middle", eye_height_mv=10.0),
            _make_pam4_measurement(0, "lower", eye_height_mv=8.0),
        ]
        results = _t4_4_pam4_balance_check(measurements, _make_port())
        assert results[0].verdict == Verdict.PASS

    def test_measured_values_populated(self):
        measurements = [
            _make_pam4_measurement(0, "upper", eye_height_mv=10.0),
            _make_pam4_measurement(0, "middle", eye_height_mv=10.0),
            _make_pam4_measurement(0, "lower", eye_height_mv=10.0),
        ]
        results = _t4_4_pam4_balance_check(measurements, _make_port())
        mv = results[0].measured_values
        assert mv["lane"] == 0
        assert mv["upper_height_mv"] == 10.0
        assert mv["middle_height_mv"] == 10.0
        assert mv["lower_height_mv"] == 10.0
        assert mv["balanced"] is True


# ---------------------------------------------------------------------------
# _worst_case_per_lane
# ---------------------------------------------------------------------------


class TestWorstCasePerLane:
    def test_reduces_three_eyes_to_worst(self):
        measurements = [
            _make_pam4_measurement(0, "upper", 0.25, 12.0),
            _make_pam4_measurement(0, "middle", 0.20, 10.0),
            _make_pam4_measurement(0, "lower", 0.22, 8.0),
        ]
        result = _worst_case_per_lane(measurements)
        assert len(result) == 1
        assert result[0]["lane"] == 0
        assert result[0]["eye_width_ui"] == pytest.approx(0.20)
        assert result[0]["eye_height_mv"] == pytest.approx(8.0)

    def test_multiple_lanes(self):
        measurements = [
            _make_pam4_measurement(0, "upper", 0.25, 12.0),
            _make_pam4_measurement(0, "middle", 0.20, 10.0),
            _make_pam4_measurement(0, "lower", 0.22, 8.0),
            _make_pam4_measurement(1, "upper", 0.30, 15.0),
            _make_pam4_measurement(1, "middle", 0.28, 14.0),
            _make_pam4_measurement(1, "lower", 0.26, 13.0),
        ]
        result = _worst_case_per_lane(measurements)
        assert len(result) == 2
        # Lane 0 worst
        lane0 = next(r for r in result if r["lane"] == 0)
        assert lane0["eye_width_ui"] == pytest.approx(0.20)
        assert lane0["eye_height_mv"] == pytest.approx(8.0)
        # Lane 1 worst
        lane1 = next(r for r in result if r["lane"] == 1)
        assert lane1["eye_width_ui"] == pytest.approx(0.26)
        assert lane1["eye_height_mv"] == pytest.approx(13.0)

    def test_empty_input(self):
        assert _worst_case_per_lane([]) == []

    def test_single_measurement(self):
        measurements = [_make_pam4_measurement(0, "upper", 0.25, 12.0)]
        result = _worst_case_per_lane(measurements)
        assert len(result) == 1
        assert result[0]["eye_width_ui"] == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# run_signal_integrity_tests (integration-style with mocked engine)
# ---------------------------------------------------------------------------


class TestRunSignalIntegrityTests:
    def _make_mock_device(self):
        return MagicMock(), MagicMock()

    @patch("calypso.compliance.tests.signal_integrity.PcieConfigReader")
    @patch("calypso.compliance.tests.signal_integrity.LaneMarginingEngine")
    def test_speed_below_gen4_skips(self, mock_engine_cls, mock_reader_cls):
        """Gen3 (speed_code=3) should skip with T4.1 SKIP."""
        device, key = self._make_mock_device()
        mock_reader = MagicMock()
        mock_reader.get_link_status.return_value = MagicMock(current_speed="Gen3")
        mock_reader_cls.return_value = mock_reader

        port = _make_port(num_lanes=4)
        config = TestRunConfig()
        results, eye_data = run_signal_integrity_tests(device, key, "dev0", port, config)
        assert len(results) == 1
        assert results[0].verdict == Verdict.SKIP
        assert results[0].test_id == "T4.1"
        assert "Gen4+" in results[0].message

    @patch("calypso.compliance.tests.signal_integrity.PcieConfigReader")
    @patch("calypso.compliance.tests.signal_integrity.LaneMarginingEngine")
    def test_no_margining_cap_skips(self, mock_engine_cls, mock_reader_cls):
        """Engine init fails (no cap) → SKIP."""
        device, key = self._make_mock_device()
        mock_reader = MagicMock()
        mock_reader.get_link_status.return_value = MagicMock(current_speed="Gen4")
        mock_reader_cls.return_value = mock_reader
        mock_engine_cls.side_effect = ValueError("Lane Margining capability not found")

        port = _make_port(num_lanes=4)
        config = TestRunConfig()
        results, eye_data = run_signal_integrity_tests(device, key, "dev0", port, config)
        assert len(results) == 1
        assert results[0].verdict == Verdict.SKIP
        assert "not found" in results[0].message

    @patch("calypso.compliance.tests.signal_integrity.PcieConfigReader")
    @patch("calypso.compliance.tests.signal_integrity.LaneMarginingEngine")
    def test_gen4_nrz_path(self, mock_engine_cls, mock_reader_cls):
        """Gen4 runs NRZ path and produces T4.1, T4.2, T4.3 results."""
        device, key = self._make_mock_device()
        mock_reader = MagicMock()
        mock_reader.get_link_status.return_value = MagicMock(current_speed="Gen4")
        mock_reader_cls.return_value = mock_reader

        mock_engine = MagicMock()
        mock_engine.sweep_lane.return_value = _make_eye_sweep_result(
            eye_width_ui=0.30, eye_height_mv=20.0
        )
        mock_engine_cls.return_value = mock_engine

        port = _make_port(num_lanes=2)
        config = TestRunConfig()
        results, eye_data = run_signal_integrity_tests(device, key, "dev0", port, config)

        # T4.1: 2 lanes
        t41 = [r for r in results if r.test_id == "T4.1"]
        assert len(t41) == 2
        assert all(r.verdict == Verdict.PASS for r in t41)

        # T4.2: 2 lanes
        t42 = [r for r in results if r.test_id == "T4.2"]
        assert len(t42) == 2

        # T4.3: 1 comparison
        t43 = [r for r in results if r.test_id == "T4.3"]
        assert len(t43) == 1
        assert t43[0].verdict == Verdict.PASS

        # No T4.4 for NRZ
        t44 = [r for r in results if r.test_id == "T4.4"]
        assert len(t44) == 0

    @patch("calypso.compliance.tests.signal_integrity.PcieConfigReader")
    @patch("calypso.compliance.tests.signal_integrity.LaneMarginingEngine")
    def test_gen6_pam4_path(self, mock_engine_cls, mock_reader_cls):
        """Gen6 runs PAM4 path and produces T4.1, T4.2, T4.3, T4.4 results."""
        device, key = self._make_mock_device()
        mock_reader = MagicMock()
        mock_reader.get_link_status.return_value = MagicMock(current_speed="Gen6")
        mock_reader_cls.return_value = mock_reader

        pam4_result = PAM4SweepResult(
            lane=0,
            upper_eye=_make_eye_sweep_result(0, 1, 0.20, 10.0, 80),
            middle_eye=_make_eye_sweep_result(0, 2, 0.18, 9.0, 90),
            lower_eye=_make_eye_sweep_result(0, 3, 0.22, 11.0, 85),
            worst_eye_width_ui=0.18,
            worst_eye_height_mv=9.0,
            is_balanced=True,
            total_sweep_time_ms=255,
        )
        mock_engine = MagicMock()
        mock_engine.sweep_lane_pam4.return_value = pam4_result
        mock_engine_cls.return_value = mock_engine

        port = _make_port(num_lanes=1)
        config = TestRunConfig()
        results, eye_data = run_signal_integrity_tests(device, key, "dev0", port, config)

        # T4.1: 3 measurements (one per eye for 1 lane)
        t41 = [r for r in results if r.test_id == "T4.1"]
        assert len(t41) == 3
        assert all(r.verdict == Verdict.PASS for r in t41)
        # Check eye labels in names
        names = [r.test_name for r in t41]
        assert any("upper" in n for n in names)
        assert any("middle" in n for n in names)
        assert any("lower" in n for n in names)

        # T4.2: 3 per-eye spec checks
        t42 = [r for r in results if r.test_id == "T4.2"]
        assert len(t42) == 3

        # T4.3: 1 comparison (uses worst-case per lane)
        t43 = [r for r in results if r.test_id == "T4.3"]
        assert len(t43) == 1
        # Single lane → SKIP for lane comparison
        assert t43[0].verdict == Verdict.SKIP

        # T4.4: PAM4 balance check (10/9/11 mV → avg=10, all within 20%)
        t44 = [r for r in results if r.test_id == "T4.4"]
        assert len(t44) == 1
        assert t44[0].verdict == Verdict.PASS

        # eye_data should have modulation set
        assert eye_data.get("modulation") == "PAM4"

    @patch("calypso.compliance.tests.signal_integrity.PcieConfigReader")
    @patch("calypso.compliance.tests.signal_integrity.LaneMarginingEngine")
    def test_gen6_sweep_error_produces_error_result(self, mock_engine_cls, mock_reader_cls):
        """PAM4 sweep failure → T4.1 ERROR result."""
        device, key = self._make_mock_device()
        mock_reader = MagicMock()
        mock_reader.get_link_status.return_value = MagicMock(current_speed="Gen6")
        mock_reader_cls.return_value = mock_reader

        mock_engine = MagicMock()
        mock_engine.sweep_lane_pam4.side_effect = RuntimeError("hardware timeout")
        mock_engine_cls.return_value = mock_engine

        port = _make_port(num_lanes=1)
        config = TestRunConfig()
        results, eye_data = run_signal_integrity_tests(device, key, "dev0", port, config)

        t41 = [r for r in results if r.test_id == "T4.1"]
        assert len(t41) == 1
        assert t41[0].verdict == Verdict.ERROR
        assert "hardware timeout" in t41[0].message

    @patch("calypso.compliance.tests.signal_integrity.PcieConfigReader")
    @patch("calypso.compliance.tests.signal_integrity.LaneMarginingEngine")
    def test_nrz_sweep_error_produces_error_result(self, mock_engine_cls, mock_reader_cls):
        """NRZ sweep failure → T4.1 ERROR result."""
        device, key = self._make_mock_device()
        mock_reader = MagicMock()
        mock_reader.get_link_status.return_value = MagicMock(current_speed="Gen4")
        mock_reader_cls.return_value = mock_reader

        mock_engine = MagicMock()
        mock_engine.sweep_lane.side_effect = RuntimeError("margining timeout")
        mock_engine_cls.return_value = mock_engine

        port = _make_port(num_lanes=1)
        config = TestRunConfig()
        results, eye_data = run_signal_integrity_tests(device, key, "dev0", port, config)

        t41 = [r for r in results if r.test_id == "T4.1"]
        assert len(t41) == 1
        assert t41[0].verdict == Verdict.ERROR

    @patch("calypso.compliance.tests.signal_integrity.PcieConfigReader")
    @patch("calypso.compliance.tests.signal_integrity.LaneMarginingEngine")
    def test_gen5_nrz_path(self, mock_engine_cls, mock_reader_cls):
        """Gen5 still uses NRZ path (not PAM4)."""
        device, key = self._make_mock_device()
        mock_reader = MagicMock()
        mock_reader.get_link_status.return_value = MagicMock(current_speed="Gen5")
        mock_reader_cls.return_value = mock_reader

        mock_engine = MagicMock()
        mock_engine.sweep_lane.return_value = _make_eye_sweep_result(
            eye_width_ui=0.25, eye_height_mv=12.0
        )
        mock_engine_cls.return_value = mock_engine

        port = _make_port(num_lanes=1)
        config = TestRunConfig()
        results, eye_data = run_signal_integrity_tests(device, key, "dev0", port, config)

        # Should call sweep_lane, NOT sweep_lane_pam4
        mock_engine.sweep_lane.assert_called_once()
        mock_engine.sweep_lane_pam4.assert_not_called()

        # No T4.4 for Gen5 NRZ
        t44 = [r for r in results if r.test_id == "T4.4"]
        assert len(t44) == 0
