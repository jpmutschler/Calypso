"""Shared MCU connection pool.

Provides process-level singleton connection management for MCU serial
connections. Both API routes and UI pages import from here to avoid
duplicate connections to the same serial port.
"""

from __future__ import annotations

import re
import sys
import threading

from calypso.mcu.client import McuClient
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()
_clients: dict[str, McuClient] = {}

_SERIAL_PORT_PATTERNS: dict[str, re.Pattern] = {
    "win32": re.compile(r"^COM\d{1,3}$"),
    "linux": re.compile(r"^/dev/tty(USB|ACM|S)\d{1,3}$"),
    "darwin": re.compile(r"^/dev/(tty|cu)\.(usbserial|usbmodem)[\w.\-]+$"),
}


def _validate_port(port: str) -> None:
    """Validate that port looks like a real serial port path.

    Raises:
        ValueError: If port does not match expected serial port patterns.
    """
    if not port or not isinstance(port, str):
        raise ValueError("Serial port path must be a non-empty string")
    pattern = _SERIAL_PORT_PATTERNS.get(sys.platform)
    if pattern and not pattern.match(port):
        raise ValueError(f"Invalid serial port path: {port}")


def get_client(port: str) -> McuClient:
    """Get or create an MCU client for the given serial port.

    Raises:
        ValueError: If port path is invalid.
        RuntimeError: If connection to the MCU fails.
    """
    _validate_port(port)
    with _lock:
        if port not in _clients or not _clients[port].is_connected:
            try:
                logger.info("mcu_pool_connecting", port=port)
                _clients[port] = McuClient(port=port)
            except Exception as exc:
                raise RuntimeError(f"MCU connection failed: {exc}") from exc
        return _clients[port]


def disconnect(port: str) -> None:
    """Disconnect and remove client for the given port."""
    with _lock:
        if port in _clients:
            logger.info("mcu_pool_disconnecting", port=port)
            try:
                _clients[port].disconnect()
            except Exception:
                logger.warning("mcu_pool_disconnect_error", port=port)
            del _clients[port]


def is_connected(port: str) -> bool:
    """Check if a port has an active connection."""
    with _lock:
        return port in _clients and _clients[port].is_connected


def list_connected() -> list[str]:
    """List serial ports with active connections."""
    with _lock:
        return [p for p, c in _clients.items() if c.is_connected]
