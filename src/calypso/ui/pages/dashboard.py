"""Switch dashboard page - overview of device status."""

from __future__ import annotations

import asyncio

from nicegui import ui

from calypso.ui.components.common import SWITCH_MODE_NAMES, kv_pair
from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS
from calypso.utils.logging import get_logger

logger = get_logger(__name__)


def dashboard_page(device_id: str) -> None:
    """Render the switch dashboard page."""
    from calypso.api.app import get_device_registry

    registry = get_device_registry()
    device = registry.get(device_id)

    if device is None:
        def content():
            ui.label("Device not found. Please reconnect.").style(
                f"color: {COLORS.red}"
            )
        page_layout("Switch Dashboard", content, device_id=device_id)
        return

    def content():
        # Loading state
        loading_container = ui.column().classes("w-full items-center py-8")
        with loading_container:
            ui.spinner("dots", size="xl").style(f"color: {COLORS.cyan}")
            ui.label("Loading dashboard...").style(f"color: {COLORS.text_secondary}")

        # Content container
        dashboard_container = ui.column().classes("w-full gap-4")
        dashboard_container.visible = False

        async def load_dashboard():
            try:
                data = await asyncio.to_thread(_collect_dashboard_data, device)

                loading_container.visible = False
                dashboard_container.visible = True
                dashboard_container.clear()

                with dashboard_container:
                    _render_dashboard(data, device_id)

            except Exception as e:
                loading_container.visible = False
                dashboard_container.visible = True
                dashboard_container.clear()
                with dashboard_container:
                    ui.label(f"Error loading dashboard: {e}").style(
                        f"color: {COLORS.red}"
                    )

        ui.timer(0.1, load_dashboard, once=True)

    page_layout("Switch Dashboard", content, device_id=device_id)


def _collect_dashboard_data(device) -> dict:
    """Collect all dashboard data in a background thread (SDK calls are blocking)."""
    from calypso.core.eeprom_manager import EepromManager
    from calypso.core.port_manager import PortManager
    from calypso.sdk import device as sdk_device
    from calypso.sdk import multi_host

    data: dict = {
        "device_info": device.device_info,
        "port_status": None,
        "driver_info": None,
        "api_version": None,
        "chip_features": None,
        "all_ports": None,
        "multi_host": None,
        "eeprom_info": None,
    }

    try:
        data["port_status"] = device.get_port_status()
    except Exception as exc:
        logger.warning("dashboard_port_status_failed", error=str(exc))

    try:
        data["driver_info"] = device.get_driver_info()
    except Exception as exc:
        logger.warning("dashboard_driver_info_failed", error=str(exc))

    try:
        data["api_version"] = sdk_device.get_api_version()
    except Exception as exc:
        logger.warning("dashboard_api_version_failed", error=str(exc))

    try:
        data["chip_features"] = device.get_chip_features()
    except Exception as exc:
        logger.warning("dashboard_chip_features_failed", error=str(exc))

    try:
        pm = PortManager(device._device_obj, device._device_key)
        data["all_ports"] = pm.get_all_port_statuses()
    except Exception as exc:
        logger.warning("dashboard_port_summary_failed", error=str(exc))

    try:
        data["multi_host"] = multi_host.get_properties(device._device_obj)
    except Exception as exc:
        logger.warning("dashboard_multi_host_failed", error=str(exc))

    try:
        em = EepromManager(device._device_obj)
        data["eeprom_info"] = em.get_info()
    except Exception as exc:
        logger.warning("dashboard_eeprom_failed", error=str(exc))

    return data


def _render_dashboard(data: dict, device_id: str) -> None:
    """Render all dashboard sections."""
    device_info = data["device_info"]

    if device_info is None:
        ui.label("Unable to retrieve device information.").style(
            f"color: {COLORS.red}"
        )
        return

    # Row 1: Device Identity + Driver/API + Upstream Port
    with ui.row().classes("w-full gap-4"):
        _render_device_identity(device_info)
        _render_driver_info(data["driver_info"], data["api_version"])
        _render_upstream_port(data["port_status"])

    # Row 2: Port Summary + Multi-Host + EEPROM
    with ui.row().classes("w-full gap-4"):
        _render_port_summary(data["all_ports"])
        _render_multi_host(data["multi_host"])
        _render_eeprom_status(data["eeprom_info"])

    # Row 3: Chip Layout
    _render_chip_layout(data["chip_features"])

    # Row 4: Quick Actions
    _render_quick_actions(device_id)


