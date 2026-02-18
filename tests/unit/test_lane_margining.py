"""Unit tests for calypso.core.lane_margining — PAM4 3-eye + NRZ sweep engine."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import calypso.core.lane_margining as _lm_mod
from calypso.core.lane_margining import (
    _check_balance,
    _build_caps_response,
    _compute_eye_dimensions,
    _contiguous_passing_steps,
    _count_sweep_steps,
    _error_threshold_from_sample_count,
    get_pam4_sweep_progress,
    get_pam4_sweep_result,
    get_sweep_progress,
    get_sweep_result,
    LaneMarginingEngine,
)
from calypso.models.phy import (
    LaneMarginCapabilities,
    MarginingCmd,
    MarginingLaneStatus,
    MarginingReceiverNumber,
)
from calypso.models.phy_api import (
    EyeSweepResult,
    LaneMarginCapabilitiesResponse,
    MarginPoint,
    PAM4SweepResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_module_state():
    """Ensure no state leaks between tests."""
    _lm_mod._active_sweeps.clear()
    _lm_mod._sweep_results.clear()
    _lm_mod._pam4_active_sweeps.clear()
    _lm_mod._pam4_sweep_results.clear()
    yield
    _lm_mod._active_sweeps.clear()
    _lm_mod._sweep_results.clear()
    _lm_mod._pam4_active_sweeps.clear()
    _lm_mod._pam4_sweep_results.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_caps(
    num_timing: int = 4,
    num_voltage: int = 4,
    max_timing_offset: int = 25,
    max_voltage_offset: int = 50,
) -> LaneMarginCapabilities:
    """Build a LaneMarginCapabilities with small step counts for fast tests."""
    return LaneMarginCapabilities(
        max_timing_offset=max_timing_offset,
        max_voltage_offset=max_voltage_offset,
        num_timing_steps=num_timing,
        num_voltage_steps=num_voltage,
        sample_count=0,
        sample_rate_voltage=False,
        sample_rate_timing=False,
        ind_up_down_voltage=True,
        ind_left_right_timing=True,
    )


def _margin_point_side_effect(error_count: int = 0):
    """Create a side_effect for _margin_single_point that echoes the command type.

    The real hardware responds with margin_type matching the command.  Timed-out
    points are now treated as failures, so the mock must echo ``cmd`` back in the
    response to be counted as passed.
    """
    def _side_effect(lane, cmd, receiver, payload):
        pld = (0x2 << 6) | (error_count & 0x3F)
        return MarginingLaneStatus(
            receiver_number=MarginingReceiverNumber.BROADCAST,
            margin_type=cmd,
            usage_model=0,
            margin_payload=pld,
        )
    return _side_effect


def _margin_point_fail_side_effect():
    """Create a side_effect for _margin_single_point with status_code=0 and errors.

    Returns status_code=0 (too many errors) with error_count=20 so the point
    fails both the spec criterion (status_code != 2) and the error_count
    criterion (error_count > 0).
    """
    def _side_effect(lane, cmd, receiver, payload):
        return MarginingLaneStatus(
            receiver_number=MarginingReceiverNumber.BROADCAST,
            margin_type=cmd,
            usage_model=0,
            margin_payload=(0x0 << 6) | 20,
        )
    return _side_effect


def _make_point(
    direction: str,
    step: int,
    passed: bool,
    *,
    margin_value: int | None = None,
    status_code: int | None = None,
) -> MarginPoint:
    if margin_value is None:
        margin_value = 0 if passed else 20
    if status_code is None:
        status_code = 2 if passed else 0
    return MarginPoint(
        direction=direction,
        step=step,
        margin_value=margin_value,
        status_code=status_code,
        passed=passed,
    )


def _make_eye_sweep_result(
    lane: int = 0,
    receiver: int = 0,
    eye_width_ui: float = 0.30,
    eye_height_mv: float = 15.0,
    sweep_time_ms: int = 100,
) -> EyeSweepResult:
    """Build a minimal EyeSweepResult for PAM4 aggregation tests."""
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


def _patch_engine_init(engine: LaneMarginingEngine) -> None:
    """Bypass __init__ hardware reads by directly setting internal attributes."""
    engine._port_device = None
    engine._config = MagicMock()
    engine._margining_offset = 0x100


def _create_engine() -> LaneMarginingEngine:
    """Create a LaneMarginingEngine with mocked hardware access."""
    with patch.object(LaneMarginingEngine, "__init__", lambda self, *a, **k: None):
        engine = LaneMarginingEngine.__new__(LaneMarginingEngine)
    _patch_engine_init(engine)
    return engine


# ---------------------------------------------------------------------------
# _check_balance
# ---------------------------------------------------------------------------


class TestCheckBalance:
    def test_equal_values_balanced(self):
        assert _check_balance(10.0, 10.0, 10.0) is True

    def test_within_20_percent_balanced(self):
        # avg = 10, each within 20% of 10 (8-12 range)
        assert _check_balance(10.0, 8.0, 12.0) is True

    def test_just_at_boundary_balanced(self):
        # avg = (10+10+8)/3 = 9.333, max deviation = |8-9.333|/9.333 = 14.3% < 20%
        assert _check_balance(10.0, 10.0, 8.0) is True

    def test_beyond_20_percent_imbalanced(self):
        # avg = 10, 7.9 is > 20% below avg
        assert _check_balance(10.0, 12.1, 7.9) is False

    def test_all_zeros_balanced(self):
        assert _check_balance(0.0, 0.0, 0.0) is True

    def test_large_spread_imbalanced(self):
        assert _check_balance(5.0, 10.0, 20.0) is False

    def test_one_zero_imbalanced(self):
        # avg = 6.67, 0 is 100% below avg
        assert _check_balance(0.0, 10.0, 10.0) is False


# ---------------------------------------------------------------------------
# _build_caps_response
# ---------------------------------------------------------------------------


class TestBuildCapsResponse:
    def test_converts_all_fields(self):
        caps = _make_caps(
            num_timing=10,
            num_voltage=8,
            max_timing_offset=30,
            max_voltage_offset=60,
        )
        resp = _build_caps_response(caps)
        assert isinstance(resp, LaneMarginCapabilitiesResponse)
        assert resp.max_timing_offset == 30
        assert resp.max_voltage_offset == 60
        assert resp.num_timing_steps == 10
        assert resp.num_voltage_steps == 8
        assert resp.ind_up_down_voltage is True
        assert resp.ind_left_right_timing is True


# ---------------------------------------------------------------------------
# _error_threshold_from_sample_count
# ---------------------------------------------------------------------------


class TestErrorThreshold:
    def test_sample_count_0(self):
        # 128 * 2^0 = 128 samples, 128 * 0.01 = 1.28 → 1
        assert _error_threshold_from_sample_count(0) == 1

    def test_sample_count_3(self):
        # 128 * 2^3 = 1024 samples, 1024 * 0.01 = 10.24 → 10
        assert _error_threshold_from_sample_count(3) == 10

    def test_sample_count_7(self):
        # 128 * 2^7 = 16384 samples, 16384 * 0.01 = 163 → capped at 63
        assert _error_threshold_from_sample_count(7) == 63

    def test_minimum_is_1(self):
        # Even if math gives 0, threshold should be at least 1
        assert _error_threshold_from_sample_count(0) >= 1


# ---------------------------------------------------------------------------
# _contiguous_passing_steps
# ---------------------------------------------------------------------------


class TestContiguousPassingSteps:
    def test_all_pass(self):
        pts = [
            _make_point("right", 1, False, margin_value=1),
            _make_point("right", 2, False, margin_value=2),
            _make_point("right", 3, False, margin_value=3),
        ]
        assert _contiguous_passing_steps(pts, "right", error_threshold=5) == 3

    def test_stops_at_first_failure(self):
        pts = [
            _make_point("right", 1, False, margin_value=1),
            _make_point("right", 2, False, margin_value=2),
            _make_point("right", 3, False, margin_value=10),  # exceeds threshold
            _make_point("right", 4, False, margin_value=1),  # below, but non-contiguous
        ]
        assert _contiguous_passing_steps(pts, "right", error_threshold=5) == 2

    def test_stops_at_nak(self):
        pts = [
            _make_point("right", 1, False, margin_value=1),
            _make_point("right", 2, False, margin_value=2, status_code=3),  # NAK
        ]
        assert _contiguous_passing_steps(pts, "right", error_threshold=5) == 1

    def test_first_step_fails(self):
        pts = [_make_point("right", 1, False, margin_value=20)]
        assert _contiguous_passing_steps(pts, "right", error_threshold=5) == 0

    def test_empty_list(self):
        assert _contiguous_passing_steps([], "right", error_threshold=5) == 0

    def test_filters_by_direction(self):
        pts = [
            _make_point("right", 1, False, margin_value=1),
            _make_point("left", 1, False, margin_value=1),
            _make_point("right", 2, False, margin_value=20),  # fails
        ]
        assert _contiguous_passing_steps(pts, "right", error_threshold=5) == 1
        assert _contiguous_passing_steps(pts, "left", error_threshold=5) == 1

    def test_unsorted_input(self):
        pts = [
            _make_point("up", 3, False, margin_value=2),
            _make_point("up", 1, False, margin_value=1),
            _make_point("up", 2, False, margin_value=1),
        ]
        assert _contiguous_passing_steps(pts, "up", error_threshold=5) == 3


# ---------------------------------------------------------------------------
# _compute_eye_dimensions
# ---------------------------------------------------------------------------


class TestComputeEyeDimensions:
    def test_basic_dimensions_with_zero_errors(self):
        """Points with margin_value=0 pass any threshold >= 0."""
        timing = [
            _make_point("right", 1, True, margin_value=0),
            _make_point("right", 2, True, margin_value=0),
            _make_point("right", 3, False, margin_value=20),
            _make_point("left", 1, True, margin_value=0),
            _make_point("left", 2, True, margin_value=0),
        ]
        voltage = [
            _make_point("up", 1, True, margin_value=0),
            _make_point("up", 2, True, margin_value=0),
            _make_point("down", 1, True, margin_value=0),
        ]
        # sample_count=0 → threshold=1, but margin_value=0 ≤ 1
        w_steps, h_steps, w_ui, h_mv = _compute_eye_dimensions(
            timing, voltage, 4, 4, sample_count=0,
        )
        assert w_steps == 4  # right=2 + left=2
        assert h_steps == 3  # up=2 + down=1

    def test_threshold_based_boundary(self):
        """Non-zero errors below threshold count as inside the eye."""
        timing = [
            _make_point("right", 1, False, margin_value=1),
            _make_point("right", 2, False, margin_value=2),
            _make_point("right", 3, False, margin_value=5),
            _make_point("right", 4, False, margin_value=15),
            _make_point("left", 1, False, margin_value=1),
            _make_point("left", 2, False, margin_value=8),
        ]
        voltage = [
            _make_point("up", 1, False, margin_value=3),
            _make_point("up", 2, False, margin_value=5),
            _make_point("up", 3, False, margin_value=20),
            _make_point("down", 1, False, margin_value=4),
            _make_point("down", 2, False, margin_value=12),
        ]
        # sample_count=3 → threshold=10
        w_steps, h_steps, _, _ = _compute_eye_dimensions(
            timing, voltage, 10, 10, sample_count=3,
        )
        # right: steps 1(1),2(2),3(5) pass (≤10), step 4(15) fails → 3
        # left: steps 1(1) pass, step 2(8) pass → 2
        assert w_steps == 5  # 3 + 2
        # up: steps 1(3),2(5) pass, step 3(20) fails → 2
        # down: step 1(4) pass, step 2(12) fails → 1
        assert h_steps == 3  # 2 + 1

    def test_no_passing_points(self):
        timing = [_make_point("right", 1, False, margin_value=20)]
        voltage = [_make_point("up", 1, False, margin_value=20)]
        w_steps, h_steps, w_ui, h_mv = _compute_eye_dimensions(
            timing, voltage, 4, 4, sample_count=0,
        )
        assert w_steps == 0
        assert h_steps == 0
        assert w_ui == 0.0
        assert h_mv == 0.0

    def test_empty_lists(self):
        w_steps, h_steps, w_ui, h_mv = _compute_eye_dimensions([], [], 4, 4)
        assert w_steps == 0
        assert h_steps == 0

    def test_physical_units_conversion(self):
        """Verify UI and mV conversion from contiguous step counts."""
        timing = [
            _make_point("right", 1, True, margin_value=0),
            _make_point("right", 2, True, margin_value=0),
            _make_point("left", 1, True, margin_value=0),
            _make_point("left", 2, True, margin_value=0),
        ]
        voltage = [
            _make_point("up", 1, True, margin_value=0),
            _make_point("down", 1, True, margin_value=0),
        ]
        w_steps, h_steps, w_ui, h_mv = _compute_eye_dimensions(
            timing, voltage, 4, 4, sample_count=0,
        )
        assert w_steps == 4
        assert h_steps == 2
        # w_ui = steps_to_timing_ui(2,4)+steps_to_timing_ui(2,4) = 0.25+0.25 = 0.5
        assert w_ui == pytest.approx(0.5, abs=0.01)
        # h_mv = steps_to_voltage_mv(1,4)+steps_to_voltage_mv(1,4) = 125+125 = 250
        assert h_mv == pytest.approx(250.0, abs=1.0)


# ---------------------------------------------------------------------------
# _count_sweep_steps
# ---------------------------------------------------------------------------


class TestCountSweepSteps:
    def test_all_independent(self):
        caps = _make_caps(num_timing=10, num_voltage=8)
        # ind_left_right=True, ind_up_down=True → 2 timing dirs + 2 voltage dirs
        assert _count_sweep_steps(caps) == (10 * 2) + (8 * 2)  # 36

    def test_no_independent_timing(self):
        caps = _make_caps(num_timing=10, num_voltage=8)
        caps = LaneMarginCapabilities(
            **{**caps.__dict__, "ind_left_right_timing": False}
        )
        # Only right timing → 10 + (8 * 2) = 26
        assert _count_sweep_steps(caps) == 10 + 16

    def test_no_independent_voltage(self):
        caps = _make_caps(num_timing=10, num_voltage=8)
        caps = LaneMarginCapabilities(
            **{**caps.__dict__, "ind_up_down_voltage": False}
        )
        # Only up voltage → (10 * 2) + 8 = 28
        assert _count_sweep_steps(caps) == 20 + 8

    def test_neither_independent(self):
        caps = _make_caps(num_timing=31, num_voltage=63)
        caps = LaneMarginCapabilities(
            **{
                **caps.__dict__,
                "ind_left_right_timing": False,
                "ind_up_down_voltage": False,
            }
        )
        # Only right + up → 31 + 63 = 94
        assert _count_sweep_steps(caps) == 94


# ---------------------------------------------------------------------------
# State getters: NRZ
# ---------------------------------------------------------------------------


class TestNRZStateGetters:
    def test_get_sweep_progress_default_idle(self):
        progress = get_sweep_progress("nonexistent_dev", 99)
        assert progress.status == "idle"
        assert progress.lane == 99
        assert progress.percent == 0.0

    def test_get_sweep_result_default_none(self):
        result = get_sweep_result("nonexistent_dev", 99)
        assert result is None


# ---------------------------------------------------------------------------
# State getters: PAM4
# ---------------------------------------------------------------------------


class TestPAM4StateGetters:
    def test_get_pam4_sweep_progress_default_idle(self):
        progress = get_pam4_sweep_progress("nonexistent_dev", 99)
        assert progress.status == "idle"
        assert progress.lane == 99
        assert progress.current_eye == ""
        assert progress.current_eye_index == 0
        assert progress.overall_total_steps == 0
        assert progress.percent == 0.0

    def test_get_pam4_sweep_result_default_none(self):
        result = get_pam4_sweep_result("nonexistent_dev", 99)
        assert result is None


# ---------------------------------------------------------------------------
# _resolve_receiver (Gen6 PAM4 receiver auto-resolution)
# ---------------------------------------------------------------------------


class TestResolveReceiver:
    def test_broadcast_at_nrz_unchanged(self):
        engine = _create_engine()
        result = engine._resolve_receiver(MarginingReceiverNumber.BROADCAST, speed_code=4)
        assert result == MarginingReceiverNumber.BROADCAST

    def test_broadcast_at_gen5_unchanged(self):
        engine = _create_engine()
        result = engine._resolve_receiver(MarginingReceiverNumber.BROADCAST, speed_code=5)
        assert result == MarginingReceiverNumber.BROADCAST

    def test_broadcast_at_gen6_becomes_receiver_a(self):
        engine = _create_engine()
        result = engine._resolve_receiver(MarginingReceiverNumber.BROADCAST, speed_code=6)
        assert result == MarginingReceiverNumber.RECEIVER_A

    def test_explicit_receiver_a_at_gen6_unchanged(self):
        engine = _create_engine()
        result = engine._resolve_receiver(MarginingReceiverNumber.RECEIVER_A, speed_code=6)
        assert result == MarginingReceiverNumber.RECEIVER_A

    def test_explicit_receiver_b_at_gen6_unchanged(self):
        engine = _create_engine()
        result = engine._resolve_receiver(MarginingReceiverNumber.RECEIVER_B, speed_code=6)
        assert result == MarginingReceiverNumber.RECEIVER_B

    def test_pam4_broadcast_at_gen6_unchanged(self):
        engine = _create_engine()
        result = engine._resolve_receiver(MarginingReceiverNumber.PAM4_BROADCAST, speed_code=6)
        assert result == MarginingReceiverNumber.PAM4_BROADCAST


# ---------------------------------------------------------------------------
# _clear_lane_command
# ---------------------------------------------------------------------------


class TestClearLaneCommand:
    @patch("calypso.core.lane_margining._CLEAR_SETTLE_S", 0)
    def test_writes_no_command(self):
        """Writes NO_COMMAND control word to the lane."""
        engine = _create_engine()
        engine._write_lane_control = MagicMock()
        engine._clear_lane_command(0, MarginingReceiverNumber.BROADCAST)
        engine._write_lane_control.assert_called_once()
        control = engine._write_lane_control.call_args[0][1]
        assert control.margin_type == MarginingCmd.NO_COMMAND

    @patch("calypso.core.lane_margining._CLEAR_SETTLE_S", 0)
    def test_uses_specified_receiver(self):
        """Preserves the receiver number in the NO_COMMAND control word."""
        engine = _create_engine()
        engine._write_lane_control = MagicMock()
        engine._clear_lane_command(0, MarginingReceiverNumber.RECEIVER_A)
        control = engine._write_lane_control.call_args[0][1]
        assert control.receiver_number == MarginingReceiverNumber.RECEIVER_A


# ---------------------------------------------------------------------------
# _execute_single_sweep
# ---------------------------------------------------------------------------


class TestExecuteSingleSweep:
    def _make_engine_with_mocked_hw(self, caps=None):
        engine = _create_engine()
        if caps is None:
            caps = _make_caps(num_timing=2, num_voltage=2)
        engine.get_capabilities = MagicMock(return_value=caps)
        engine._margin_single_point = MagicMock(side_effect=_margin_point_side_effect())
        engine._go_to_normal_and_confirm = MagicMock()
        return engine

    def test_successful_sweep_returns_result(self):
        engine = self._make_engine_with_mocked_hw()
        result = engine._execute_single_sweep(
            lane=0,
            receiver=MarginingReceiverNumber.BROADCAST,
        )
        assert isinstance(result, EyeSweepResult)
        assert result.lane == 0
        assert result.receiver == int(MarginingReceiverNumber.BROADCAST)
        assert len(result.timing_points) == 4  # 2 right + 2 left
        assert len(result.voltage_points) == 4  # 2 up + 2 down
        assert result.eye_width_steps > 0
        assert result.eye_height_steps > 0

    def test_zero_steps_raises(self):
        caps = _make_caps(num_timing=0, num_voltage=0)
        engine = self._make_engine_with_mocked_hw(caps)
        with pytest.raises(ValueError, match="0 margining steps"):
            engine._execute_single_sweep(
                lane=0,
                receiver=MarginingReceiverNumber.BROADCAST,
                caps=caps,
            )

    def test_progress_callback_called(self):
        engine = self._make_engine_with_mocked_hw()
        callback = MagicMock()
        caps = _make_caps(num_timing=2, num_voltage=2)
        engine._execute_single_sweep(
            lane=0,
            receiver=MarginingReceiverNumber.BROADCAST,
            progress_callback=callback,
            caps=caps,
        )
        # 2 right + 2 left + 2 up + 2 down = 8 steps
        assert callback.call_count == 8
        # Last call should be (8, 8)
        callback.assert_called_with(8, 8)

    def test_caps_passed_skips_query(self):
        engine = self._make_engine_with_mocked_hw()
        caps = _make_caps(num_timing=2, num_voltage=2)
        engine._execute_single_sweep(
            lane=0,
            receiver=MarginingReceiverNumber.BROADCAST,
            caps=caps,
        )
        # get_capabilities should NOT be called when caps is provided
        engine.get_capabilities.assert_not_called()

    def test_caps_not_passed_queries_hw(self):
        engine = self._make_engine_with_mocked_hw()
        engine._execute_single_sweep(
            lane=0,
            receiver=MarginingReceiverNumber.BROADCAST,
        )
        engine.get_capabilities.assert_called_once()

    def test_failing_points_produce_zero_eye(self):
        engine = _create_engine()
        engine.get_capabilities = MagicMock(return_value=_make_caps(num_timing=2, num_voltage=2))
        engine._margin_single_point = MagicMock(side_effect=_margin_point_fail_side_effect())
        engine._go_to_normal_and_confirm = MagicMock()
        caps = _make_caps(num_timing=2, num_voltage=2)
        result = engine._execute_single_sweep(
            lane=0,
            receiver=MarginingReceiverNumber.BROADCAST,
            caps=caps,
        )
        assert result.eye_width_steps == 0
        assert result.eye_height_steps == 0
        assert result.eye_width_ui == 0.0
        assert result.eye_height_mv == 0.0

    def test_mirrors_when_ind_flags_false(self):
        """When ind_left_right/ind_up_down are False, only sweeps one direction
        and mirrors the result, producing points for both directions."""
        caps = LaneMarginCapabilities(
            max_timing_offset=25,
            max_voltage_offset=50,
            num_timing_steps=2,
            num_voltage_steps=2,
            sample_count=0,
            sample_rate_voltage=False,
            sample_rate_timing=False,
            ind_up_down_voltage=False,
            ind_left_right_timing=False,
        )
        engine = self._make_engine_with_mocked_hw(caps)
        result = engine._execute_single_sweep(
            lane=0,
            receiver=MarginingReceiverNumber.BROADCAST,
            caps=caps,
        )
        # Only right+up swept (2+2=4 margin_single_point calls), then mirrored
        assert engine._margin_single_point.call_count == 4
        # But result contains all 4 directions via mirroring
        assert len(result.timing_points) == 4  # 2 right + 2 mirrored left
        assert len(result.voltage_points) == 4  # 2 up + 2 mirrored down
        right_pts = [p for p in result.timing_points if p.direction == "right"]
        left_pts = [p for p in result.timing_points if p.direction == "left"]
        assert len(right_pts) == 2
        assert len(left_pts) == 2
        # Mirrored points should have same values
        for rp, lp in zip(right_pts, left_pts):
            assert rp.step == lp.step
            assert rp.margin_value == lp.margin_value
            assert rp.passed == lp.passed

    def test_progress_with_ind_flags_false(self):
        """Progress callback receives correct total when directions are halved."""
        caps = LaneMarginCapabilities(
            max_timing_offset=25,
            max_voltage_offset=50,
            num_timing_steps=2,
            num_voltage_steps=2,
            sample_count=0,
            sample_rate_voltage=False,
            sample_rate_timing=False,
            ind_up_down_voltage=False,
            ind_left_right_timing=False,
        )
        engine = self._make_engine_with_mocked_hw(caps)
        callback = MagicMock()
        engine._execute_single_sweep(
            lane=0,
            receiver=MarginingReceiverNumber.BROADCAST,
            progress_callback=callback,
            caps=caps,
        )
        # Only 4 steps swept (right 2 + up 2), not 8
        assert callback.call_count == 4
        callback.assert_called_with(4, 4)


# ---------------------------------------------------------------------------
# sweep_lane (NRZ)
# ---------------------------------------------------------------------------


class TestSweepLane:
    def _make_engine(self):
        engine = _create_engine()
        caps = _make_caps(num_timing=2, num_voltage=2)
        engine.get_capabilities = MagicMock(return_value=caps)
        engine._margin_single_point = MagicMock(side_effect=_margin_point_side_effect())
        engine._go_to_normal_and_confirm = MagicMock()
        engine.reset_lane = MagicMock()
        # NRZ speed so _resolve_receiver keeps BROADCAST unchanged
        engine._get_link_state = MagicMock(return_value=(4, True, False))
        return engine

    def test_successful_sweep_stores_result(self):
        engine = self._make_engine()
        result = engine.sweep_lane(lane=0, device_id="test_dev")
        assert isinstance(result, EyeSweepResult)
        # Check state was updated
        progress = get_sweep_progress("test_dev", 0)
        assert progress.status == "complete"
        assert progress.percent == 100.0
        stored = get_sweep_result("test_dev", 0)
        assert stored is not None
        assert stored.lane == 0

    def test_resets_lane_after_sweep(self):
        engine = self._make_engine()
        engine.sweep_lane(lane=0, device_id="test_reset")
        engine.reset_lane.assert_called_once()

    def test_zero_steps_sets_error_state(self):
        engine = _create_engine()
        engine.get_capabilities = MagicMock(return_value=_make_caps(num_timing=0, num_voltage=0))
        engine._get_link_state = MagicMock(return_value=(4, True, False))
        with pytest.raises(ValueError, match="0 margining steps"):
            engine.sweep_lane(lane=0, device_id="test_zero")
        progress = get_sweep_progress("test_zero", 0)
        assert progress.status == "error"

    def test_sweep_error_resets_lane(self):
        engine = _create_engine()
        caps = _make_caps(num_timing=2, num_voltage=2)
        engine.get_capabilities = MagicMock(return_value=caps)
        engine._margin_single_point = MagicMock(side_effect=RuntimeError("hw fail"))
        engine._go_to_normal_and_confirm = MagicMock()
        engine.reset_lane = MagicMock()
        engine._get_link_state = MagicMock(return_value=(4, True, False))
        with pytest.raises(RuntimeError, match="hw fail"):
            engine.sweep_lane(lane=0, device_id="test_err")
        engine.reset_lane.assert_called_once()
        progress = get_sweep_progress("test_err", 0)
        assert progress.status == "error"
        assert "hw fail" in progress.error


# ---------------------------------------------------------------------------
# sweep_lane_pam4
# ---------------------------------------------------------------------------


class TestSweepLanePAM4:
    def _make_engine(self):
        engine = _create_engine()
        caps = _make_caps(num_timing=2, num_voltage=2)
        engine.get_capabilities = MagicMock(return_value=caps)
        engine._margin_single_point = MagicMock(side_effect=_margin_point_side_effect())
        engine._go_to_normal_and_confirm = MagicMock()
        engine.reset_lane = MagicMock()
        return engine

    def test_successful_pam4_sweep(self):
        engine = self._make_engine()
        result = engine.sweep_lane_pam4(lane=0, device_id="pam4_dev")
        assert isinstance(result, PAM4SweepResult)
        assert result.lane == 0
        assert result.modulation == "PAM4"
        assert result.upper_eye is not None
        assert result.middle_eye is not None
        assert result.lower_eye is not None
        assert result.worst_eye_width_ui >= 0
        assert result.worst_eye_height_mv >= 0
        assert result.total_sweep_time_ms >= 0

    def test_pam4_stores_result(self):
        engine = self._make_engine()
        engine.sweep_lane_pam4(lane=0, device_id="pam4_store")
        stored = get_pam4_sweep_result("pam4_store", 0)
        assert stored is not None
        assert stored.modulation == "PAM4"

    def test_pam4_progress_complete(self):
        engine = self._make_engine()
        engine.sweep_lane_pam4(lane=0, device_id="pam4_prog")
        progress = get_pam4_sweep_progress("pam4_prog", 0)
        assert progress.status == "complete"
        assert progress.percent == 100.0

    def test_pam4_resets_each_receiver(self):
        engine = self._make_engine()
        engine.sweep_lane_pam4(lane=0, device_id="pam4_reset")
        # reset_lane called: 1x after pre-flight + 3x before each eye + 3x after each eye = 7
        assert engine.reset_lane.call_count == 7

    def test_pam4_queries_caps_once_with_receiver_a(self):
        engine = self._make_engine()
        engine.sweep_lane_pam4(lane=0, device_id="pam4_caps")
        # Capabilities queried once with RECEIVER_A — some hardware only
        # responds to report commands on RECEIVER_A, so we cache and reuse.
        engine.get_capabilities.assert_called_once_with(
            lane=0, receiver=MarginingReceiverNumber.RECEIVER_A,
        )

    def test_pam4_zero_steps_raises(self):
        engine = _create_engine()
        engine.get_capabilities = MagicMock(return_value=_make_caps(num_timing=0, num_voltage=0))
        engine.reset_lane = MagicMock()
        with pytest.raises(ValueError, match="0 margining steps"):
            engine.sweep_lane_pam4(lane=0, device_id="pam4_zero")
        progress = get_pam4_sweep_progress("pam4_zero", 0)
        assert progress.status == "error"

    def test_pam4_error_resets_all_receivers(self):
        engine = _create_engine()
        caps = _make_caps(num_timing=2, num_voltage=2)
        engine.get_capabilities = MagicMock(return_value=caps)
        # Fail on the second margin_single_point call (during first eye sweep)
        call_count = 0

        def _fail_on_second(lane, cmd, receiver, payload):
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                raise RuntimeError("hw fail during pam4")
            pld = (0x2 << 6) | 0
            return MarginingLaneStatus(
                receiver_number=MarginingReceiverNumber.BROADCAST,
                margin_type=cmd,
                usage_model=0,
                margin_payload=pld,
            )

        engine._margin_single_point = MagicMock(side_effect=_fail_on_second)
        engine._go_to_normal_and_confirm = MagicMock()
        engine.reset_lane = MagicMock()
        with pytest.raises(RuntimeError, match="hw fail during pam4"):
            engine.sweep_lane_pam4(lane=0, device_id="pam4_err")
        # Should attempt to reset: 1x after pre-flight + 1x before first eye + 3x error cleanup = 5
        assert engine.reset_lane.call_count == 5
        # Error cleanup resets include all 3 receivers (calls with 2 args)
        error_resets = [
            call.args[1]
            for call in engine.reset_lane.call_args_list
            if len(call.args) > 1
        ]
        assert MarginingReceiverNumber.RECEIVER_A in error_resets
        assert MarginingReceiverNumber.RECEIVER_B in error_resets
        assert MarginingReceiverNumber.RECEIVER_C in error_resets
        progress = get_pam4_sweep_progress("pam4_err", 0)
        assert progress.status == "error"

    def test_pam4_balance_flag(self):
        engine = _create_engine()

        # Return different caps per receiver to create different eye heights
        # by returning different statuses per direction
        caps = _make_caps(num_timing=1, num_voltage=1)
        engine.get_capabilities = MagicMock(return_value=caps)
        engine._margin_single_point = MagicMock(side_effect=_margin_point_side_effect(20))
        engine._go_to_normal_and_confirm = MagicMock()
        engine.reset_lane = MagicMock()

        result = engine.sweep_lane_pam4(lane=0, device_id="pam4_bal")
        # All eyes should have the same dimensions since same mock status → balanced
        assert result.is_balanced is True

    def test_pam4_worst_case_aggregation(self):
        engine = _create_engine()
        caps = _make_caps(num_timing=1, num_voltage=1)
        engine.get_capabilities = MagicMock(return_value=caps)
        engine._margin_single_point = MagicMock(side_effect=_margin_point_side_effect(20))
        engine._go_to_normal_and_confirm = MagicMock()
        engine.reset_lane = MagicMock()

        result = engine.sweep_lane_pam4(lane=0, device_id="pam4_worst")
        # All eyes identical → worst = same as any individual
        assert result.worst_eye_width_ui == result.upper_eye.eye_width_ui
        assert result.worst_eye_height_mv == result.upper_eye.eye_height_mv
