"""Auto-discovery splash page - detect and connect PCIe switch on launch.

This page intentionally does NOT use ``page_layout()`` because it serves
as a minimal splash screen before the user has a connected device.  It
applies dark mode and global CSS directly.
"""

from __future__ import annotations

import asyncio
import sys

from nicegui import ui

from calypso.hardware.atlas3 import get_board_profile
from calypso.ui.services.pcie import DriverSetupError, connect_pcie_device, scan_pcie_devices
from calypso.ui.theme import COLORS, GLOBAL_CSS
from calypso.utils.logging import get_logger

logger = get_logger(__name__)


def auto_discovery_page() -> None:
    """Render the auto-discovery splash at ``/``."""
    ui.dark_mode(True)
    ui.add_css(GLOBAL_CSS)

    # Check if a device is already registered -- skip scan entirely
    from calypso.api.app import get_device_registry

    registry = get_device_registry()
    if registry:
        device_id = next(iter(registry))
        ui.navigate.to(f"/switch/{device_id}")
        return

    # Main container
    container = ui.column().classes(
        "absolute-center items-center gap-6"
    ).style("max-width: 600px; width: 100%;")

    with container:
        ui.label("CALYPSO").style(
            f"color: {COLORS.cyan}; font-size: 2.5rem; font-weight: 700; "
            "letter-spacing: 0.15em;"
        )
        ui.label("Atlas3 PCIe Switch Manager").style(
            f"color: {COLORS.text_secondary}; font-size: 1rem;"
        )

        status_area = ui.column().classes("items-center gap-4 w-full mt-4")

    async def _auto_discover():
        await _run_auto_discovery(status_area)

    ui.timer(0.1, _auto_discover, once=True)


async def _run_auto_discovery(status_area: ui.column) -> None:
    """State machine for auto-discovery."""
    _show_loading(status_area)

    if sys.platform not in ("win32", "linux"):
        _show_unsupported_platform(status_area)
        return

    try:
        devices = await asyncio.to_thread(scan_pcie_devices)
    except DriverSetupError as exc:
        _show_driver_error(status_area, str(exc))
        return
    except Exception as exc:
        logger.warning("auto_discovery_failed", error=str(exc))
        _show_driver_error(status_area, str(exc))
        return

    if not devices:
        _show_no_devices(status_area)
        return

    if len(devices) == 1:
        _show_connecting(status_area)
        try:
            device_id = await asyncio.to_thread(connect_pcie_device, 0)
            ui.navigate.to(f"/switch/{device_id}")
        except Exception as exc:
            logger.error("auto_connect_failed", error=str(exc))
            _show_connection_error(status_area, str(exc))
    else:
        _show_device_selector(status_area, devices)


# ---------------------------------------------------------------------------
# UI state renderers
# ---------------------------------------------------------------------------

def _show_loading(area: ui.column) -> None:
    area.clear()
    with area:
        ui.spinner("dots", size="xl").style(f"color: {COLORS.cyan}")
        ui.label("Detecting PCIe switch...").style(
            f"color: {COLORS.text_secondary}; font-size: 1rem;"
        )


def _show_connecting(area: ui.column) -> None:
    area.clear()
    with area:
        ui.spinner("dots", size="xl").style(f"color: {COLORS.cyan}")
        ui.label("Connecting to device...").style(
            f"color: {COLORS.text_secondary}; font-size: 1rem;"
        )


def _show_unsupported_platform(area: ui.column) -> None:
    area.clear()
    with area:
        ui.icon("warning").style(
            f"color: {COLORS.yellow}; font-size: 3rem;"
        )
        ui.label("Platform Not Supported").style(
            f"color: {COLORS.text_primary}; font-size: 1.2rem; font-weight: 600;"
        )
        ui.label(
            f"PCIe auto-discovery is not available on {sys.platform}. "
            "Use manual discovery for UART or SDB connections."
        ).style(
            f"color: {COLORS.text_secondary}; text-align: center;"
        )
        ui.button(
            "Manual Discovery", icon="search",
            on_click=lambda: ui.navigate.to("/discovery"),
        ).style(f"background: {COLORS.blue}")


