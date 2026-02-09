"""Tests for SMART model serialization, build_smart_history, and poll_smart_loop."""

from __future__ import annotations

import struct
import threading
import time
from unittest.mock import MagicMock

from calypso.workloads.models import (
    BackendType,
    SmartSnapshot,
    SmartTimeSeries,
    WorkloadConfig,
    WorkloadProgress,
    WorkloadResult,
    WorkloadState,
)
from calypso.workloads.pynvme_backend import PynvmeBackend, _PynvmeWorkload

_KELVIN_OFFSET = 273


def _make_config(**overrides) -> WorkloadConfig:
    defaults = {
        "backend": BackendType.PYNVME,
        "target_bdf": "0000:01:00.0",
        "duration_seconds": 5,
    }
    defaults.update(overrides)
    return WorkloadConfig(**defaults)


def _make_snapshot(
    temp: float = 45.0, poh: int = 100, ps: int = 0, spare: int = 95
) -> SmartSnapshot:
    return SmartSnapshot(
        timestamp_ms=int(time.time() * 1000),
        composite_temp_celsius=temp,
        temp_sensors_celsius=[temp, temp - 5],
        power_on_hours=poh,
        power_state=ps,
        available_spare_pct=spare,
    )


def _build_smart_buffer(
    composite_k: int = 0, available_spare: int = 100, poh: int = 0
) -> bytearray:
    buf = bytearray(512)
    struct.pack_into("<H", buf, 1, composite_k)
    buf[3] = available_spare
    struct.pack_into("<Q", buf, 128, poh)
    return buf


# ---------------------------------------------------------------------------
# 1. Model serialization round-trip
# ---------------------------------------------------------------------------


class TestModelSerialization:
    def test_smart_snapshot_round_trip(self):
        snap = _make_snapshot(temp=72.5, poh=5000, ps=2, spare=88)
        data = snap.model_dump()

        assert data["composite_temp_celsius"] == 72.5
        assert data["power_on_hours"] == 5000
        assert data["power_state"] == 2
        assert data["available_spare_pct"] == 88
        assert data["temp_sensors_celsius"] == [72.5, 67.5]

        restored = SmartSnapshot.model_validate(data)
        assert restored == snap

    def test_smart_snapshot_json_round_trip(self):
        snap = _make_snapshot()
        json_str = snap.model_dump_json()
        restored = SmartSnapshot.model_validate_json(json_str)
        assert restored == snap

    def test_smart_time_series_round_trip(self):
        snaps = [_make_snapshot(temp=t) for t in [40.0, 50.0, 60.0]]
        ts = SmartTimeSeries(
            snapshots=snaps,
            peak_temp_celsius=60.0,
            avg_temp_celsius=50.0,
            latest=snaps[-1],
        )
        data = ts.model_dump()
        restored = SmartTimeSeries.model_validate(data)

        assert len(restored.snapshots) == 3
        assert restored.peak_temp_celsius == 60.0
        assert restored.avg_temp_celsius == 50.0
        assert restored.latest == snaps[-1]

    def test_workload_progress_with_smart(self):
        snap = _make_snapshot(temp=55.0)
        progress = WorkloadProgress(
            workload_id="wl_test123",
            elapsed_seconds=10.0,
            total_seconds=30.0,
            current_iops=50000.0,
            current_bandwidth_mbps=200.0,
            smart=snap,
        )
        data = progress.model_dump()

        assert data["smart"] is not None
        assert data["smart"]["composite_temp_celsius"] == 55.0

        restored = WorkloadProgress.model_validate(data)
        assert restored.smart is not None
        assert restored.smart.composite_temp_celsius == 55.0

    def test_workload_progress_without_smart(self):
        progress = WorkloadProgress(
            workload_id="wl_test456",
            elapsed_seconds=5.0,
            total_seconds=30.0,
        )
        data = progress.model_dump()
        assert data["smart"] is None

        restored = WorkloadProgress.model_validate(data)
        assert restored.smart is None

    def test_workload_result_with_smart_history(self):
        snaps = [_make_snapshot(temp=t) for t in [45.0, 55.0, 65.0]]
        history = SmartTimeSeries(
            snapshots=snaps,
            peak_temp_celsius=65.0,
            avg_temp_celsius=55.0,
            latest=snaps[-1],
        )
        result = WorkloadResult(
            workload_id="wl_result1",
            config=_make_config(),
            smart_history=history,
        )
        data = result.model_dump()

        assert data["smart_history"] is not None
        assert len(data["smart_history"]["snapshots"]) == 3
        assert data["smart_history"]["peak_temp_celsius"] == 65.0

        restored = WorkloadResult.model_validate(data)
        assert restored.smart_history is not None
        assert restored.smart_history.peak_temp_celsius == 65.0

    def test_workload_result_without_smart_history(self):
        result = WorkloadResult(
            workload_id="wl_result2",
            config=_make_config(),
        )
        data = result.model_dump()
        assert data["smart_history"] is None

    def test_workload_result_json_round_trip(self):
        snaps = [_make_snapshot(temp=50.0)]
        history = SmartTimeSeries(
            snapshots=snaps,
            peak_temp_celsius=50.0,
            avg_temp_celsius=50.0,
            latest=snaps[0],
        )
        result = WorkloadResult(
            workload_id="wl_json",
            config=_make_config(),
            smart_history=history,
        )
        json_str = result.model_dump_json()
        restored = WorkloadResult.model_validate_json(json_str)
        assert restored.smart_history is not None
        assert restored.smart_history.snapshots[0].composite_temp_celsius == 50.0


