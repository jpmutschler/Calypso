"""Shared threshold constants for recipe verdict logic.

Centralises BER and eye-margin thresholds with PCIe 6.1 spec references
so every recipe and renderer uses one source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BerThresholds:
    """BER pass/warn/fail thresholds for a given speed and measurement type."""

    pass_threshold: float
    warn_threshold: float
    fail_threshold: float
    spec_ref: str = ""


@dataclass(frozen=True)
class EyeThresholds:
    """Eye width pass/warn thresholds in UI."""

    pass_ui: float
    warn_ui: float
    fail_ui: float
    spec_ref: str = ""


# ---------------------------------------------------------------------------
# Pre-FEC BER thresholds (SERDES / UTP layer)
# PCIe 6.1 Section 8.3 — SerDes raw error rate targets
# ---------------------------------------------------------------------------

PRE_FEC_BER: dict[str, BerThresholds] = {
    "Gen1": BerThresholds(1e-12, 1e-9, 1e-6, "PCIe 6.1 §8.3"),
    "Gen2": BerThresholds(1e-12, 1e-9, 1e-6, "PCIe 6.1 §8.3"),
    "Gen3": BerThresholds(1e-12, 1e-9, 1e-6, "PCIe 6.1 §8.3"),
    "Gen4": BerThresholds(1e-12, 1e-9, 1e-6, "PCIe 6.1 §8.3"),
    "Gen5": BerThresholds(1e-12, 1e-9, 1e-6, "PCIe 6.1 §8.3"),
    # Gen6 PAM4: pre-FEC raw error rate is intentionally higher
    "Gen6": BerThresholds(1e-6, 1e-4, 1e-3, "PCIe 6.1 §8.3.1"),
}

# ---------------------------------------------------------------------------
# Post-FEC BER thresholds (Flit / MAC layer)
# PCIe 6.1 Section 8.4.2 — FEC-corrected residual error rate
# ---------------------------------------------------------------------------

POST_FEC_BER: dict[str, BerThresholds] = {
    "Gen1": BerThresholds(1e-12, 1e-9, 1e-6, "PCIe 6.1 §8.4"),
    "Gen2": BerThresholds(1e-12, 1e-9, 1e-6, "PCIe 6.1 §8.4"),
    "Gen3": BerThresholds(1e-12, 1e-9, 1e-6, "PCIe 6.1 §8.4"),
    "Gen4": BerThresholds(1e-12, 1e-9, 1e-6, "PCIe 6.1 §8.4"),
    "Gen5": BerThresholds(1e-12, 1e-9, 1e-6, "PCIe 6.1 §8.4"),
    # Gen6 Flit: MAC-level target after FEC correction
    "Gen6": BerThresholds(1e-12, 1e-9, 1e-6, "PCIe 6.1 §8.4.2"),
}


def get_ber_thresholds(speed_gen: str, *, is_flit_ber: bool = False) -> BerThresholds:
    """Look up BER thresholds for a given speed generation.

    Args:
        speed_gen: Link speed string, e.g. "Gen4", "Gen6".
        is_flit_ber: True for post-FEC (Flit/MAC) measurement,
                     False for pre-FEC (SerDes/UTP) measurement.

    Returns:
        ``BerThresholds`` for the requested speed/layer, falling back
        to Gen5 pre-FEC defaults if the speed string is unrecognised.
    """
    source = POST_FEC_BER if is_flit_ber else PRE_FEC_BER
    return source.get(speed_gen, PRE_FEC_BER["Gen5"])


# ---------------------------------------------------------------------------
# Eye margin thresholds
# PCIe 6.1 Section 8.4.4 — Lane margining requirements
# ---------------------------------------------------------------------------

NRZ_EYE = EyeThresholds(
    pass_ui=0.15,
    warn_ui=0.08,
    fail_ui=0.04,
    spec_ref="PCIe 6.1 §8.4.4",
)

PAM4_EYE = EyeThresholds(
    pass_ui=0.10,
    warn_ui=0.05,
    fail_ui=0.025,
    spec_ref="PCIe 6.1 §8.4.4 (PAM4 per sub-eye)",
)


def get_eye_thresholds(*, is_pam4: bool = False) -> EyeThresholds:
    """Return eye width/height thresholds for NRZ or PAM4 signaling."""
    return PAM4_EYE if is_pam4 else NRZ_EYE


# ---------------------------------------------------------------------------
# FEC correction rate thresholds (corrections per second)
# A high rate suggests the channel is operating near its error correction limit
# ---------------------------------------------------------------------------

FEC_RATE_WARN = 100.0
FEC_RATE_FAIL = 10000.0

# ---------------------------------------------------------------------------
# LTSSM recovery count warn threshold
# ---------------------------------------------------------------------------

LTSSM_RECOVERY_WARN = 5

# ---------------------------------------------------------------------------
# Bandwidth utilization warn threshold
# ---------------------------------------------------------------------------

UTILIZATION_WARN = 0.90

# ---------------------------------------------------------------------------
# SKP ordered set rate bounds (fraction of PTrace entries, PCIe 6.1 §4.2.7)
# PCIe 6.1 §4.2.7: SKP ordered sets inserted every 370 ±10 symbols.
# At ~32 symbols/flit, that's ~1 SKP per ~11.5 flits.
# In PTrace captures, SKP fraction depends on link utilization and capture mode.
# These bounds are empirical for typical Atlas3 traffic patterns.
# ---------------------------------------------------------------------------

SKP_RATE_MIN = 0.001
SKP_RATE_MAX = 0.05

# Cap for FEC margin ratio to avoid float("inf") in JSON serialization
FEC_MARGIN_RATIO_CAP = 9999.0


# ---------------------------------------------------------------------------
# Comparison report: metric direction defaults
# ---------------------------------------------------------------------------

NEUTRAL_METRIC_KEYS: frozenset[str] = frozenset(
    {
        "sample_count",
        "lane_count",
        "total_ports",
        "active_ports",
        "num_errors",
        "soak_duration_s",
        "capture_duration_s",
        "actual_duration_s",
        "poll_interval_ms",
        "duration_s",
        "max_entries",
    }
)
