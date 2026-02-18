"""Unit tests for calypso.core.lane_margining — PAM4 3-eye + NRZ sweep engine."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import calypso.core.lane_margining as _lm_mod
from calypso.core.lane_margining import (
    _check_balance,
    _build_caps_response,
    _compute_eye_dimensions,
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
        sample_count=39,
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
    """Create a side_effect for _margin_single_point with status_code=0 (too many errors)."""
    def _side_effect(lane, cmd, receiver, payload):
        return MarginingLaneStatus(
            receiver_number=MarginingReceiverNumber.BROADCAST,
            margin_type=cmd,
            usage_model=0,
            margin_payload=(0x0 << 6) | 0,
        )
    return _side_effect


def _make_point(direction: str, step: int, passed: bool) -> MarginPoint:
    return MarginPoint(
        direction=direction,
        step=step,
        margin_value=0 if passed else 20,  # 0 errors = passed, >0 errors = failed
        status_code=2 if passed else 0,  # 2 = margining passed, 0 = error exceeded
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
# _compute_eye_dimensions
# ---------------------------------------------------------------------------


class TestComputeEyeDimensions:
    def test_basic_dimensions(self):
        timing = [
            _make_point("right", 1, True),
            _make_point("right", 2, True),
            _make_point("right", 3, False),
            _make_point("left", 1, True),
            _make_point("left", 2, True),
        ]
        voltage = [
            _make_point("up", 1, True),
            _make_point("up", 2, True),
            _make_point("down", 1, True),
        ]
        w_steps, h_steps, w_ui, h_mv = _compute_eye_dimensions(timing, voltage, 4, 4)
        # max_right=2, max_left=2 → width_steps=4
        # max_up=2, max_down=1 → height_steps=3
        assert w_steps == 4
        assert h_steps == 3
        # w_ui = steps_to_timing_ui(2,4)+steps_to_timing_ui(2,4) = 0.25+0.25 = 0.5
        assert w_ui == pytest.approx(0.5, abs=0.01)
        # h_mv = steps_to_voltage_mv(2,4)+steps_to_voltage_mv(1,4) = 250+125 = 375
        assert h_mv == pytest.approx(375.0, abs=1.0)

    def test_no_passing_points(self):
        timing = [_make_point("right", 1, False), _make_point("left", 1, False)]
        voltage = [_make_point("up", 1, False), _make_point("down", 1, False)]
        w_steps, h_steps, w_ui, h_mv = _compute_eye_dimensions(timing, voltage, 4, 4)
        assert w_steps == 0
        assert h_steps == 0
        assert w_ui == 0.0
        assert h_mv == 0.0

    def test_empty_lists(self):
        w_steps, h_steps, w_ui, h_mv = _compute_eye_dimensions([], [], 4, 4)
        assert w_steps == 0
        assert h_steps == 0


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