# ---------------------------------------------------------------------------
# 2. _build_smart_history logic
# ---------------------------------------------------------------------------


class TestBuildSmartHistory:
    def test_empty_snapshots_returns_none(self):
        wl = _PynvmeWorkload(workload_id="wl_empty", config=_make_config())
        result = PynvmeBackend._build_smart_history(wl)
        assert result is None

    def test_single_snapshot(self):
        wl = _PynvmeWorkload(workload_id="wl_single", config=_make_config())
        snap = _make_snapshot(temp=42.0)
        wl.smart_snapshots = [snap]

        result = PynvmeBackend._build_smart_history(wl)

        assert result is not None
        assert len(result.snapshots) == 1
        assert result.peak_temp_celsius == 42.0
        assert result.avg_temp_celsius == 42.0
        assert result.latest == snap

    def test_multiple_snapshots_computes_peak_and_avg(self):
        wl = _PynvmeWorkload(workload_id="wl_multi", config=_make_config())
        wl.smart_snapshots = [
            _make_snapshot(temp=40.0),
            _make_snapshot(temp=60.0),
            _make_snapshot(temp=80.0),
        ]

        result = PynvmeBackend._build_smart_history(wl)

        assert result is not None
        assert result.peak_temp_celsius == 80.0
        assert result.avg_temp_celsius == 60.0
        assert result.latest == wl.smart_snapshots[-1]

    def test_latest_is_last_snapshot(self):
        wl = _PynvmeWorkload(workload_id="wl_latest", config=_make_config())
        snap1 = _make_snapshot(temp=30.0, poh=100)
        snap2 = _make_snapshot(temp=50.0, poh=200)
        wl.smart_snapshots = [snap1, snap2]

        result = PynvmeBackend._build_smart_history(wl)

        assert result is not None
        assert result.latest.power_on_hours == 200

    def test_returns_copy_of_snapshots(self):
        wl = _PynvmeWorkload(workload_id="wl_copy", config=_make_config())
        snap = _make_snapshot(temp=50.0)
        wl.smart_snapshots = [snap]

        result = PynvmeBackend._build_smart_history(wl)

        assert result.snapshots is not wl.smart_snapshots
        assert result.snapshots == wl.smart_snapshots


# ---------------------------------------------------------------------------
# 3. _poll_smart_loop with mock controller
# ---------------------------------------------------------------------------


class TestPollSmartLoop:
    def test_accumulates_snapshots_until_deadline(self):
        wl = _PynvmeWorkload(
            workload_id="wl_poll",
            config=_make_config(duration_seconds=1),
            state=WorkloadState.RUNNING,
            start_time=time.monotonic(),
            smart_poll_interval=0.1,
        )
        buf = _build_smart_buffer(composite_k=_KELVIN_OFFSET + 50)
        ctrl = MagicMock()
        ctrl.getlogpage.return_value = bytes(buf)
        ctrl.getfeatures.return_value = 0

        backend = PynvmeBackend()
        backend._poll_smart_loop(wl, ctrl)

        assert len(wl.smart_snapshots) >= 2
        assert wl.latest_smart is not None
        assert wl.latest_smart.composite_temp_celsius == 50.0

    def test_stop_event_exits_early(self):
        wl = _PynvmeWorkload(
            workload_id="wl_stop",
            config=_make_config(duration_seconds=60),
            state=WorkloadState.RUNNING,
            start_time=time.monotonic(),
            smart_poll_interval=0.1,
        )
        buf = _build_smart_buffer(composite_k=_KELVIN_OFFSET + 30)
        ctrl = MagicMock()
        ctrl.getlogpage.return_value = bytes(buf)
        ctrl.getfeatures.return_value = 0

        # Set stop event after a short delay from another thread
        def trigger_stop():
            time.sleep(0.3)
            wl.stop_event.set()

        t = threading.Thread(target=trigger_stop, daemon=True)
        t.start()

        backend = PynvmeBackend()
        start = time.monotonic()
        backend._poll_smart_loop(wl, ctrl)
        elapsed = time.monotonic() - start

        t.join(timeout=2)

        # Should have exited well before 60s duration
        assert elapsed < 5.0
        assert len(wl.smart_snapshots) >= 1

    def test_failed_smart_read_does_not_accumulate(self):
        wl = _PynvmeWorkload(
            workload_id="wl_fail",
            config=_make_config(duration_seconds=1),
            state=WorkloadState.RUNNING,
            start_time=time.monotonic(),
            smart_poll_interval=0.1,
        )
        ctrl = MagicMock()
        ctrl.getlogpage.side_effect = RuntimeError("device error")

        backend = PynvmeBackend()
        backend._poll_smart_loop(wl, ctrl)

        assert len(wl.smart_snapshots) == 0
        assert wl.latest_smart is None

    def test_snapshots_consistent_under_concurrent_read(self):
        """Verify snapshots and latest_smart stay consistent when read under lock."""
        wl = _PynvmeWorkload(
            workload_id="wl_lock",
            config=_make_config(duration_seconds=1),
            state=WorkloadState.RUNNING,
            start_time=time.monotonic(),
            smart_poll_interval=0.1,
        )
        buf = _build_smart_buffer(composite_k=_KELVIN_OFFSET + 45)
        ctrl = MagicMock()
        ctrl.getlogpage.return_value = bytes(buf)
        ctrl.getfeatures.return_value = 0

        # Read snapshots from another thread while polling runs
        observed: list[tuple[int, bool]] = []

        def reader():
            for _ in range(20):
                with wl.lock:
                    n = len(wl.smart_snapshots)
                    has_latest = wl.latest_smart is not None
                    # If there are snapshots, latest must also be set
                    if n > 0:
                        observed.append((n, has_latest))
                time.sleep(0.05)

        reader_thread = threading.Thread(target=reader, daemon=True)
        reader_thread.start()

        backend = PynvmeBackend()
        backend._poll_smart_loop(wl, ctrl)
        reader_thread.join(timeout=3)

        # All observations should show consistent state
        for count, has_latest in observed:
            assert has_latest, f"latest_smart was None but {count} snapshots existed"
        assert len(wl.smart_snapshots) >= 1


