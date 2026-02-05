"""Optional NVMe workload generation module.

Probes for available backends (SPDK perf, pynvme) at runtime and
degrades gracefully when neither is installed.
"""

from __future__ import annotations

import shutil

_pynvme_available: bool | None = None
_spdk_available: bool | None = None


def is_pynvme_available() -> bool:
    """Check whether the pynvme library can be imported."""
    global _pynvme_available
    if _pynvme_available is None:
        try:
            import pynvme  # noqa: F401
            _pynvme_available = True
        except ImportError:
            _pynvme_available = False
    return _pynvme_available


def is_spdk_available() -> bool:
    """Check whether the spdk_nvme_perf binary is on PATH."""
    global _spdk_available
    if _spdk_available is None:
        _spdk_available = shutil.which("spdk_nvme_perf") is not None
    return _spdk_available


def is_any_backend_available() -> bool:
    """Return True if at least one workload backend is usable."""
    return is_pynvme_available() or is_spdk_available()


def available_backends() -> list[str]:
    """Return names of all usable backends."""
    backends: list[str] = []
    if is_spdk_available():
        backends.append("spdk")
    if is_pynvme_available():
        backends.append("pynvme")
    return backends