def _show_driver_error(area: ui.column, detail: str) -> None:
    area.clear()
    with area:
        ui.icon("error_outline").style(
            f"color: {COLORS.red}; font-size: 3rem;"
        )
        ui.label("Driver Not Available").style(
            f"color: {COLORS.text_primary}; font-size: 1.2rem; font-weight: 600;"
        )

        instructions = _platform_driver_instructions()
        ui.label(instructions).style(
            f"color: {COLORS.text_secondary}; text-align: center; "
            "white-space: pre-line;"
        )

        with ui.expansion("Details", icon="info").classes("w-full").style(
            f"color: {COLORS.text_muted}"
        ):
            ui.label(detail).style(
                f"color: {COLORS.text_muted}; font-size: 0.85rem; "
                "font-family: monospace; word-break: break-all;"
            )

        _action_buttons(area)


def _show_no_devices(area: ui.column) -> None:
    area.clear()
    with area:
        ui.icon("info_outline").style(
            f"color: {COLORS.blue}; font-size: 3rem;"
        )
        ui.label("No Devices Found").style(
            f"color: {COLORS.text_primary}; font-size: 1.2rem; font-weight: 600;"
        )
        ui.label(
            "PLX driver loaded successfully but no Atlas3 switches were detected. "
            "Check that the card is seated and powered."
        ).style(
            f"color: {COLORS.text_secondary}; text-align: center;"
        )
        _action_buttons(area)


def _show_connection_error(area: ui.column, detail: str) -> None:
    area.clear()
    with area:
        ui.icon("error_outline").style(
            f"color: {COLORS.red}; font-size: 3rem;"
        )
        ui.label("Connection Failed").style(
            f"color: {COLORS.text_primary}; font-size: 1.2rem; font-weight: 600;"
        )
        ui.label(detail).style(
            f"color: {COLORS.text_secondary}; text-align: center;"
        )
        _action_buttons(area)


def _show_device_selector(area: ui.column, devices: list) -> None:
    area.clear()
    with area:
        ui.label(f"Found {len(devices)} PCIe device(s)").style(
            f"color: {COLORS.green}; font-size: 1.1rem; font-weight: 600;"
        )
        ui.label("Select a device to connect:").style(
            f"color: {COLORS.text_secondary};"
        )

        for idx, dev in enumerate(devices):
            profile = get_board_profile(dev.chip_type, chip_id=dev.chip_id)
            bdf = f"{dev.domain:04X}:{dev.bus:02X}:{dev.slot:02X}.{dev.function}"

            with ui.card().classes("w-full p-4").style(
                f"background: {COLORS.bg_card}; "
                f"border: 1px solid {COLORS.border}; cursor: pointer;"
            ):
                with ui.row().classes("items-center gap-4 w-full"):
                    ui.icon("memory").style(f"color: {COLORS.cyan}; font-size: 2rem;")
                    with ui.column().classes("gap-1"):
                        ui.label(f"{profile.chip_name} @ {bdf}").style(
                            f"color: {COLORS.text_primary}; font-weight: bold;"
                        )
                        ui.label(
                            f"Port {dev.port_number} | "
                            f"Family: {dev.chip_family} | "
                            f"Rev: {dev.chip_revision}"
                        ).style(
                            f"color: {COLORS.text_secondary}; font-size: 13px;"
                        )
                    ui.space()
                    ui.button(
                        "Connect", icon="link",
                        on_click=lambda _e, i=idx: _on_connect_click(area, i),
                    ).style(f"background: {COLORS.green}")


async def _on_connect_click(area: ui.column, device_index: int) -> None:
    """Handle connect button click for multi-device selector."""
    _show_connecting(area)
    try:
        device_id = await asyncio.to_thread(connect_pcie_device, device_index)
        ui.navigate.to(f"/switch/{device_id}")
    except Exception as exc:
        logger.error("connect_failed", error=str(exc), index=device_index)
        _show_connection_error(area, str(exc))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _action_buttons(area: ui.column) -> None:
    """Render the standard Retry / Manual Discovery button row."""
    with ui.row().classes("gap-4"):
        ui.button(
            "Retry", icon="refresh",
            on_click=lambda: ui.navigate.to("/"),
        ).style(f"background: {COLORS.blue}")
        ui.button(
            "Manual Discovery", icon="search",
            on_click=lambda: ui.navigate.to("/discovery"),
        ).props("outline").style(f"color: {COLORS.text_secondary}")


def _platform_driver_instructions() -> str:
    if sys.platform == "win32":
        return (
            "PlxSvc service is not running or PlxApi.dll was not found.\n"
            "Run 'calypso driver install' to install and start the service.\n"
            "This requires administrator privileges."
        )
    return (
        "PlxSvc kernel module is not loaded.\n"
        "Run 'calypso driver install' to load the driver,\n"
        "or 'calypso driver build' if not yet compiled."
    )
