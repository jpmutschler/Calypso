"""Device discovery page - scan and connect to Atlas3 devices."""

from __future__ import annotations

import asyncio
import sys

from nicegui import app, ui

from calypso.mcu import pool
from calypso.mcu.client import McuClient
from calypso.ui.layout import page_layout
from calypso.ui.services.pcie import connect_pcie_device, scan_pcie_devices
from calypso.ui.theme import COLORS
from calypso.utils.logging import get_logger

logger = get_logger(__name__)


def discovery_page() -> None:
    """Render the device discovery page at /discovery."""

    def content():
        _discovery_content()

    page_layout("Device Discovery", content)


def _discovery_content() -> None:
    """Build the discovery page content inside page_layout."""

    ui.label(
        "Scan for Atlas3 PCIe switches via UART, SDB, or PCIe bus."
    ).style(f"color: {COLORS.text_secondary}")

    # Transport selection
    with ui.card().classes("w-full p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    ):
        ui.label("Transport").classes("text-subtitle2 mb-2").style(
            f"color: {COLORS.text_primary}"
        )

        ui.select(
            ["PCIe Bus", "UART (MCU/USB)", "SDB (USB)"],
            value="PCIe Bus",
        ).classes("w-full")

        with ui.row().classes("gap-4 mt-2"):
            ui.number("Port", value=0, min=0).classes("w-32")
            ui.select(["115200", "19200"], value="115200").classes("w-32")

        ui.button("Scan for Devices", icon="search").classes("mt-2").style(
            f"background: {COLORS.blue}"
        )

    # Results area
    results_container = ui.column().classes("w-full gap-2")

    def _show_pcie_results(devices: list) -> None:
        """Populate the results container with PCIe scan results."""
        results_container.clear()
        with results_container:
            if not devices:
                ui.label("No PCIe devices found.").style(
                    f"color: {COLORS.text_muted}"
                )
                return

            ui.label(f"Found {len(devices)} PCIe device(s)").style(
                f"color: {COLORS.green}; font-weight: bold"
            )

            for idx, dev in enumerate(devices):
                with ui.card().classes("w-full p-3").style(
                    f"background: {COLORS.bg_card}; "
                    f"border: 1px solid {COLORS.border}"
                ):
                    with ui.row().classes("items-center gap-4"):
                        ui.icon("memory").style(f"color: {COLORS.cyan}")
                        with ui.column().classes("gap-1"):
                            chip_id = dev.chip_id
                            bdf = f"{dev.domain:04X}:{dev.bus:02X}:{dev.slot:02X}.{dev.function}"
                            ui.label(
                                f"PLX {chip_id:#06x} @ {bdf}"
                            ).style(
                                f"color: {COLORS.text_primary}; font-weight: bold"
                            )
                            ui.label(
                                f"Port {dev.port_number} | "
                                f"Family: {dev.chip_family} | "
                                f"Rev: {dev.chip_revision}"
                            ).style(
                                f"color: {COLORS.text_secondary}; font-size: 13px"
                            )

                        ui.space()

                        async def _connect_click(_e, device_index=idx):
                            try:
                                device_id = await asyncio.to_thread(
                                    connect_pcie_device, device_index
                                )
                                ui.navigate.to(f"/switch/{device_id}")
                            except Exception as exc:
                                logger.error(
                                    "connect_failed", error=str(exc),
                                    index=device_index,
                                )
                                ui.notify(
                                    "Connection failed. Check logs for details.",
                                    type="negative",
                                )

                        ui.button(
                            "Connect", icon="link", on_click=_connect_click,
                        ).style(f"background: {COLORS.green}")

    with results_container:
        ui.label("No scan results yet.").style(f"color: {COLORS.text_muted}")

    # Auto-scan PCIe on page load (Windows and Linux only)
    async def _auto_scan_pcie():
        if sys.platform not in ("win32", "linux"):
            return
        try:
            devices = await asyncio.to_thread(scan_pcie_devices)
            if devices:
                _show_pcie_results(devices)
        except Exception:
            logger.debug("pcie_auto_scan_skipped", exc_info=True)

    ui.timer(0.1, _auto_scan_pcie, once=True)

    # MCU Connection
    with ui.card().classes("w-full p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    ):
        with ui.row().classes("items-center gap-2 mb-2"):
            ui.icon("usb").classes("text-lg").style(
                f"color: {COLORS.blue}"
            )
            ui.label("MCU Connection").classes("text-subtitle2").style(
                f"color: {COLORS.text_primary}"
            )
        ui.label(
            "Connect to Atlas3 MCU via serial port for thermal, fan, power, and port monitoring."
        ).classes("text-caption mb-3").style(
            f"color: {COLORS.text_secondary}"
        )

        with ui.row().classes("items-end gap-4"):
            mcu_port_select = ui.select(
                [], label="Serial Port"
            ).classes("w-64")

            async def scan_mcu():
                try:
                    ports = await asyncio.to_thread(McuClient.find_devices)
                    mcu_port_select.options = ports
                    if ports:
                        mcu_port_select.value = ports[0]
                    mcu_port_select.update()
                    if ports:
                        ui.notify(f"Found {len(ports)} device(s)", type="positive")
                    else:
                        ui.notify("No MCU devices found", type="warning")
                except Exception as exc:
                    ui.notify(f"Scan failed: {exc}", type="negative")

            ui.button("Scan", icon="search", on_click=scan_mcu).style(
                f"background: {COLORS.blue}"
            )

        mcu_status = ui.label("Not connected").classes("text-caption mt-3").style(
            f"color: {COLORS.text_muted}"
        )

        with ui.row().classes("gap-2 mt-2"):
            async def connect_mcu():
                selected = mcu_port_select.value
                if not selected:
                    ui.notify("Select a serial port first", type="warning")
                    return
                try:
                    pool.get_client(selected)
                    app.storage.user["mcu_port"] = selected
                    mcu_status.text = f"Connected: {selected}"
                    mcu_status.style(f"color: {COLORS.green}")
                    ui.notify(f"Connected to {selected}", type="positive")
                except Exception as exc:
                    ui.notify(f"Connection failed: {exc}", type="negative")

            async def disconnect_mcu():
                existing = app.storage.user.get("mcu_port")
                if existing:
                    pool.disconnect(existing)
                    app.storage.user.pop("mcu_port", None)
                    mcu_status.text = "Not connected"
                    mcu_status.style(f"color: {COLORS.text_muted}")
                    ui.notify("MCU disconnected", type="info")

            ui.button("Connect", icon="usb", on_click=connect_mcu).style(
                f"background: {COLORS.green}"
            )
            ui.button("Disconnect", icon="usb_off", on_click=disconnect_mcu).props(
                "flat"
            ).style(f"color: {COLORS.text_secondary}")

        # Show existing connection on page load
        existing_port = app.storage.user.get("mcu_port")
        if existing_port and pool.is_connected(existing_port):
            mcu_status.text = f"Connected: {existing_port}"
            mcu_status.style(f"color: {COLORS.green}")
