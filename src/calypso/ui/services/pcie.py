"""Shared PCIe scan and connect helpers for UI pages.

These functions run blocking PLX SDK calls and should be invoked via
``asyncio.to_thread()`` from NiceGUI async handlers.
"""

from __future__ import annotations

from calypso.utils.logging import get_logger

logger = get_logger(__name__)


class DriverSetupError(Exception):
    """Raised when the PLX SDK driver/library cannot be loaded."""


def scan_pcie_devices() -> list:
    """Load the PLX SDK and scan for PCIe devices.

    Returns:
        List of :class:`~calypso.models.device_info.DeviceInfo`.

    Raises:
        DriverSetupError: If the PLX library or driver is unavailable.
    """
    from calypso.bindings.functions import initialize
    from calypso.bindings.library import load_library
    from calypso.core.discovery import scan_devices
    from calypso.exceptions import DriverNotFoundError
    from calypso.transport.pcie import PcieTransport

    try:
        load_library()
        initialize()
    except DriverNotFoundError as exc:
        raise DriverSetupError(str(exc)) from exc
    except Exception as exc:
        raise DriverSetupError(f"Failed to initialize PLX SDK: {exc}") from exc

    try:
        return scan_devices(PcieTransport())
    except DriverNotFoundError as exc:
        raise DriverSetupError(str(exc)) from exc


def connect_pcie_device(device_index: int) -> str:
    """Connect to a PCIe device by index and register it.

    If the same BDF is already registered, the existing entry is reused
    and the new handle is closed to avoid leaking PLX SDK resources.

    Args:
        device_index: Zero-based index from a prior scan.

    Returns:
        The ``device_id`` string (e.g. ``"dev_03_00"``).

    Raises:
        ValueError: If *device_index* is negative.
        DriverSetupError: If the PLX library or driver is unavailable.
    """
    if device_index < 0:
        raise ValueError(f"Invalid device index: {device_index}")

    from calypso.api.app import get_device_registry
    from calypso.bindings.functions import initialize
    from calypso.bindings.library import load_library
    from calypso.core.switch import SwitchDevice
    from calypso.exceptions import DriverNotFoundError
    from calypso.transport.pcie import PcieTransport

    try:
        load_library()
        initialize()
    except DriverNotFoundError as exc:
        raise DriverSetupError(str(exc)) from exc

    sw = SwitchDevice(PcieTransport())
    try:
        sw.open(device_index)
        device_id = f"dev_{sw.device_info.bus:02x}_{sw.device_info.slot:02x}"
    except Exception:
        sw.close()
        raise

    registry = get_device_registry()
    existing = registry.get(device_id)
    if existing is not None:
        # Device already registered at this BDF -- reuse it, close the new handle.
        sw.close()
        return device_id

    registry[device_id] = sw
    return device_id