# ---------------------------------------------------------------------------
# 4. Graceful degradation -- get_progress/get_result without SMART data
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    def test_get_progress_without_smart_data(self):
        backend = PynvmeBackend()
        wl = _PynvmeWorkload(
            workload_id="wl_nosmart",
            config=_make_config(),
            state=WorkloadState.RUNNING,
            start_time=time.monotonic(),
        )
        backend._workloads["wl_nosmart"] = wl

        progress = backend.get_progress("wl_nosmart")

        assert progress.smart is None
        assert progress.workload_id == "wl_nosmart"
        assert progress.state == WorkloadState.RUNNING

    def test_get_progress_with_smart_data(self):
        backend = PynvmeBackend()
        snap = _make_snapshot(temp=62.0)
        wl = _PynvmeWorkload(
            workload_id="wl_withsmart",
            config=_make_config(),
            state=WorkloadState.RUNNING,
            start_time=time.monotonic(),
            latest_smart=snap,
        )
        backend._workloads["wl_withsmart"] = wl

        progress = backend.get_progress("wl_withsmart")

        assert progress.smart is not None
        assert progress.smart.composite_temp_celsius == 62.0

    def test_get_result_without_smart_history(self):
        backend = PynvmeBackend()
        wl = _PynvmeWorkload(
            workload_id="wl_nohist",
            config=_make_config(),
            state=WorkloadState.COMPLETED,
            start_time=1000.0,
            end_time=1030.0,
        )
        backend._workloads["wl_nohist"] = wl

        result = backend.get_result("wl_nohist")

        assert result.smart_history is None
        assert result.workload_id == "wl_nohist"

    def test_get_result_with_smart_history(self):
        backend = PynvmeBackend()
        snaps = [_make_snapshot(temp=t) for t in [40.0, 60.0]]
        wl = _PynvmeWorkload(
            workload_id="wl_withhist",
            config=_make_config(),
            state=WorkloadState.COMPLETED,
            start_time=1000.0,
            end_time=1030.0,
            smart_snapshots=snaps,
            latest_smart=snaps[-1],
        )
        backend._workloads["wl_withhist"] = wl

        result = backend.get_result("wl_withhist")

        assert result.smart_history is not None
        assert result.smart_history.peak_temp_celsius == 60.0
        assert result.smart_history.avg_temp_celsius == 50.0
        assert len(result.smart_history.snapshots) == 2

    def test_progress_serializes_without_smart(self):
        """Verify progress without SMART data serializes cleanly for WebSocket."""
        progress = WorkloadProgress(
            workload_id="wl_ser",
            elapsed_seconds=5.0,
            total_seconds=30.0,
            current_iops=10000.0,
        )
        data = progress.model_dump()
        assert "smart" in data
        assert data["smart"] is None
        # Must not raise when JSON-serialized
        json_str = progress.model_dump_json()
        assert '"smart":null' in json_str or '"smart": null' in json_str

    def test_result_serializes_without_smart_history(self):
        """Verify result without SMART history serializes cleanly for API."""
        result = WorkloadResult(
            workload_id="wl_ser2",
            config=_make_config(),
        )
        data = result.model_dump()
        assert "smart_history" in data
        assert data["smart_history"] is None
        json_str = result.model_dump_json()
        assert "smart_history" in json_str
