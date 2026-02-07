"""API response models for lane margining and eye diagram endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class LaneMarginCapabilitiesResponse(BaseModel):
    """Port-level lane margining capabilities."""

    max_timing_offset: int
    max_voltage_offset: int
    num_timing_steps: int
    num_voltage_steps: int
    ind_up_down_voltage: bool
    ind_left_right_timing: bool


class MarginPoint(BaseModel):
    """A single margining measurement point."""

    direction: str          # "left", "right", "up", "down"
    step: int
    margin_value: int
    status_code: int        # 0=too_close, 1=in_progress, 2=setup_for_nak, 3=complete
    passed: bool            # status_code == 3 and margin_value > 0


class EyeSweepResult(BaseModel):
    """Complete eye sweep result for a single lane."""

    lane: int
    receiver: int
    timing_points: list[MarginPoint]
    voltage_points: list[MarginPoint]
    capabilities: LaneMarginCapabilitiesResponse
    eye_width_steps: int    # max passing timing step (left + right)
    eye_height_steps: int   # max passing voltage step (up + down)
    eye_width_ui: float     # converted to Unit Intervals
    eye_height_mv: float    # converted to millivolts
    sweep_time_ms: int


class SweepProgress(BaseModel):
    """Progress tracking for an active sweep."""

    status: str             # "idle", "running", "complete", "error"
    lane: int
    current_step: int
    total_steps: int
    percent: float
    error: str | None = None
