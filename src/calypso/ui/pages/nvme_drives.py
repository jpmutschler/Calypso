"""NVMe drive discovery and SMART health monitoring page.

Provides scan controls with connector/channel filtering, summary stat cards,
card grid per drive with temperature gauge, spare bar, drive life bar,
critical warning flags, and expandable per-controller detail. Auto-refresh.
"""

from __future__ import annotations

import datetime

from nicegui import app, run, ui

from calypso.mcu import pool
from calypso.ui.components.mcu_common import (
    card_header,
    card_style,
    no_mcu_message,
    page_header,
    set_status_error,
    set_status_live,
    stat_card,
    status_indicator,
)
from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS
from calypso.utils.logging import get_logger

logger = get_logger(__name__)


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


_WARNING_FLAG_DEFS: list[tuple[int, str, str]] = [
    (0x01, "disc_full", "Spare Below Threshold"),
    (0x02, "thermostat", "Temperature Exceeded"),
    (0x04, "trending_down", "Reliability Degraded"),
    (0x08, "edit_off", "Read-Only Mode"),
    (0x10, "battery_alert", "Volatile Backup Failed"),
]


def _warning_flags(critical_warning: int) -> list[tuple[str, str]]:
    """Return list of (icon, label) for active warning bits."""
    return [
        (icon, label) for mask, icon, label in _WARNING_FLAG_DEFS
        if critical_warning & mask
    ]


_CONTROLLER_COLUMNS = [
    {"name": "id", "label": "Controller ID", "field": "id", "align": "left"},
    {"name": "temp", "label": "Temp (\u00b0C)", "field": "temp", "align": "center"},
    {"name": "spare", "label": "Spare %", "field": "spare", "align": "center"},
    {"name": "used", "label": "Used %", "field": "used", "align": "center"},
    {"name": "warning", "label": "Warning", "field": "warning", "align": "center"},
]


