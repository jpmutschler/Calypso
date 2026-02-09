"""pynvme library backend for NVMe workload generation (Linux only)."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

from calypso.utils.logging import get_logger
from calypso.workloads.base import WorkloadBackend
from calypso.workloads.exceptions import (
    WorkloadNotFoundError,
    WorkloadTargetError,
)
from calypso.workloads.models import (
    SmartSnapshot,
    SmartTimeSeries,
    WorkloadConfig,
    WorkloadIOStats,
    WorkloadProgress,
    WorkloadResult,
    WorkloadState,
)
from calypso.workloads.smart_parser import read_smart_from_controller

logger = get_logger(__name__)


@dataclass
class _PynvmeWorkload:
    """Tracks a single pynvme workload run."""

    workload_id: str
    config: WorkloadConfig
    state: WorkloadState = WorkloadState.PENDING
    thread: threading.Thread | None = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    start_time: float = 0.0
    end_time: float = 0.0
    stats: WorkloadIOStats | None = None
    error: str | None = None
    current_iops: float = 0.0
    current_bw_mbps: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)
    smart_snapshots: list[SmartSnapshot] = field(default_factory=list)
    latest_smart: SmartSnapshot | None = None
    smart_poll_interval: float = 3.0


class PynvmeBackend(WorkloadBackend):
    """Workload backend using the pynvme Python library."""

    def __init__(self) -> None:
        self._workloads: dict[str, _PynvmeWorkload] = {}

    @property
    def backend_name(self) -> str:
        return "pynvme"

    def validate_target(self, bdf: str) -> bool:
        """Verify the NVMe device at *bdf* is accessible via pynvme."""
        try:
            import pynvme

            pcie = pynvme.Pcie(bdf)
            pcie.close()
            return True
        except Exception:
            return False

    def start(self, config: WorkloadConfig) -> str:
        workload_id = f"wl_{uuid.uuid4().hex[:12]}"
        logger.info("pynvme_start", workload_id=workload_id, bdf=config.target_bdf)

        wl = _PynvmeWorkload(
            workload_id=workload_id,
            config=config,
            state=WorkloadState.RUNNING,
            start_time=time.monotonic(),
        )

        worker_thread = threading.Thread(
            target=self._run_workload,
            args=(wl,),
            daemon=True,
        )
        wl.thread = worker_thread
        self._workloads[workload_id] = wl
        worker_thread.start()
        return workload_id

    def stop(self, workload_id: str) -> None:
        wl = self._get_workload(workload_id)
        with wl.lock:
            if wl.state != WorkloadState.RUNNING:
                return
        logger.info("pynvme_stop", workload_id=workload_id)
        wl.stop_event.set()
        # pynvme IOWorker cannot be cancelled mid-run, so we wait for
        # the current duration to expire naturally
        if wl.thread is not None:
            wl.thread.join(timeout=wl.config.duration_seconds + 10)
        with wl.lock:
            if wl.state == WorkloadState.RUNNING:
                wl.state = WorkloadState.STOPPED
                wl.end_time = time.monotonic()

    def get_result(self, workload_id: str) -> WorkloadResult:
        wl = self._get_workload(workload_id)
        with wl.lock:
            duration_ms = 0.0
            if wl.end_time > 0:
                duration_ms = (wl.end_time - wl.start_time) * 1000
            return WorkloadResult(
                workload_id=workload_id,
                config=wl.config,
                stats=wl.stats,
                duration_ms=duration_ms,
                error=wl.error,
                state=wl.state,
                smart_history=self._build_smart_history(wl),
            )

    def get_progress(self, workload_id: str) -> WorkloadProgress:
        wl = self._get_workload(workload_id)
        with wl.lock:
            elapsed = time.monotonic() - wl.start_time if wl.start_time > 0 else 0.0
            return WorkloadProgress(
                workload_id=workload_id,
                elapsed_seconds=elapsed,
                total_seconds=float(wl.config.duration_seconds),
                current_iops=wl.current_iops,
                current_bandwidth_mbps=wl.current_bw_mbps,
                state=wl.state,
                smart=wl.latest_smart,
            )

    def is_running(self, workload_id: str) -> bool:
        wl = self._workloads.get(workload_id)
        if wl is None:
            return False
        with wl.lock:
            return wl.state == WorkloadState.RUNNING

    def shutdown(self) -> None:
        """Stop all running workloads."""
        for wl_id in list(self._workloads):
            if self.is_running(wl_id):
                try:
                    self.stop(wl_id)
                except Exception:
                    pass

    # --- internal ---

    def _get_workload(self, workload_id: str) -> _PynvmeWorkload:
        wl = self._workloads.get(workload_id)
        if wl is None:
            raise WorkloadNotFoundError(f"Workload {workload_id} not found")
        return wl

    def _run_workload(self, wl: _PynvmeWorkload) -> None:
        """Background thread: open device, run IOWorker(s), collect results."""
        pcie = None
        try:
            import pynvme

            pcie = pynvme.Pcie(wl.config.target_bdf)
            ctrl = pynvme.Controller(pcie)
            ns = pynvme.Namespace(ctrl)
        except Exception as exc:
            with wl.lock:
                wl.error = f"Failed to open device: {exc}"
                wl.state = WorkloadState.FAILED
                wl.end_time = time.monotonic()
            if pcie is not None:
                try:
                    pcie.close()
                except Exception:
                    pass
            return

        try:
            results = self._run_ioworkers(wl, ns, ctrl)
            with wl.lock:
                if wl.state == WorkloadState.RUNNING:
                    wl.stats = self._aggregate_results(results, wl.config)
                    wl.state = WorkloadState.COMPLETED
                    wl.end_time = time.monotonic()
        except Exception as exc:
            with wl.lock:
                wl.error = f"IOWorker error: {exc}"
                wl.state = WorkloadState.FAILED
                wl.end_time = time.monotonic()
        finally:
            try:
                pcie.close()
            except Exception:
                pass

    def _run_ioworkers(
        self,
        wl: _PynvmeWorkload,
        ns: object,
        ctrl: object,
    ) -> list[dict]:
        """Launch IOWorkers, poll SMART while they run, collect result dicts."""
        config = wl.config
        num_workers = config.num_workers
        io_size_lba = max(1, config.io_size_bytes // 512)

        # Calculate LBA region per worker to avoid conflicts
        ns_size = getattr(ns, "id_data", {}).get(7, 0) if hasattr(ns, "id_data") else 0
        region_start = config.region_start or 0
        region_end = config.region_end or ns_size

        region_size = region_end - region_start
        worker_region = region_size // num_workers if num_workers > 0 else region_size

        workers = []
        for i in range(num_workers):
            if wl.stop_event.is_set():
                break

            w_start = region_start + i * worker_region
            w_end = w_start + worker_region if i < num_workers - 1 else region_end

            worker_kwargs = {
                "io_size": io_size_lba,
                "qdepth": config.queue_depth,
                "time": config.duration_seconds,
                "read_percentage": config.read_percentage,
            }

            if config.lba_random:
                worker_kwargs["lba_random"] = True

            if w_start > 0 or w_end < region_end:
                worker_kwargs["region_start"] = w_start
                worker_kwargs["region_end"] = w_end

            ioworker = ns.ioworker(**worker_kwargs)
            workers.append(ioworker)

        # Poll SMART while IOWorkers run in background C threads
        self._poll_smart_loop(wl, ctrl)

        # IOWorkers should have finished by now, collect results
        results = []
        for ioworker in workers:
            result = ioworker.close()
            results.append(result if isinstance(result, dict) else {})

        return results

    def _poll_smart_loop(self, wl: _PynvmeWorkload, ctrl: object) -> None:
        """Poll SMART data at regular intervals until duration expires or stopped."""
        deadline = wl.start_time + wl.config.duration_seconds
        while not wl.stop_event.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            snap = read_smart_from_controller(ctrl)
            if snap is not None:
                with wl.lock:
                    wl.smart_snapshots.append(snap)
                    wl.latest_smart = snap

            wait_time = min(wl.smart_poll_interval, remaining)
            if wait_time > 0:
                wl.stop_event.wait(timeout=wait_time)

    @staticmethod
    def _build_smart_history(wl: _PynvmeWorkload) -> SmartTimeSeries | None:
        """Build SmartTimeSeries from accumulated snapshots. Caller holds wl.lock."""
        if not wl.smart_snapshots:
            return None
        temps = [s.composite_temp_celsius for s in wl.smart_snapshots]
        return SmartTimeSeries(
            snapshots=list(wl.smart_snapshots),
            peak_temp_celsius=max(temps),
            avg_temp_celsius=sum(temps) / len(temps),
            latest=wl.smart_snapshots[-1],
        )

    @staticmethod
    def _aggregate_results(
        results: list[dict],
        config: WorkloadConfig,
    ) -> WorkloadIOStats:
        """Combine results from multiple IOWorkers into a single stats model."""
        total_read = 0
        total_write = 0
        total_ms = 0.0
        latency_avg_sum = 0.0
        latency_max_val = 0.0
        cpu_sum = 0.0

        for r in results:
            total_read += r.get("io_count_read", 0)
            total_write += r.get("io_count_write", 0)
            ms = r.get("mseconds", 0)
            total_ms = max(total_ms, float(ms))
            latency_avg_sum += r.get("latency_average_us", 0)
            latency_max_val = max(latency_max_val, r.get("latency_max_us", 0))
            cpu_sum += r.get("cpu_usage", 0)

        duration_s = total_ms / 1000.0 if total_ms > 0 else float(config.duration_seconds)
        n = len(results) if results else 1

        iops_read = total_read / duration_s if duration_s > 0 else 0.0
        iops_write = total_write / duration_s if duration_s > 0 else 0.0
        io_size_bytes = config.io_size_bytes

        return WorkloadIOStats(
            io_count_read=total_read,
            io_count_write=total_write,
            iops_read=iops_read,
            iops_write=iops_write,
            iops_total=iops_read + iops_write,
            bandwidth_read_mbps=(iops_read * io_size_bytes) / (1024 * 1024),
            bandwidth_write_mbps=(iops_write * io_size_bytes) / (1024 * 1024),
            bandwidth_total_mbps=((iops_read + iops_write) * io_size_bytes / (1024 * 1024)),
            latency_avg_us=latency_avg_sum / n if n > 0 else 0.0,
            latency_max_us=latency_max_val,
            cpu_usage_percent=cpu_sum / n if n > 0 else 0.0,
        )
