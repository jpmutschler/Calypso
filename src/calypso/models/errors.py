"""Combined error view models aggregating AER, MCU, and LTSSM error sources."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PortErrorSummary(BaseModel):
    """Per-port error summary combining all sources."""

    port_number: int
    # MCU counters (None if MCU not connected)
    mcu_bad_tlp: int | None = None
    mcu_bad_dllp: int | None = None
    mcu_port_rx: int | None = None
    mcu_rec_diag: int | None = None
    mcu_link_down: int | None = None
    mcu_flit_error: int | None = None
    mcu_total: int | None = None
    # LTSSM counters (None if port not probed)
    ltssm_recovery_count: int | None = None
    ltssm_link_down_count: int | None = None
    ltssm_rx_eval_count: int | None = None


class ErrorOverview(BaseModel):
    """Combined error view across all sources."""

    # AER (device-level)
    aer_available: bool = False
    aer_uncorrectable_raw: int = 0
    aer_correctable_raw: int = 0
    aer_uncorrectable_active: list[str] = Field(default_factory=list)
    aer_correctable_active: list[str] = Field(default_factory=list)
    # Per-port breakdown
    port_errors: list[PortErrorSummary] = Field(default_factory=list)
    # MCU connected?
    mcu_connected: bool = False
    # Totals
    total_aer_uncorrectable: int = 0
    total_aer_correctable: int = 0
    total_mcu_errors: int = 0
    total_ltssm_recoveries: int = 0
