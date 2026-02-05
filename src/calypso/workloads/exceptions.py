"""Workload-specific exception hierarchy."""

from __future__ import annotations

from calypso.exceptions import CalypsoError


class WorkloadError(CalypsoError):
    """Base exception for workload operations."""


class WorkloadBackendUnavailable(WorkloadError):
    """The requested workload backend is not installed or not found."""


class WorkloadNotFoundError(WorkloadError):
    """No workload exists with the given ID."""


class WorkloadAlreadyRunning(WorkloadError):
    """A workload is already running on the target BDF."""


class WorkloadTargetError(WorkloadError):
    """The NVMe target device is inaccessible or invalid."""