def _nvme_drives_content() -> None:
    """Build the NVMe drives page content."""
    mcu_port = app.storage.user.get("mcu_port")
    if not mcu_port:
        no_mcu_message()
        return

    page_header("NVMe Drive Management", f"MCU: {mcu_port} | NVMe-MI over MCTP")

    # --- Summary stat cards ---
    with ui.row().classes("w-full gap-4 flex-wrap"):
        total_label = stat_card("Total Drives", "storage")
        healthy_label = stat_card("Healthy", "check_circle")
        warning_label = stat_card("Warnings", "warning")
        avg_temp_label = stat_card("Avg Temperature", "thermostat")

    stat_labels = {
        "total": total_label,
        "healthy": healthy_label,
        "warnings": warning_label,
        "avg_temp": avg_temp_label,
    }

    # --- Scan controls ---
    with ui.card().classes("w-full p-4").style(card_style()):
        card_header("Scan Controls", "radar")
        with ui.row().classes("w-full items-end gap-4 flex-wrap"):
            cn_from = ui.number("From CN", value=0, min=0, max=5).classes("w-28")
            cn_to = ui.number("To CN", value=5, min=0, max=5).classes("w-28")
            channel_select = ui.select(
                {"both": "Both", "a": "A only", "b": "B only"},
                value="both",
                label="Channel",
            ).classes("w-32")
            scan_btn = ui.button("Scan for Drives", icon="search").props("color=primary")
            scan_status = ui.label("").classes("text-caption").style(
                f"color: {COLORS.text_muted}"
            )

    # --- State ---
    discovered_drives: list = []
    expand_state: dict[str, bool] = {}
    status = status_indicator()

    # --- Drive container ---
    drive_container = ui.column().classes("w-full gap-4")

    def _update_summary() -> None:
        """Update the four summary stat cards from current drive data."""
        total = len(discovered_drives)
        stat_labels["total"].text = str(total)
        stat_labels["total"].style(f"color: {COLORS.text_primary}")

        if total == 0:
            stat_labels["healthy"].text = "--"
            stat_labels["healthy"].style(f"color: {COLORS.text_primary}")
            stat_labels["warnings"].text = "--"
            stat_labels["warnings"].style(f"color: {COLORS.text_primary}")
            stat_labels["avg_temp"].text = "--"
            stat_labels["avg_temp"].style(f"color: {COLORS.text_primary}")
            return

        healthy = sum(1 for d in discovered_drives if not d.health.has_critical_warning)
        warnings = total - healthy
        avg_t = sum(d.health.composite_temperature_celsius for d in discovered_drives) // total

        stat_labels["healthy"].text = str(healthy)
        stat_labels["healthy"].style(
            f"color: {COLORS.green if healthy == total else COLORS.yellow}"
        )

        stat_labels["warnings"].text = str(warnings)
        stat_labels["warnings"].style(
            f"color: {COLORS.red if warnings > 0 else COLORS.green}"
        )

        stat_labels["avg_temp"].text = f"{avg_t}\u00b0C"
        stat_labels["avg_temp"].style(f"color: {_temp_color(avg_t)}")

    async def do_scan() -> None:
        """Scan for NVMe drives with connector/channel filter."""
        from calypso.nvme_mi.discovery import discover_nvme_drives

        current_port = app.storage.user.get("mcu_port")
        if not current_port:
            set_status_error(status, Exception("MCU disconnected"))
            return

        try:
            scan_btn.props("loading")
            scan_status.text = "Scanning..."
            scan_status.style(f"color: {COLORS.cyan}")

            from_cn = int(cn_from.value or 0)
            to_cn = int(cn_to.value or 5)
            connectors = list(range(from_cn, to_cn + 1))

            ch_val = channel_select.value
            channels = ["a", "b"] if ch_val == "both" else [ch_val]

            result = await run.io_bound(
                lambda: discover_nvme_drives(
                    pool.get_client(current_port),
                    connectors=connectors,
                    channels=channels,
                )
            )
            discovered_drives.clear()
            discovered_drives.extend(result.drives)
            _render_drives(drive_container, discovered_drives, expand_state)
            _update_summary()

            now = datetime.datetime.now().strftime("%H:%M:%S")
            if result.scan_errors:
                scan_status.text = (
                    f"Found {result.drive_count} drive(s), "
                    f"{len(result.scan_errors)} error(s) \u2014 {now}"
                )
                scan_status.style(f"color: {COLORS.yellow}")
            else:
                scan_status.text = f"Found {result.drive_count} drive(s) \u2014 {now}"
                scan_status.style(f"color: {COLORS.green}")
                set_status_live(status)
        except Exception as exc:
            set_status_error(status, exc)
            scan_status.text = f"Scan failed: {str(exc)[:120]}"
            scan_status.style(f"color: {COLORS.red}")
        finally:
            scan_btn.props(remove="loading")

    scan_btn.on_click(do_scan)

    async def refresh_health() -> None:
        """Refresh health for all discovered drives."""
        if not discovered_drives:
            return

        current_port = app.storage.user.get("mcu_port")
        if not current_port:
            set_status_error(status, Exception("MCU disconnected"))
            return

        from calypso.mctp.transport import MCTPOverI2C
        from calypso.mcu.bus import I2cBus
        from calypso.nvme_mi.client import NVMeMIClient

        try:
            client = pool.get_client(current_port)
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

            _render_drives(drive_container, discovered_drives, expand_state)
            _update_summary()
            set_status_live(status)
        except Exception as exc:
            set_status_error(status, exc)

    # --- Auto-refresh controls ---
    with ui.row().classes("w-full items-center gap-4"):
        auto_switch = ui.switch("Auto-refresh health").props("color=cyan")
        ui.button("Refresh Now", icon="refresh", on_click=refresh_health).props(
            "color=secondary flat"
        )

    async def _auto_refresh() -> None:
        if auto_switch.value and discovered_drives:
            await refresh_health()

    ui.timer(5.0, _auto_refresh)


def _render_drives(
    container: ui.column,
    drives: list,
    expand_state: dict[str, bool],
) -> None:
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
                    "Click 'Scan for Drives' to search connectors."
                ).style(f"color: {COLORS.text_muted}")
        return

    with container:
        with ui.row().classes("w-full gap-4 flex-wrap"):
            for drive in drives:
                _drive_card(drive, expand_state)


