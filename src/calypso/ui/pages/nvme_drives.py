"""NVMe drive discovery and SMART health monitoring page.

Provides scan button, card grid per drive with temperature gauge,
spare bar, drive life bar, critical warning indicator. Auto-refresh.
"""

from __future__ import annotations

from nicegui import app, run, ui

from calypso.mcu import pool
from calypso.ui.components.mcu_common import (
    no_mcu_message,
    page_header,
    set_status_error,
    set_status_live,
    status_indicator,
)
from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS


def _temp_color(celsius: int) -> str:
    """Return color based on temperature threshold."""
    if celsius < 50:
        return COLORS.green
    if celsius < 70:
        return COLORS.yellow
    return COLORS.red


def _spare_color(percent: int) -> str:
    """Return color based on available spare percentage."""
    if percent > 30:
        return COLORS.green
    if percent > 10:
        return COLORS.yellow
    return COLORS.red


def _nvme_drives_content() -> None:
    """Build the NVMe drives page content."""
    mcu_port = app.storage.user.get("mcu_port")
    if not mcu_port:
        no_mcu_message()
        return

    page_header("NVMe Drive Management", f"MCU: {mcu_port} | NVMe-MI over MCTP")

    status = status_indicator()
    drive_container = ui.column().classes("w-full gap-4")
    discovered_drives: list = []

    async def do_scan():
        """Scan for NVMe drives."""
        from calypso.nvme_mi.discovery import discover_nvme_drives

        try:
            status.text = "Scanning..."
            status.style(f"color: {COLORS.cyan}")
            result = await run.io_bound(
                lambda: discover_nvme_drives(pool.get_client(mcu_port))
            )
            discovered_drives.clear()
            discovered_drives.extend(result.drives)
            _render_drives(drive_container, discovered_drives)

            if result.scan_errors:
                status.text = f"Found {result.drive_count} drive(s), {len(result.scan_errors)} error(s)"
                status.style(f"color: {COLORS.yellow}")
            else:
                set_status_live(status)
                status.text = f"Found {result.drive_count} drive(s)"
        except Exception as exc:
            set_status_error(status, exc)

    async def refresh_health():
        """Refresh health for all discovered drives."""
        if not discovered_drives:
            return
        from calypso.mctp.transport import MCTPOverI2C
        from calypso.mcu.bus import I2cBus
        from calypso.nvme_mi.client import NVMeMIClient

        try:
            client = pool.get_client(mcu_port)
            for drive in discovered_drives:
                try:
                    bus = I2cBus(client, drive.connector, drive.channel)
                    transport = MCTPOverI2C(bus)
                    nvme = NVMeMIClient(transport)
                    health = await run.io_bound(
                        lambda _n=nvme, _d=drive: _n.health_poll(
                            slave_addr=_d.slave_addr, eid=_d.eid
                        )
                    )
                    drive.health = health
                    drive.reachable = True
                except Exception:
                    drive.reachable = False

            _render_drives(drive_container, discovered_drives)
            set_status_live(status)
        except Exception as exc:
            set_status_error(status, exc)

    with ui.row().classes("w-full gap-4 items-center"):
        ui.button("Scan for Drives", on_click=do_scan, icon="search").props(
            "color=primary"
        )
        ui.button("Refresh Health", on_click=refresh_health, icon="refresh").props(
            "color=secondary"
        )

    # Auto-refresh timer (every 5 seconds, only when drives are discovered)
    ui.timer(5.0, lambda: refresh_health() if discovered_drives else None)


def _render_drives(container: ui.column, drives: list) -> None:
    """Render drive cards into the container."""
    container.clear()

    if not drives:
        with container:
            with ui.card().classes("w-full p-6 items-center").style(
                f"background: {COLORS.bg_card}; border: 1px solid {COLORS.border}"
            ):
                ui.icon("storage").classes("text-4xl").style(
                    f"color: {COLORS.text_muted}"
                )
                ui.label("No NVMe drives discovered").style(
                    f"color: {COLORS.text_secondary}"
                )
                ui.label(
                    "Click 'Scan for Drives' to search all connectors."
                ).style(f"color: {COLORS.text_muted}")
        return

    with container:
        with ui.row().classes("w-full gap-4 flex-wrap"):
            for drive in drives:
                _drive_card(drive)


