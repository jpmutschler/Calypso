"""UI session state management."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class UIState:
    """Per-session UI state."""

    connected_device_id: str | None = None
    selected_port: int | None = None
    perf_monitoring: bool = False
    auto_refresh: bool = True
    refresh_interval_ms: int = 2000
    # MCU connection state
    mcu_serial_port: str | None = None
    mcu_connected: bool = False