def _drive_card(
    drive,
    expand_state: dict[str, bool],
) -> None:
    """Render a single drive health card with expandable details."""
    health = drive.health
    border_color = COLORS.red if health.has_critical_warning else COLORS.border
    card_key = f"CN{drive.connector}/{drive.channel}"

    with ui.card().classes("p-4 min-w-[340px] flex-1").style(
        f"background: {COLORS.bg_card}; "
        f"border: 2px solid {border_color}; "
        f"max-width: 460px"
    ):
        # Header row: display name + location badge + reachable indicator
        with ui.row().classes("w-full items-center gap-2 mb-3"):
            ui.icon("storage").style(f"color: {COLORS.cyan}")
            with ui.column().classes("gap-0 flex-1"):
                ui.label(drive.display_name).classes("text-subtitle2").style(
                    f"color: {COLORS.text_primary}"
                )
                with ui.row().classes("items-center gap-2"):
                    ui.badge(card_key).props("outline color=cyan")
                    if drive.subsystem.nqn:
                        version_str = (
                            f"NVMe {drive.subsystem.major_version}."
                            f"{drive.subsystem.minor_version}"
                        )
                        ui.badge(version_str).props("outline color=grey")
                    if drive.subsystem.number_of_ports > 0:
                        ui.badge(
                            f"{drive.subsystem.number_of_ports} port(s)"
                        ).props("outline color=grey")
            # Reachable indicator
            if drive.reachable:
                ui.icon("wifi").classes("text-sm").style(f"color: {COLORS.green}")
            else:
                ui.icon("signal_wifi_off").classes("text-sm").style(
                    f"color: {COLORS.yellow}"
                )

        # Warning flags (when critical_warning != 0)
        active_flags = _warning_flags(health.critical_warning)
        if active_flags:
            with ui.column().classes("w-full gap-1 mb-3 p-2 rounded").style(
                f"background: {COLORS.red}15; border: 1px solid {COLORS.red}"
            ):
                for icon, label in active_flags:
                    with ui.row().classes("items-center gap-2"):
                        ui.icon(icon).classes("text-sm").style(f"color: {COLORS.red}")
                        ui.label(label).classes("text-caption").style(
                            f"color: {COLORS.red}"
                        )

        # Unreachable banner
        if not drive.reachable:
            with ui.row().classes("w-full items-center gap-2 p-2 rounded mb-3").style(
                f"background: {COLORS.yellow}22; border: 1px solid {COLORS.yellow}"
            ):
                ui.icon("signal_wifi_off").style(f"color: {COLORS.yellow}")
                ui.label("Drive unreachable").style(f"color: {COLORS.yellow}")

        # Temperature
        with ui.row().classes("w-full items-center gap-3 mb-2"):
            ui.icon("thermostat").style(
                f"color: {_temp_color(health.composite_temperature_celsius)}"
            )
            ui.label("Temperature").classes("text-caption flex-1").style(
                f"color: {COLORS.text_secondary}"
            )
            ui.label(f"{health.composite_temperature_celsius}\u00b0C").classes(
                "text-subtitle2"
            ).style(
                f"color: {_temp_color(health.composite_temperature_celsius)}"
            )

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
            with ui.row().classes("w-full items-center gap-3 mb-2"):
                ui.icon("schedule").style(f"color: {COLORS.text_muted}")
                ui.label("Power-On Hours").classes("text-caption flex-1").style(
                    f"color: {COLORS.text_secondary}"
                )
                ui.label(f"{health.power_on_hours:,}").classes("text-caption").style(
                    f"color: {COLORS.text_primary}"
                )

        # Expand/collapse detail section
        detail_container = ui.column().classes("w-full")

        if expand_state.get(card_key, False):
            with detail_container:
                _drive_detail_section(drive)

        with ui.row().classes("w-full justify-center mt-2"):
            expand_icon = "expand_less" if expand_state.get(card_key, False) else "expand_more"
            expand_text = "Hide Details" if expand_state.get(card_key, False) else "Details"
            expand_btn = ui.button(expand_text, icon=expand_icon).props(
                "flat dense color=cyan size=sm"
            )

        def toggle_expand(
            _card_key=card_key, _drive=drive, _dc=detail_container, _btn=expand_btn
        ):
            is_expanded = expand_state.get(_card_key, False)
            expand_state[_card_key] = not is_expanded
            _dc.clear()
            if not is_expanded:
                with _dc:
                    _drive_detail_section(_drive)
            _btn.text = "Hide Details" if not is_expanded else "Details"
            _btn._props["icon"] = "expand_less" if not is_expanded else "expand_more"
            _btn.update()

        expand_btn.on_click(toggle_expand)


