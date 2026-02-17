"""PCIe spec-derived pass/fail thresholds per speed grade."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EyeThreshold:
    """Eye diagram pass/fail thresholds for a given speed generation."""

    speed_gen: int
    min_eye_width_ui: float
    min_eye_height_mv: float
    max_ber: float


# Thresholds derived from PCIe CEM 6.0 and PCIe Base Spec 6.0.1.
# Gen3/4 use NRZ (BER 1e-12). Gen5 uses NRZ with FEC (BER 1e-6). Gen6 uses PAM4 (BER 1e-6).
EYE_THRESHOLDS: dict[int, EyeThreshold] = {
    3: EyeThreshold(speed_gen=3, min_eye_width_ui=0.30, min_eye_height_mv=15.0, max_ber=1e-12),
    4: EyeThreshold(speed_gen=4, min_eye_width_ui=0.25, min_eye_height_mv=15.0, max_ber=1e-12),
    5: EyeThreshold(speed_gen=5, min_eye_width_ui=0.20, min_eye_height_mv=10.0, max_ber=1e-6),
    6: EyeThreshold(speed_gen=6, min_eye_width_ui=0.15, min_eye_height_mv=8.0, max_ber=1e-6),
}

VALID_MPS_VALUES: set[int] = {128, 256, 512, 1024, 2048, 4096}

VALID_MRRS_VALUES: set[int] = {128, 256, 512, 1024, 2048, 4096}

# Flag lanes whose eye dimensions are >30% worse than the average
LANE_MARGIN_OUTLIER_PERCENT: float = 30.0

# Speed code to generation number mapping
SPEED_CODE_TO_GEN: dict[int, int] = {
    1: 1,
    2: 2,
    3: 3,
    4: 4,
    5: 5,
    6: 6,
}

# Gen name string to speed code
GEN_NAME_TO_SPEED_CODE: dict[str, int] = {
    "Gen1": 1,
    "Gen2": 2,
    "Gen3": 3,
    "Gen4": 4,
    "Gen5": 5,
    "Gen6": 6,
}
