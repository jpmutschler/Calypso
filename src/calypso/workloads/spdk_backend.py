"""SPDK spdk_nvme_perf subprocess backend."""

from __future__ import annotations

import shutil
import subprocess
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
    WorkloadConfig,
    WorkloadIOStats,
    WorkloadProgress,
    WorkloadResult,
    WorkloadState,
    WorkloadType,
)
from calypso.workloads.output_parser import parse_spdk_output

logger = get_logger(__name__)

_KILL_TIMEOUT_SECONDS = 5


@dataclass
class _SpdkWorkload:
    """Tracks a single spdk_nvme_perf subprocess."""
    workload_id: str
    config: WorkloadConfig
    process: subprocess.Popen | None = None
    thread: threading.Thread | None = None
    state: WorkloadState = WorkloadState.PENDING
    start_time: float = 0.0
    end_time: float = 0.0
    stdout_text: str = ""
    stderr_text: str = ""
    stats: WorkloadIOStats | None = None
    error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class SpdkBackend(WorkloadBackend):
    """Workload backend using the SPDK spdk_nvme_perf CLI tool."""

    def __init__(self) -> None:
        self._workloads: dict[str, _SpdkWorkload] = {}

    @property
    def backend_name(self) -> str:
        return "spdk"

    def validate_target(self, bdf: str) -> bool:
        """Check that spdk_nvme_perf is available (device probing deferred to SPDK)."""
        return shutil.which("spdk_nvme_perf") is not None

    def start(self, config: WorkloadConfig) -> str:
        workload_id = f"wl_{uuid.uuid4().hex[:12]}"
        cmd = self._build_command(config)
        logger.info("spdk_start", workload_id=workload_id, cmd=" ".join(cmd))

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError as exc:
            raise WorkloadTargetError(
                f"spdk_nvme_perf not found: {exc}"
            ) from exc
        except OSError as exc:
            raise WorkloadTargetError(
                f"Failed to launch spdk_nvme_perf: {exc}"
            ) from exc

        wl = _SpdkWorkload(
            workload_id=workload_id,
            config=config,
            process=proc,
            state=WorkloadState.RUNNING,
            start_time=time.monotonic(),
        )

        monitor_thread = threading.Thread(
            target=self._monitor_process,
            args=(wl,),
            daemon=True,
        )
        wl.thread = monitor_thread
        self._workloads[workload_id] = wl
        monitor_thread.start()
        return workload_id

    def stop(self, workload_id: str) -> None:
        wl = self._get_workload(workload_id)
        with wl.lock:
            if wl.process is None or wl.process.poll() is not None:
                return
            logger.info("spdk_stop", workload_id=workload_id)
            wl.process.terminate()
        # Wait for graceful exit, then force-kill
        try:
            wl.process.wait(timeout=_KILL_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            wl.process.kill()
            wl.process.wait()
        with wl.lock:
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
            )

    def get_progress(self, workload_id: str) -> WorkloadProgress:
        wl = self._get_workload(workload_id)
        with wl.lock:
            elapsed = time.monotonic() - wl.start_time if wl.start_time > 0 else 0.0
            return WorkloadProgress(
                workload_id=workload_id,
                elapsed_seconds=elapsed,
                total_seconds=float(wl.config.duration_seconds),
                current_iops=wl.stats.iops_total if wl.stats else 0.0,
                current_bandwidth_mbps=(
                    wl.stats.bandwidth_total_mbps if wl.stats else 0.0
                ),
                state=wl.state,
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

    def _get_workload(self, workload_id: str) -> _SpdkWorkload:
        wl = self._workloads.get(workload_id)
        if wl is None:
            raise WorkloadNotFoundError(f"Workload {workload_id} not found")
        return wl

    def _monitor_process(self, wl: _SpdkWorkload) -> None:
        """Background thread: wait for process to finish, then parse output."""
        proc = wl.process
        if proc is None:
            return
        try:
            stdout, stderr = proc.communicate()
        except Exception as exc:
            with wl.lock:
                wl.error = str(exc)
                wl.state = WorkloadState.FAILED
                wl.end_time = time.monotonic()
            return

        with wl.lock:
            wl.stdout_text = stdout
            wl.stderr_text = stderr
            wl.end_time = time.monotonic()
            if proc.returncode == 0:
                try:
                    wl.stats = parse_spdk_output(stdout)
                    wl.state = WorkloadState.COMPLETED
                except Exception as exc:
                    wl.error = f"Output parse error: {exc}"
                    wl.state = WorkloadState.FAILED
            elif wl.state == WorkloadState.RUNNING:
                wl.error = f"spdk_nvme_perf exited with code {proc.returncode}"
                if stderr.strip():
                    wl.error += f": {stderr.strip()[:500]}"
                wl.state = WorkloadState.FAILED

    @staticmethod
    def _build_command(config: WorkloadConfig) -> list[str]:
        """Map WorkloadConfig fields to spdk_nvme_perf CLI flags."""
        cmd = ["spdk_nvme_perf"]
        cmd.extend(["-o", str(config.io_size_bytes)])
        cmd.extend(["-q", str(config.queue_depth)])
        cmd.extend(["-w", config.workload_type.value])
        cmd.extend(["-t", str(config.duration_seconds)])

        if config.core_mask is not None:
            cmd.extend(["-c", config.core_mask])

        if config.workload_type in (WorkloadType.RANDRW, WorkloadType.RW):
            cmd.extend(["-M", str(config.read_percentage)])

        # SPDK transport address
        bdf = config.target_bdf.replace(":", ".")
        cmd.extend(["-r", f"trtype:PCIe traddr:{bdf}"])

        return cmd
