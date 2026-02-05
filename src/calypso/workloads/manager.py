"""Workload lifecycle manager -- orchestrates backends and prevents conflicts."""

from __future__ import annotations

import threading

from calypso.utils.logging import get_logger
from calypso.workloads.base import WorkloadBackend
from calypso.workloads.exceptions import (
    WorkloadAlreadyRunning,
    WorkloadBackendUnavailable,
    WorkloadNotFoundError,
)
from calypso.workloads.models import (
    BackendType,
    WorkloadConfig,
    WorkloadState,
    WorkloadStatus,
)

logger = get_logger(__name__)


class WorkloadManager:
    """Manages workload lifecycle across all available backends."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._backends: dict[BackendType, WorkloadBackend] = {}
        self._workload_backend_map: dict[str, BackendType] = {}
        self._active_bdfs: dict[str, str] = {}  # bdf -> workload_id
        self._configs: dict[str, WorkloadConfig] = {}
        self._initialized = False

    def _init_backends(self) -> None:
        """Lazy-load available backends on first use."""
        if self._initialized:
            return
        self._initialized = True

        from calypso.workloads import is_pynvme_available, is_spdk_available

        if is_spdk_available():
            from calypso.workloads.spdk_backend import SpdkBackend
            self._backends[BackendType.SPDK] = SpdkBackend()
            logger.info("workload_backend_loaded", backend="spdk")

        if is_pynvme_available():
            from calypso.workloads.pynvme_backend import PynvmeBackend
            self._backends[BackendType.PYNVME] = PynvmeBackend()
            logger.info("workload_backend_loaded", backend="pynvme")

    @property
    def available_backends(self) -> list[BackendType]:
        """Return list of backends that are installed and usable."""
        self._init_backends()
        return list(self._backends.keys())

    def validate_target(self, backend_type: BackendType, bdf: str) -> bool:
        """Validate whether a target BDF is accessible via the given backend."""
        self._init_backends()
        backend = self._backends.get(backend_type)
        if backend is None:
            return False
        return backend.validate_target(bdf)

    def start_workload(self, config: WorkloadConfig) -> WorkloadStatus:
        """Start a workload, returning its initial status."""
        self._init_backends()

        backend = self._backends.get(config.backend)
        if backend is None:
            raise WorkloadBackendUnavailable(
                f"Backend '{config.backend.value}' is not available. "
                f"Available: {[b.value for b in self._backends]}"
            )

        with self._lock:
            # Prevent duplicate BDF usage
            existing_id = self._active_bdfs.get(config.target_bdf)
            if existing_id is not None:
                existing_backend = self._workload_backend_map.get(existing_id)
                if existing_backend is not None:
                    eb = self._backends.get(existing_backend)
                    if eb is not None and eb.is_running(existing_id):
                        raise WorkloadAlreadyRunning(
                            f"BDF {config.target_bdf} already has active workload "
                            f"{existing_id}"
                        )
                # Previous workload finished, clean up stale tracking
                del self._active_bdfs[config.target_bdf]

            workload_id = backend.start(config)

            self._workload_backend_map[workload_id] = config.backend
            self._active_bdfs[config.target_bdf] = workload_id
            self._configs[workload_id] = config

        logger.info(
            "workload_started",
            workload_id=workload_id,
            backend=config.backend.value,
            bdf=config.target_bdf,
        )

        return WorkloadStatus(
            workload_id=workload_id,
            backend=config.backend,
            target_bdf=config.target_bdf,
            state=WorkloadState.RUNNING,
            config=config,
        )

    def stop_workload(self, workload_id: str) -> WorkloadStatus:
        """Stop a running workload."""
        backend = self._get_backend_for(workload_id)
        backend.stop(workload_id)
        result = backend.get_result(workload_id)
        config = self._configs[workload_id]

        with self._lock:
            # Clean up BDF tracking
            for bdf, wl_id in list(self._active_bdfs.items()):
                if wl_id == workload_id:
                    del self._active_bdfs[bdf]
                    break

        return WorkloadStatus(
            workload_id=workload_id,
            backend=config.backend,
            target_bdf=config.target_bdf,
            state=result.state,
            config=config,
            result=result,
        )

    def get_status(self, workload_id: str) -> WorkloadStatus:
        """Get full status of a workload."""
        backend = self._get_backend_for(workload_id)
        config = self._configs[workload_id]
        result = backend.get_result(workload_id)

        progress = None
        if backend.is_running(workload_id):
            progress = backend.get_progress(workload_id)

        return WorkloadStatus(
            workload_id=workload_id,
            backend=config.backend,
            target_bdf=config.target_bdf,
            state=result.state,
            config=config,
            result=result if result.state != WorkloadState.RUNNING else None,
            progress=progress,
        )

    def list_workloads(self) -> list[WorkloadStatus]:
        """List all tracked workloads."""
        with self._lock:
            workload_ids = list(self._workload_backend_map.keys())
        statuses = []
        for workload_id in workload_ids:
            try:
                statuses.append(self.get_status(workload_id))
            except Exception:
                logger.debug("list_workloads_skip", workload_id=workload_id)
        return statuses

    def shutdown(self) -> None:
        """Stop all running workloads and clean up."""
        for backend in self._backends.values():
            if hasattr(backend, "shutdown"):
                try:
                    backend.shutdown()
                except Exception:
                    logger.warning("backend_shutdown_error", backend=backend.backend_name)
        with self._lock:
            self._active_bdfs.clear()
        logger.info("workload_manager_shutdown")

    def _get_backend_for(self, workload_id: str) -> WorkloadBackend:
        """Look up the backend responsible for a given workload."""
        backend_type = self._workload_backend_map.get(workload_id)
        if backend_type is None:
            raise WorkloadNotFoundError(f"Workload {workload_id} not found")
        backend = self._backends.get(backend_type)
        if backend is None:
            raise WorkloadNotFoundError(
                f"Backend for workload {workload_id} is no longer available"
            )
        return backend