def _render_device_identity(device_info) -> None:
    """Render device identity card."""
    with ui.card().classes("flex-1 p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    ):
        ui.label("Device Identity").classes("text-subtitle2 mb-2").style(
            f"color: {COLORS.cyan}"
        )
        with ui.column().classes("gap-1"):
            ui.label(
                f"{device_info.chip_family.upper()}"
            ).style(f"color: {COLORS.text_primary}; font-weight: 600; font-size: 1.1rem;")

            bdf = (
                f"{device_info.domain:04X}:{device_info.bus:02X}"
                f":{device_info.slot:02X}.{device_info.function}"
            )
            kv_pair("BDF", bdf)
            kv_pair("Chip ID", f"{device_info.chip_id:#06x}")
            kv_pair("Vendor ID", f"{device_info.vendor_id:#06x}")
            kv_pair("Device ID", f"{device_info.device_id:#06x}")
            kv_pair("Revision", f"{device_info.chip_revision:#04x}")
            kv_pair("Port", str(device_info.port_number))


def _render_driver_info(driver_info, api_version) -> None:
    """Render driver and API version card."""
    with ui.card().classes("flex-1 p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    ):
        ui.label("Driver & API").classes("text-subtitle2 mb-2").style(
            f"color: {COLORS.cyan}"
        )
        with ui.column().classes("gap-1"):
            if driver_info:
                kv_pair("Driver", driver_info.name)
                kv_pair(
                    "Version",
                    f"{driver_info.version_major}.{driver_info.version_minor}"
                    f".{driver_info.version_revision}",
                )
                service_type = "Service" if driver_info.is_service_driver else "Standard"
                kv_pair("Type", service_type)
            else:
                ui.label("Driver info unavailable").style(
                    f"color: {COLORS.text_muted}; font-size: 0.85rem;"
                )

            if api_version:
                major, minor, rev = api_version
                kv_pair("API Version", f"{major}.{minor}.{rev}")
            else:
                ui.label("API version unavailable").style(
                    f"color: {COLORS.text_muted}; font-size: 0.85rem;"
                )


def _render_upstream_port(port_status) -> None:
    """Render upstream port link status card."""
    with ui.card().classes("flex-1 p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    ):
        ui.label("Upstream Port").classes("text-subtitle2 mb-2").style(
            f"color: {COLORS.cyan}"
        )
        with ui.column().classes("gap-1"):
            if port_status is None:
                ui.label("Port status unavailable").style(
                    f"color: {COLORS.text_muted}; font-size: 0.85rem;"
                )
                return

            if port_status.is_link_up:
                with ui.row().classes("items-center gap-2"):
                    ui.icon("link").style(f"color: {COLORS.green}; font-size: 1.3rem;")
                    ui.label("Link Up").style(
                        f"color: {COLORS.green}; font-weight: 600;"
                    )
                speed_text = port_status.link_speed.value.replace("_", " ").upper()
                kv_pair("Speed", speed_text)
                kv_pair("Width", f"x{port_status.link_width}")
                kv_pair("MPS", f"{port_status.max_payload_size} bytes")
            else:
                with ui.row().classes("items-center gap-2"):
                    ui.icon("link_off").style(
                        f"color: {COLORS.text_muted}; font-size: 1.3rem;"
                    )
                    ui.label("Link Down").style(
                        f"color: {COLORS.text_muted}; font-weight: 600;"
                    )


def _render_port_summary(all_ports) -> None:
    """Render port summary card with link up/down counts and speed breakdown."""
    with ui.card().classes("flex-1 p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    ):
        ui.label("Port Summary").classes("text-subtitle2 mb-2").style(
            f"color: {COLORS.cyan}"
        )
        with ui.column().classes("gap-1"):
            if all_ports is None:
                ui.label("Port data unavailable").style(
                    f"color: {COLORS.text_muted}; font-size: 0.85rem;"
                )
                return

            from calypso.models.port import PortRole

            # Filter to upstream + downstream
            relevant = [
                p for p in all_ports
                if p.role in (PortRole.UPSTREAM, PortRole.DOWNSTREAM)
            ]
            total = len(relevant)
            links_up = sum(1 for p in relevant if p.is_link_up)
            links_down = total - links_up

            up_color = COLORS.green if links_up > 0 else COLORS.text_muted
            down_color = COLORS.red if links_down > 0 else COLORS.text_muted

            with ui.row().classes("items-center gap-4"):
                with ui.row().classes("items-center gap-1"):
                    ui.icon("link").style(f"color: {up_color}; font-size: 1.2rem;")
                    ui.label(f"{links_up} up").style(
                        f"color: {up_color}; font-weight: 600;"
                    )
                with ui.row().classes("items-center gap-1"):
                    ui.icon("link_off").style(f"color: {down_color}; font-size: 1.2rem;")
                    ui.label(f"{links_down} down").style(
                        f"color: {down_color}; font-weight: 600;"
                    )
                ui.label(f"/ {total} total").style(
                    f"color: {COLORS.text_secondary}; font-size: 0.85rem;"
                )

            # Speed breakdown for links that are up
            speed_counts: dict[str, int] = {}
            for p in relevant:
                if p.is_link_up:
                    speed_label = p.link_speed.value.replace("_", " ")
                    key = f"{speed_label} x{p.link_width}"
                    speed_counts[key] = speed_counts.get(key, 0) + 1

            if speed_counts:
                ui.separator().classes("my-1")
                for speed, count in sorted(speed_counts.items()):
                    ui.label(f"{count}x {speed}").style(
                        f"color: {COLORS.text_secondary}; font-size: 0.85rem;"
                    )


def _render_multi_host(mh_props) -> None:
    """Render multi-host overview card."""
    with ui.card().classes("flex-1 p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    ):
        ui.label("Multi-Host").classes("text-subtitle2 mb-2").style(
            f"color: {COLORS.cyan}"
        )
        with ui.column().classes("gap-1"):
            if mh_props is None:
                ui.label("Multi-host data unavailable").style(
                    f"color: {COLORS.text_muted}; font-size: 0.85rem;"
                )
                return

            mode = mh_props.SwitchMode
            mode_name = SWITCH_MODE_NAMES.get(mode, f"Unknown ({mode})")
            kv_pair("Switch Mode", mode_name)

            # Count active virtual switches
            vs_mask = mh_props.VS_EnabledMask
            vs_count = bin(vs_mask).count("1")
            kv_pair("Active VS", str(vs_count))

            if mh_props.bIsMgmtPort:
                kv_pair("Mgmt Port", str(mh_props.MgmtPortNumActive))


def _render_eeprom_status(eeprom_info) -> None:
    """Render EEPROM status card."""
    with ui.card().classes("flex-1 p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    ):
        ui.label("EEPROM").classes("text-subtitle2 mb-2").style(
            f"color: {COLORS.cyan}"
        )
        with ui.column().classes("gap-1"):
            if eeprom_info is None:
                ui.label("EEPROM data unavailable").style(
                    f"color: {COLORS.text_muted}; font-size: 0.85rem;"
                )
                return

            present_color = COLORS.green if eeprom_info.present else COLORS.red
            kv_pair("Present", "Yes" if eeprom_info.present else "No", present_color)
            kv_pair("Status", eeprom_info.status.title())

            if eeprom_info.present:
                crc_color = COLORS.green if eeprom_info.crc_status == "valid" else COLORS.yellow
                kv_pair("CRC", eeprom_info.crc_status.title(), crc_color)
                if eeprom_info.crc_value:
                    kv_pair("CRC Value", f"{eeprom_info.crc_value:#010x}")


def _render_chip_layout(chip_features) -> None:
    """Render chip layout card with station/port info."""
    with ui.card().classes("w-full p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    ):
        ui.label("Chip Layout").classes("text-subtitle2 mb-2").style(
            f"color: {COLORS.cyan}"
        )
        if chip_features is None:
            ui.label("Chip features unavailable").style(
                f"color: {COLORS.text_muted}; font-size: 0.85rem;"
            )
            return

        with ui.row().classes("gap-8"):
            kv_pair("Stations", str(chip_features.station_count))
            kv_pair("Ports/Station", str(chip_features.ports_per_station))
            kv_pair("Station Mask", f"{chip_features.station_mask:#06x}")

        # Show port mask per DWORD (each covers 32 ports).  PortMask is indexed
        # by port_number/32, NOT by station index.
        if chip_features.port_mask:
            ui.separator().classes("my-2")
            ui.label("Port Mask").style(
                f"color: {COLORS.text_secondary}; font-size: 0.85rem; font-weight: 600;"
            )
            with ui.row().classes("gap-4 flex-wrap mt-1"):
                for dw_idx, mask in enumerate(chip_features.port_mask):
                    if mask == 0:
                        continue
                    port_lo = dw_idx * 32
                    port_hi = port_lo + 31
                    port_count = bin(mask).count("1")
                    ui.badge(
                        f"Ports {port_lo}-{port_hi}: {port_count} active ({mask:#010x})"
                    ).style(f"background: {COLORS.bg_elevated}; color: {COLORS.cyan};")


def _render_quick_actions(device_id: str) -> None:
    """Render quick action navigation buttons."""
    with ui.card().classes("w-full p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    ):
        ui.label("Quick Actions").classes("text-subtitle2 mb-2").style(
            f"color: {COLORS.cyan}"
        )
        with ui.row().classes("gap-2 flex-wrap"):
            ui.button(
                "Ports", icon="storage",
                on_click=lambda: ui.navigate.to(f"/switch/{device_id}/ports"),
            ).style(f"background: {COLORS.blue}")
            ui.button(
                "Performance", icon="speed",
                on_click=lambda: ui.navigate.to(f"/switch/{device_id}/performance"),
            ).style(f"background: {COLORS.green}")
            ui.button(
                "Configuration", icon="settings",
                on_click=lambda: ui.navigate.to(f"/switch/{device_id}/configuration"),
            ).style(f"background: {COLORS.purple}")
            ui.button(
                "Topology", icon="account_tree",
                on_click=lambda: ui.navigate.to(f"/switch/{device_id}/topology"),
            ).style(f"background: {COLORS.orange}")
            ui.button(
                "PCIe Registers", icon="memory",
                on_click=lambda: ui.navigate.to(f"/switch/{device_id}/registers"),
            ).style(f"background: {COLORS.cyan_dim}")
            ui.button(
                "EEPROM", icon="sd_storage",
                on_click=lambda: ui.navigate.to(f"/switch/{device_id}/eeprom"),
            ).style(f"background: {COLORS.yellow}")


