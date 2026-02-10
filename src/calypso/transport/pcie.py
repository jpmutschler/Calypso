"""PCIe bus transport implementation."""

from __future__ import annotations

import sys

from calypso.bindings.constants import PlxApiMode
from calypso.bindings.types import PLX_MODE_PROP
from calypso.exceptions import DriverNotFoundError
from calypso.transport.base import PcieConfig, Transport
from calypso.utils.logging import get_logger

logger = get_logger(__name__)


class PcieTransport(Transport):
    """Transport using PCIe bus via PLX driver.

    Uses PLX_API_MODE_PCI. Requires the PLX driver to be loaded
    (PlxSvc kernel module on Linux, PlxSvc service + PlxApi.dll on Windows).
    """

    def __init__(self, config: PcieConfig | None = None) -> None:
        super().__init__(config or PcieConfig())

    @property
    def api_mode(self) -> PlxApiMode:
        return PlxApiMode.PCI

    def build_mode_prop(self) -> PLX_MODE_PROP | None:
        # PCI mode doesn't use mode properties
        return None

    def scan_ports(self) -> list[str]:
        """PCIe bus scanning is done through the SDK's DeviceFind.

        Returns an empty list since PCI enumeration is handled
        at the SDK level, not at the transport level.
        """
        return []

    def connect(self) -> None:
        if self._connected:
            return

        if sys.platform == "win32":
            self._check_library_available()
            self._check_service_running()
        elif sys.platform == "linux":
            self._check_driver_loaded()
        else:
            raise DriverNotFoundError(
                f"PCIe transport not supported on {sys.platform}."
            )

        logger.info("pcie_connecting")
        self._connected = True
        logger.info("pcie_connected")

    def disconnect(self) -> None:
        if not self._connected:
            return
        logger.info("pcie_disconnecting")
        self._connected = False
        logger.info("pcie_disconnected")

    def _check_library_available(self) -> None:
        """Verify PlxApi.dll can be loaded on Windows."""
        try:
            from calypso.bindings.library import load_library

            load_library()
        except Exception as exc:
            raise DriverNotFoundError(
                f"PlxApi.dll not found. Ensure PLX SDK is installed and "
                f"PLX_SDK_DIR is set. Detail: {exc}"
            ) from exc

    def _check_service_running(self) -> None:
        """Verify the PlxSvc Windows service is running."""
        try:
            from calypso.driver.manager import DriverManager

            mgr = DriverManager()
            status = mgr.get_status()
            if not status.is_loaded:
                raise DriverNotFoundError(
                    "PlxSvc service is not running. "
                    "Run 'calypso driver install' to install and start it."
                )
        except FileNotFoundError as exc:
            raise DriverNotFoundError(
                "PLX SDK not found. Set PLX_SDK_DIR environment variable. "
                "Run 'calypso driver check' for prerequisite details."
            ) from exc
        except DriverNotFoundError:
            raise
        except Exception as exc:
            raise DriverNotFoundError(
                f"Failed to check PlxSvc service status: {exc}. "
                "Run 'calypso driver check' for prerequisite details."
            ) from exc

    def _check_driver_loaded(self) -> None:
        """Verify the PlxSvc kernel module is loaded."""
        try:
            from calypso.driver.manager import DriverManager

            mgr = DriverManager()
            status = mgr.get_status()
            if not status.is_loaded:
                raise DriverNotFoundError(
                    "PlxSvc kernel module is not loaded. "
                    "Run 'calypso driver install' to load it, "
                    "or 'calypso driver build' first if not yet built."
                )
        except FileNotFoundError as exc:
            raise DriverNotFoundError(
                "PLX SDK not found. Set PLX_SDK_DIR environment variable. "
                "Run 'calypso driver check' for prerequisite details."
            ) from exc
