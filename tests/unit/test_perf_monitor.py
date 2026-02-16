"""Unit tests for calypso.core.perf_monitor — multi-port init, snapshots, edge cases."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT, PLX_PERF_PROP
from calypso.core.perf_monitor import PerfMonitor
from calypso.exceptions import PlxStatusError, UnsupportedError
from calypso.models.performance import PerfSnapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_device_key(api_mode: int = 0, plx_port: int = 0) -> PLX_DEVICE_KEY:
    """Build a PLX_DEVICE_KEY with PCI mode (0) by default."""
    key = PLX_DEVICE_KEY()
    key.ApiMode = api_mode
    key.PlxPort = plx_port
    return key


def _make_device_obj() -> PLX_DEVICE_OBJECT:
    return PLX_DEVICE_OBJECT()


def _make_found_key(plx_port: int = 0) -> PLX_DEVICE_KEY:
    """Build a device key as returned by find_devices."""
    key = PLX_DEVICE_KEY()
    key.PlxPort = plx_port
    return key


def _init_props_sequence(*fns):
    """Build a single side_effect that calls fns[0] on first call, fns[1] on second, etc.

    Each fn receives (device, prop) and should mutate prop in-place.
    This is needed because mock's list side_effect returns values, but
    init_properties needs to modify the prop argument in-place.
    """
    it = iter(fns)

    def _side_effect(device, prop):
        fn = next(it)
        if isinstance(fn, Exception):
            raise fn
        fn(device, prop)

    return _side_effect


def _set_valid(port_number: int, station: int = 0, station_port: int = 0):
    """Return a callable that marks a PLX_PERF_PROP as valid."""
    def _init(device, prop):
        prop.IsValidTag = 1
        prop.PortNumber = port_number
        prop.Station = station
        prop.StationPort = station_port
        prop.LinkWidth = 8
        prop.LinkSpeed = 4
    return _init


def _set_invalid():
    """Return a callable that leaves IsValidTag at 0."""
    def _init(device, prop):
        prop.IsValidTag = 0
    return _init


def _make_mock_stats(**overrides):
    """Build a mock PLX_PERF_STATS with sensible defaults."""
    defaults = {
        "IngressTotalBytes": 1000,
        "IngressTotalByteRate": 100.0,
        "IngressPayloadReadBytes": 500,
        "IngressPayloadWriteBytes": 300,
        "IngressPayloadTotalBytes": 800,
        "IngressPayloadAvgPerTlp": 64.0,
        "IngressPayloadByteRate": 80.0,
        "IngressLinkUtilization": 0.05,
        "EgressTotalBytes": 900,
        "EgressTotalByteRate": 90.0,
        "EgressPayloadReadBytes": 400,
        "EgressPayloadWriteBytes": 350,
        "EgressPayloadTotalBytes": 750,
        "EgressPayloadAvgPerTlp": 60.0,
        "EgressPayloadByteRate": 75.0,
        "EgressLinkUtilization": 0.04,
    }
    defaults.update(overrides)
    stats = MagicMock()
    for k, v in defaults.items():
        setattr(stats, k, v)
    return stats


# ---------------------------------------------------------------------------
# Construction and Properties
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_initial_state(self):
        dev = _make_device_obj()
        key = _make_device_key()
        monitor = PerfMonitor(dev, key)

        assert monitor.is_running is False
        assert monitor.num_ports == 0

    def test_stores_device_and_key(self):
        dev = _make_device_obj()
        key = _make_device_key()
        monitor = PerfMonitor(dev, key)

        assert monitor._device is dev
        assert monitor._key is key


# ---------------------------------------------------------------------------
# Initialize — multi-port enumeration
# ---------------------------------------------------------------------------

class TestInitializeMultiPort:
    @patch("calypso.core.perf_monitor.sdk_device")
    @patch("calypso.core.perf_monitor.sdk_perf")
    def test_happy_path_three_ports(self, mock_sdk_perf, mock_sdk_device):
        """Three ports discovered and all init successfully."""
        keys = [_make_found_key(p) for p in (0, 1, 2)]
        mock_sdk_device.find_devices.return_value = keys

        dev_handles = [_make_device_obj() for _ in range(3)]
        mock_sdk_device.open_device.side_effect = dev_handles

        mock_sdk_perf.init_properties.side_effect = _init_props_sequence(
            _set_valid(0, station=0, station_port=0),
            _set_valid(1, station=0, station_port=1),
            _set_valid(2, station=1, station_port=0),
        )

        dev = _make_device_obj()
        key = _make_device_key()
        monitor = PerfMonitor(dev, key)
        count = monitor.initialize()

        assert count == 3
        assert monitor.num_ports == 3
        assert len(monitor._perf_props) == 3

        # Each device was opened and closed
        assert mock_sdk_device.open_device.call_count == 3
        assert mock_sdk_device.close_device.call_count == 3

    @patch("calypso.core.perf_monitor.sdk_device")
    @patch("calypso.core.perf_monitor.sdk_perf")
    def test_partial_failure_some_ports_fail_to_open(self, mock_sdk_perf, mock_sdk_device):
        """Two ports found, first fails to open, second succeeds."""
        keys = [_make_found_key(0), _make_found_key(1)]
        mock_sdk_device.find_devices.return_value = keys

        mock_sdk_device.open_device.side_effect = [
            PlxStatusError("DeviceOpen: PLX_STATUS_IN_USE"),
            _make_device_obj(),
        ]

        mock_sdk_perf.init_properties.side_effect = _init_props_sequence(
            _set_valid(1),
        )

        monitor = PerfMonitor(_make_device_obj(), _make_device_key())
        count = monitor.initialize()

        assert count == 1
        assert monitor.num_ports == 1
        # First port failed to open so close_device called only once
        assert mock_sdk_device.close_device.call_count == 1

    @patch("calypso.core.perf_monitor.sdk_device")
    @patch("calypso.core.perf_monitor.sdk_perf")
    def test_partial_failure_init_properties_raises(self, mock_sdk_perf, mock_sdk_device):
        """Port opens but init_properties raises — device still closed."""
        keys = [_make_found_key(0)]
        mock_sdk_device.find_devices.return_value = keys
        mock_sdk_device.open_device.return_value = _make_device_obj()

        mock_sdk_perf.init_properties.side_effect = UnsupportedError("UNSUPPORTED")

        monitor = PerfMonitor(_make_device_obj(), _make_device_key())
        # Should not raise — falls back to single port
        monitor.initialize()

        # close_device IS called (in the finally block) despite init_properties raising
        assert mock_sdk_device.close_device.call_count == 1

    @patch("calypso.core.perf_monitor.sdk_device")
    @patch("calypso.core.perf_monitor.sdk_perf")
    def test_invalid_tag_ports_excluded(self, mock_sdk_perf, mock_sdk_device):
        """Ports where IsValidTag remains 0 are excluded from results."""
        keys = [_make_found_key(0), _make_found_key(1)]
        mock_sdk_device.find_devices.return_value = keys
        mock_sdk_device.open_device.return_value = _make_device_obj()

        mock_sdk_perf.init_properties.side_effect = _init_props_sequence(
            _set_valid(0),
            _set_invalid(),
        )

        monitor = PerfMonitor(_make_device_obj(), _make_device_key())
        count = monitor.initialize()

        assert count == 1

    @patch("calypso.core.perf_monitor.sdk_device")
    @patch("calypso.core.perf_monitor.sdk_perf")
    def test_no_devices_found_falls_back(self, mock_sdk_perf, mock_sdk_device):
        """find_devices returns empty list — falls back to single-port."""
        mock_sdk_device.find_devices.return_value = []

        # Single-port fallback succeeds
        mock_sdk_perf.init_properties.side_effect = _init_props_sequence(
            _set_valid(0),
        )

        monitor = PerfMonitor(_make_device_obj(), _make_device_key())
        count = monitor.initialize()

        assert count == 1
        # The fallback uses the monitor's own device, not open_device
        assert mock_sdk_device.open_device.call_count == 0

    @patch("calypso.core.perf_monitor.sdk_device")
    @patch("calypso.core.perf_monitor.sdk_perf")
    def test_uses_correct_api_mode_for_sdb(self, mock_sdk_perf, mock_sdk_device):
        """Non-PCI api_mode passes mode_prop to find_devices."""
        mock_sdk_device.find_devices.return_value = []
        mock_sdk_perf.init_properties.side_effect = _init_props_sequence(_set_invalid())

        key = _make_device_key(api_mode=3)  # SDB
        monitor = PerfMonitor(_make_device_obj(), key)
        monitor.initialize()

        call_args = mock_sdk_device.find_devices.call_args
        assert call_args.kwargs["api_mode"].value == 3
        assert call_args.kwargs["mode_prop"] is not None


# ---------------------------------------------------------------------------
# Single-port fallback
# ---------------------------------------------------------------------------

class TestSinglePortFallback:
    @patch("calypso.core.perf_monitor.sdk_device")
    @patch("calypso.core.perf_monitor.sdk_perf")
    def test_fallback_succeeds(self, mock_sdk_perf, mock_sdk_device):
        """All multi-port inits fail, single-port fallback returns 1 port."""
        keys = [_make_found_key(0)]
        mock_sdk_device.find_devices.return_value = keys
        mock_sdk_device.open_device.side_effect = PlxStatusError("FAILED")

        # Fallback init_properties call succeeds
        mock_sdk_perf.init_properties.side_effect = _init_props_sequence(
            _set_valid(0),
        )

        monitor = PerfMonitor(_make_device_obj(), _make_device_key())
        count = monitor.initialize()

        assert count == 1

    @patch("calypso.core.perf_monitor.sdk_device")
    @patch("calypso.core.perf_monitor.sdk_perf")
    def test_fallback_also_fails(self, mock_sdk_perf, mock_sdk_device):
        """Both multi-port and single-port fail — returns 0 ports."""
        mock_sdk_device.find_devices.return_value = []
        mock_sdk_perf.init_properties.side_effect = UnsupportedError("UNSUPPORTED")

        monitor = PerfMonitor(_make_device_obj(), _make_device_key())
        count = monitor.initialize()

        assert count == 0
        assert monitor.num_ports == 0
        assert monitor._perf_props == []


# ---------------------------------------------------------------------------
# Start / Stop
# ---------------------------------------------------------------------------

class TestStartStop:
    @patch("calypso.core.perf_monitor.sdk_device")
    @patch("calypso.core.perf_monitor.sdk_perf")
    def test_start_calls_initialize_if_no_props(self, mock_sdk_perf, mock_sdk_device):
        """start() auto-initializes if _perf_props is empty."""
        mock_sdk_device.find_devices.return_value = [_make_found_key(0)]
        mock_sdk_device.open_device.return_value = _make_device_obj()
        mock_sdk_perf.init_properties.side_effect = _init_props_sequence(_set_valid(0))

        monitor = PerfMonitor(_make_device_obj(), _make_device_key())
        assert monitor._perf_props == []

        monitor.start()

        assert monitor.is_running is True
        assert monitor.num_ports == 1
        mock_sdk_perf.start_monitoring.assert_called_once()

    @patch("calypso.core.perf_monitor.sdk_perf")
    def test_start_idempotent(self, mock_sdk_perf):
        """Calling start() twice does not call start_monitoring twice."""
        monitor = PerfMonitor(_make_device_obj(), _make_device_key())
        # Pre-populate props to skip initialize
        prop = PLX_PERF_PROP()
        prop.IsValidTag = 1
        monitor._perf_props = [prop]

        monitor.start()
        monitor.start()

        assert mock_sdk_perf.start_monitoring.call_count == 1

    @patch("calypso.core.perf_monitor.sdk_perf")
    def test_stop_calls_sdk(self, mock_sdk_perf):
        monitor = PerfMonitor(_make_device_obj(), _make_device_key())
        prop = PLX_PERF_PROP()
        prop.IsValidTag = 1
        monitor._perf_props = [prop]

        monitor.start()
        assert monitor.is_running is True

        monitor.stop()
        assert monitor.is_running is False
        mock_sdk_perf.stop_monitoring.assert_called_once()

    @patch("calypso.core.perf_monitor.sdk_perf")
    def test_stop_when_not_running_is_noop(self, mock_sdk_perf):
        monitor = PerfMonitor(_make_device_obj(), _make_device_key())
        monitor.stop()
        mock_sdk_perf.stop_monitoring.assert_not_called()


# ---------------------------------------------------------------------------
# Read Snapshot
# ---------------------------------------------------------------------------

class TestReadSnapshot:
    @patch("calypso.core.perf_monitor.sdk_perf")
    def test_empty_props_returns_empty_snapshot(self, mock_sdk_perf):
        """No ports initialized — returns snapshot with no port_stats."""
        monitor = PerfMonitor(_make_device_obj(), _make_device_key())
        snapshot = monitor.read_snapshot()

        assert isinstance(snapshot, PerfSnapshot)
        assert snapshot.port_stats == []
        assert snapshot.timestamp_ms > 0
        mock_sdk_perf.get_counters.assert_not_called()

    @patch("calypso.core.perf_monitor.sdk_perf")
    def test_snapshot_with_ports(self, mock_sdk_perf):
        """Snapshot with two ports returns correct stats."""
        monitor = PerfMonitor(_make_device_obj(), _make_device_key())

        prop0 = PLX_PERF_PROP()
        prop0.IsValidTag = 1
        prop0.PortNumber = 0
        prop1 = PLX_PERF_PROP()
        prop1.IsValidTag = 1
        prop1.PortNumber = 4
        monitor._perf_props = [prop0, prop1]
        monitor._last_read_time_ms = 1000

        stats0 = _make_mock_stats(IngressPayloadByteRate=1000.0)
        stats1 = _make_mock_stats(IngressPayloadByteRate=2000.0)
        mock_sdk_perf.calc_statistics.side_effect = [stats0, stats1]

        snapshot = monitor.read_snapshot()

        assert len(snapshot.port_stats) == 2
        assert snapshot.port_stats[0].port_number == 0
        assert snapshot.port_stats[0].ingress_payload_byte_rate == 1000.0
        assert snapshot.port_stats[1].port_number == 4
        assert snapshot.port_stats[1].ingress_payload_byte_rate == 2000.0

        mock_sdk_perf.get_counters.assert_called_once()

    @patch("calypso.core.perf_monitor.sdk_perf")
    def test_calc_statistics_failure_returns_zeroed_stats(self, mock_sdk_perf):
        """If calc_statistics raises for one port, that port gets zeroed stats."""
        monitor = PerfMonitor(_make_device_obj(), _make_device_key())

        prop0 = PLX_PERF_PROP()
        prop0.IsValidTag = 1
        prop0.PortNumber = 3
        prop1 = PLX_PERF_PROP()
        prop1.IsValidTag = 1
        prop1.PortNumber = 7
        monitor._perf_props = [prop0, prop1]
        monitor._last_read_time_ms = 1000

        # First port raises (e.g. INVALID_DATA for link-down port)
        # Second port succeeds
        mock_sdk_perf.calc_statistics.side_effect = [
            PlxStatusError("INVALID_DATA"),
            _make_mock_stats(IngressPayloadByteRate=500.0),
        ]

        snapshot = monitor.read_snapshot()

        assert len(snapshot.port_stats) == 2
        # First port: zeroed defaults
        assert snapshot.port_stats[0].port_number == 3
        assert snapshot.port_stats[0].ingress_payload_byte_rate == 0.0
        assert snapshot.port_stats[0].egress_link_utilization == 0.0
        # Second port: real values
        assert snapshot.port_stats[1].port_number == 7
        assert snapshot.port_stats[1].ingress_payload_byte_rate == 500.0

    @patch("calypso.core.perf_monitor.sdk_perf")
    def test_all_calc_statistics_fail(self, mock_sdk_perf):
        """All ports fail calc_statistics — still returns snapshot with zeroed entries."""
        monitor = PerfMonitor(_make_device_obj(), _make_device_key())

        prop = PLX_PERF_PROP()
        prop.IsValidTag = 1
        prop.PortNumber = 5
        monitor._perf_props = [prop]
        monitor._last_read_time_ms = 1000

        mock_sdk_perf.calc_statistics.side_effect = PlxStatusError("INVALID_DATA")

        snapshot = monitor.read_snapshot()

        assert len(snapshot.port_stats) == 1
        assert snapshot.port_stats[0].port_number == 5
        assert snapshot.port_stats[0].ingress_total_bytes == 0

    @patch("calypso.core.perf_monitor.sdk_perf")
    def test_elapsed_ms_calculated(self, mock_sdk_perf):
        """elapsed_ms reflects time since last read."""
        monitor = PerfMonitor(_make_device_obj(), _make_device_key())

        # First call with no last_read_time defaults to 1000ms
        snapshot1 = monitor.read_snapshot()
        assert snapshot1.elapsed_ms == 1000

        # Second call should compute from previous timestamp
        snapshot2 = monitor.read_snapshot()
        assert snapshot2.elapsed_ms >= 0

    @patch("calypso.core.perf_monitor.sdk_perf")
    def test_perf_props_updated_after_snapshot(self, mock_sdk_perf):
        """_perf_props is updated from the array after get_counters fills in new data."""
        monitor = PerfMonitor(_make_device_obj(), _make_device_key())

        prop = PLX_PERF_PROP()
        prop.IsValidTag = 1
        prop.PortNumber = 0
        monitor._perf_props = [prop]
        monitor._last_read_time_ms = 1000

        mock_sdk_perf.calc_statistics.return_value = _make_mock_stats()

        original_props = monitor._perf_props
        monitor.read_snapshot()

        # _perf_props was replaced with a new list from the ctypes array
        assert monitor._perf_props is not original_props
        assert len(monitor._perf_props) == 1


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

class TestReset:
    @patch("calypso.core.perf_monitor.sdk_perf")
    def test_reset_calls_sdk(self, mock_sdk_perf):
        monitor = PerfMonitor(_make_device_obj(), _make_device_key())

        prop = PLX_PERF_PROP()
        prop.IsValidTag = 1
        monitor._perf_props = [prop]

        monitor.reset()

        mock_sdk_perf.reset_counters.assert_called_once()

    @patch("calypso.core.perf_monitor.sdk_perf")
    def test_reset_noop_when_no_props(self, mock_sdk_perf):
        monitor = PerfMonitor(_make_device_obj(), _make_device_key())
        monitor.reset()
        mock_sdk_perf.reset_counters.assert_not_called()

    @patch("calypso.core.perf_monitor.sdk_perf")
    def test_reset_updates_last_read_time(self, mock_sdk_perf):
        monitor = PerfMonitor(_make_device_obj(), _make_device_key())
        prop = PLX_PERF_PROP()
        prop.IsValidTag = 1
        monitor._perf_props = [prop]
        monitor._last_read_time_ms = 0

        monitor.reset()

        assert monitor._last_read_time_ms > 0
