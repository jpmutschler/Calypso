"""Abstract interface for workload backends."""

from __future__ import annotations

import abc

from calypso.workloads.models import (
    WorkloadConfig,
    WorkloadProgress,
    WorkloadResult,
)


class WorkloadBackend(abc.ABC):
    """Base class for NVMe workload generation backends."""

    @abc.abstractmethod
    def validate_target(self, bdf: str) -> bool:
        """Check whether the NVMe device at *bdf* is accessible.

        Returns True if the device can be used, False otherwise.
        """

    @abc.abstractmethod
    def start(self, config: WorkloadConfig) -> str:
        """Start a workload and return a unique workload ID."""

    @abc.abstractmethod
    def stop(self, workload_id: str) -> None:
        """Stop a running workload."""

    @abc.abstractmethod
    def get_result(self, workload_id: str) -> WorkloadResult:
        """Retrieve the final result for a finished workload."""

    @abc.abstractmethod
    def get_progress(self, workload_id: str) -> WorkloadProgress:
        """Retrieve live progress for a running workload."""

    @abc.abstractmethod
    def is_running(self, workload_id: str) -> bool:
        """Return True if the workload is still running."""

    @property
    @abc.abstractmethod
    def backend_name(self) -> str:
        """Human-readable name of this backend."""