def _drive_detail_section(drive) -> None:
    """Render the expandable detail section for a drive card."""
    with ui.column().classes("w-full gap-3 mt-3 pt-3").style(
        f"border-top: 1px solid {COLORS.border}"
    ):
        # Full NQN
        if drive.subsystem.nqn:
            ui.label("NQN").classes("text-caption").style(
                f"color: {COLORS.text_muted}"
            )
            ui.label(drive.subsystem.nqn).classes("text-caption mono").style(
                f"color: {COLORS.text_primary}; word-break: break-all"
            )

        # Per-controller health table
        ui.label("Controller Health").classes("text-caption mt-2").style(
            f"color: {COLORS.text_muted}"
        )

        ctrl_container = ui.column().classes("w-full")

        async def fetch_controllers(
            _drive=drive, _container=ctrl_container
        ) -> None:
            from calypso.mctp.transport import MCTPOverI2C
            from calypso.mcu.bus import I2cBus
            from calypso.nvme_mi.client import NVMeMIClient

            current_port = app.storage.user.get("mcu_port")
            if not current_port:
                _container.clear()
                with _container:
                    ui.label("MCU disconnected").classes("text-caption").style(
                        f"color: {COLORS.red}"
                    )
                return

            _container.clear()
            with _container:
                ui.label("Fetching controller health...").classes(
                    "text-caption"
                ).style(f"color: {COLORS.cyan}")

            try:
                client = pool.get_client(current_port)
                bus = I2cBus(client, _drive.connector, _drive.channel)
                transport = MCTPOverI2C(bus)
                nvme = NVMeMIClient(transport)

                # NVMe-MI subsystem info exposes port count but not controller
                # count directly. We iterate port indices as a proxy; failures
                # are caught per-controller below.
                controllers = []
                for cid in range(_drive.subsystem.number_of_ports or 1):
                    try:
                        ch = await run.io_bound(
                            lambda _n=nvme, _c=cid, _d=_drive: _n.controller_health_poll(
                                controller_id=_c,
                                slave_addr=_d.slave_addr,
                                eid=_d.eid,
                            )
                        )
                        controllers.append(ch)
                    except Exception:
                        logger.debug(
                            "controller_health_poll_failed",
                            cid=cid,
                            drive=_drive.display_name,
                        )

                _container.clear()
                if not controllers:
                    with _container:
                        ui.label("No controller data available").classes(
                            "text-caption"
                        ).style(f"color: {COLORS.text_muted}")
                    return

                rows = [
                    {
                        "id": c.controller_id,
                        "temp": f"{c.composite_temperature_celsius}\u00b0C",
                        "spare": f"{c.available_spare_percent}%",
                        "used": f"{c.percentage_used}%",
                        "warning": f"0x{c.critical_warning:02X}" if c.critical_warning else "None",
                    }
                    for c in controllers
                ]
                with _container:
                    ui.table(
                        columns=_CONTROLLER_COLUMNS,
                        rows=rows,
                        row_key="id",
                    ).classes("w-full")

            except Exception as exc:
                _container.clear()
                with _container:
                    ui.label(f"Error: {str(exc)[:200]}").classes(
                        "text-caption"
                    ).style(f"color: {COLORS.red}")

        ui.button(
            "Load Controller Health",
            icon="download",
            on_click=fetch_controllers,
        ).props("flat dense color=cyan size=sm")


def nvme_drives_page() -> None:
    """Render the NVMe drives page."""
    page_layout("NVMe Drives", _nvme_drives_content)
