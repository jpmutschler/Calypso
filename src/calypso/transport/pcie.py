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
    """Transport using PCIe bus via PLX kernel driver.

    Uses PLX_API_MODE_PCI. Requires the PLX driver to be loaded.
    Linux only.
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

        if sys.platform != "linux":
            raise DriverNotFoundError(
                "PCIe transport requires Linux. "
                "Use UART or SDB transport on this platform."
            )

        self._check_driver_loaded()
        logger.info("pcie_connecting")
        self._connected = True
        logger.info("pcie_connected")

    def disconnect(self) -> None:
        if not self._connected:
            return
        logger.info("pcie_disconnecting")
        self._connected = False
        logger.info("pcie_disconnected")

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
