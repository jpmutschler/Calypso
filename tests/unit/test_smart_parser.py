"""Unit tests for calypso.workloads.smart_parser."""

from __future__ import annotations

import struct

from calypso.workloads.smart_parser import parse_smart_buffer

_KELVIN_OFFSET = 273


def _build_smart_buffer(
    composite_k: int = 0,
    available_spare: int = 100,
    poh: int = 0,
    sensors_k: list[int] | None = None,
) -> bytearray:
    """Build a synthetic 512-byte SMART log page buffer."""
    buf = bytearray(512)
    struct.pack_into("<H", buf, 1, composite_k)
    buf[3] = available_spare
    struct.pack_into("<Q", buf, 128, poh)
    if sensors_k:
        for i, val in enumerate(sensors_k):
            struct.pack_into("<H", buf, 200 + i * 2, val)
    return buf


class TestParseSmartBuffer:
    def test_basic_kelvin_conversion(self):
        buf = _build_smart_buffer(composite_k=_KELVIN_OFFSET + 45)
        snap = parse_smart_buffer(bytes(buf))
        assert snap.composite_temp_celsius == 45.0

    def test_zero_kelvin_yields_zero_celsius(self):
        buf = _build_smart_buffer(composite_k=0)
        snap = parse_smart_buffer(bytes(buf))
        assert snap.composite_temp_celsius == 0.0

    def test_below_kelvin_offset_clamped_to_zero(self):
        buf = _build_smart_buffer(composite_k=100)
        snap = parse_smart_buffer(bytes(buf))
        assert snap.composite_temp_celsius == 0.0

    def test_available_spare(self):
        buf = _build_smart_buffer(available_spare=42)
        snap = parse_smart_buffer(bytes(buf))
        assert snap.available_spare_pct == 42

    def test_available_spare_clamped_to_100(self):
        buf = _build_smart_buffer(available_spare=200)
        snap = parse_smart_buffer(bytes(buf))
        assert snap.available_spare_pct == 100

    def test_power_on_hours(self):
        buf = _build_smart_buffer(poh=12345)
        snap = parse_smart_buffer(bytes(buf))
        assert snap.power_on_hours == 12345

    def test_power_state_passed_through(self):
        buf = _build_smart_buffer()
        snap = parse_smart_buffer(bytes(buf), power_state=3)
        assert snap.power_state == 3

    def test_temperature_sensors(self):
        sensors = [_KELVIN_OFFSET + 40, _KELVIN_OFFSET + 50, _KELVIN_OFFSET + 60]
        buf = _build_smart_buffer(sensors_k=sensors)
        snap = parse_smart_buffer(bytes(buf))
        assert snap.temp_sensors_celsius == [40.0, 50.0, 60.0]

    def test_sensors_stop_at_zero(self):
        sensors = [_KELVIN_OFFSET + 40, _KELVIN_OFFSET + 50, 0, _KELVIN_OFFSET + 70]
        buf = _build_smart_buffer(sensors_k=sensors)
        snap = parse_smart_buffer(bytes(buf))
        assert len(snap.temp_sensors_celsius) == 2
        assert snap.temp_sensors_celsius == [40.0, 50.0]

    def test_no_sensors(self):
        buf = _build_smart_buffer()
        snap = parse_smart_buffer(bytes(buf))
        assert snap.temp_sensors_celsius == []

    def test_timestamp_is_populated(self):
        buf = _build_smart_buffer()
        snap = parse_smart_buffer(bytes(buf))
        assert snap.timestamp_ms > 0

    def test_short_buffer_padded(self):
        short_buf = b"\x00" * 10
        snap = parse_smart_buffer(short_buf)
        assert snap.composite_temp_celsius == 0.0
        assert snap.available_spare_pct == 0

    def test_all_zeros_buffer(self):
        buf = bytes(512)
        snap = parse_smart_buffer(buf)
        assert snap.composite_temp_celsius == 0.0
        assert snap.power_on_hours == 0
        assert snap.available_spare_pct == 0
        assert snap.temp_sensors_celsius == []

    def test_sensor_below_kelvin_offset_clamped(self):
        sensors = [100]  # below 273K offset
        buf = _build_smart_buffer(sensors_k=sensors)
        snap = parse_smart_buffer(bytes(buf))
        assert snap.temp_sensors_celsius == [0.0]

    def test_large_poh_value(self):
        buf = _build_smart_buffer(poh=2**48)
        snap = parse_smart_buffer(bytes(buf))
        assert snap.power_on_hours == 2**48

    def test_high_temperature(self):
        buf = _build_smart_buffer(composite_k=_KELVIN_OFFSET + 105)
        snap = parse_smart_buffer(bytes(buf))
        assert snap.composite_temp_celsius == 105.0