def _drive_card(drive) -> None:
    """Render a single drive health card."""
    health = drive.health
    border_color = COLORS.red if health.has_critical_warning else COLORS.border

    with ui.card().classes("p-4 min-w-[320px] flex-1").style(
        f"background: {COLORS.bg_card}; "
        f"border: 2px solid {border_color}; "
        f"max-width: 420px"
    ):
        # Header
        with ui.row().classes("w-full items-center gap-2 mb-3"):
            ui.icon("storage").style(f"color: {COLORS.cyan}")
            with ui.column().classes("gap-0"):
                ui.label(drive.display_name).classes("text-subtitle2").style(
                    f"color: {COLORS.text_primary}"
                )
                ui.label(
                    f"CN{drive.connector}/{drive.channel} (0x{drive.slave_addr:02X})"
                ).classes("text-caption").style(f"color: {COLORS.text_muted}")

        # Critical warning banner
        if health.has_critical_warning:
            with ui.row().classes("w-full items-center gap-2 p-2 rounded mb-3").style(
                f"background: {COLORS.red}22; border: 1px solid {COLORS.red}"
            ):
                ui.icon("warning").style(f"color: {COLORS.red}")
                ui.label(f"Critical Warning: 0x{health.critical_warning:02X}").style(
                    f"color: {COLORS.red}"
                )

        # Unreachable indicator
        if not drive.reachable:
            with ui.row().classes("w-full items-center gap-2 p-2 rounded mb-3").style(
                f"background: {COLORS.yellow}22; border: 1px solid {COLORS.yellow}"
            ):
                ui.icon("signal_wifi_off").style(f"color: {COLORS.yellow}")
                ui.label("Drive unreachable").style(f"color: {COLORS.yellow}")

        # Temperature
        with ui.row().classes("w-full items-center gap-3 mb-2"):
            ui.icon("thermostat").style(f"color: {_temp_color(health.composite_temperature_celsius)}")
            ui.label("Temperature").classes("text-caption flex-1").style(
                f"color: {COLORS.text_secondary}"
            )
            ui.label(f"{health.composite_temperature_celsius} C").classes(
                "text-subtitle2"
            ).style(f"color: {_temp_color(health.composite_temperature_celsius)}")

        # Available Spare bar
        with ui.column().classes("w-full gap-1 mb-2"):
            with ui.row().classes("w-full items-center"):
                ui.label("Available Spare").classes("text-caption flex-1").style(
                    f"color: {COLORS.text_secondary}"
                )
                ui.label(f"{health.available_spare_percent}%").classes(
                    "text-caption"
                ).style(f"color: {_spare_color(health.available_spare_percent)}")
            ui.linear_progress(
                value=health.available_spare_percent / 100,
                color=_spare_color(health.available_spare_percent),
            ).classes("w-full").props("rounded")

        # Drive Life bar
        life_remaining = health.drive_life_remaining_percent
        with ui.column().classes("w-full gap-1 mb-2"):
            with ui.row().classes("w-full items-center"):
                ui.label("Drive Life").classes("text-caption flex-1").style(
                    f"color: {COLORS.text_secondary}"
                )
                ui.label(f"{life_remaining}% remaining").classes(
                    "text-caption"
                ).style(f"color: {_spare_color(life_remaining)}")
            ui.linear_progress(
                value=life_remaining / 100,
                color=_spare_color(life_remaining),
            ).classes("w-full").props("rounded")

        # Power-on hours
        if health.power_on_hours > 0:
            with ui.row().classes("w-full items-center gap-3"):
                ui.icon("schedule").style(f"color: {COLORS.text_muted}")
                ui.label("Power-On Hours").classes("text-caption flex-1").style(
                    f"color: {COLORS.text_secondary}"
                )
                ui.label(f"{health.power_on_hours:,}").classes("text-caption").style(
                    f"color: {COLORS.text_primary}"
                )


def nvme_drives_page() -> None:
    """Render the NVMe drives page."""
    page_layout("NVMe Drives", _nvme_drives_content)
