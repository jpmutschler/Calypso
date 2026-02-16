"""Switch configuration page - multi-host mode, virtual switches, port mapping."""

from __future__ import annotations

import asyncio

from nicegui import ui

from calypso.ui.components.common import SWITCH_MODE_NAMES, bitmask_to_ports, kv_pair
from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS
from calypso.utils.logging import get_logger

logger = get_logger(__name__)


def configuration_page(device_id: str) -> None:
    """Render the switch configuration page."""
    from calypso.api.app import get_device_registry

    registry = get_device_registry()
    device = registry.get(device_id)

    if device is None:
        def content():
            ui.label("Device not found. Please reconnect.").style(
                f"color: {COLORS.red}"
            )
        page_layout("Switch Configuration", content, device_id=device_id)
        return

    def content():
        # Loading state
        loading_container = ui.column().classes("w-full items-center py-8")
        with loading_container:
            ui.spinner("dots", size="xl").style(f"color: {COLORS.cyan}")
            ui.label("Loading configuration...").style(f"color: {COLORS.text_secondary}")

        # Content container
        config_container = ui.column().classes("w-full gap-4")
        config_container.visible = False

        async def load_config():
            try:
                data = await asyncio.to_thread(_collect_config_data, device)

                loading_container.visible = False
                config_container.visible = True
                config_container.clear()

                with config_container:
                    _render_config(data)

            except Exception as e:
                loading_container.visible = False
                config_container.visible = True
                config_container.clear()
                with config_container:
                    ui.label(f"Error loading configuration: {e}").style(
                        f"color: {COLORS.red}"
                    )

        ui.timer(0.1, load_config, once=True)

    page_layout("Switch Configuration", content, device_id=device_id)


def _collect_config_data(device) -> dict:
    """Collect all switch configuration data in a background thread."""
    from calypso.sdk import multi_host

    data: dict = {
        "device_info": device.device_info,
        "multi_host": None,
        "port_properties": None,
        "chip_features": None,
    }

    try:
        data["multi_host"] = multi_host.get_properties(device._device_obj)
    except Exception as exc:
        logger.warning("config_multi_host_failed", error=str(exc))

    try:
        data["port_properties"] = device.get_port_properties()
    except Exception as exc:
        logger.warning("config_port_properties_failed", error=str(exc))

    try:
        data["chip_features"] = device.get_chip_features()
    except Exception as exc:
        logger.warning("config_chip_features_failed", error=str(exc))

    return data


def _render_config(data: dict) -> None:
    """Render all configuration sections."""
    device_info = data["device_info"]
    mh_props = data["multi_host"]
    port_props = data["port_properties"]
    chip_features = data["chip_features"]

    # Switch Mode card
    _render_switch_mode(mh_props)

    # Virtual Switches card
    _render_virtual_switches(mh_props)

    # Management Port card
    _render_management_port(mh_props)

    # Current Port Properties card
    _render_port_properties(port_props, device_info)

    # Chip Port Map card
    _render_chip_port_map(chip_features)


def _render_switch_mode(mh_props) -> None:
    """Render switch mode card."""
    with ui.card().classes("w-full p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    ):
        ui.label("Switch Mode").classes("text-h6 mb-3").style(
            f"color: {COLORS.text_primary}"
        )

        if mh_props is None:
            ui.label("Multi-host properties unavailable.").style(
                f"color: {COLORS.text_muted}; font-size: 0.85rem;"
            )
            return

        mode = mh_props.SwitchMode
        mode_name = SWITCH_MODE_NAMES.get(mode, f"Unknown ({mode})")

        with ui.row().classes("items-center gap-4"):
            ui.icon("settings_ethernet").style(
                f"color: {COLORS.cyan}; font-size: 2rem;"
            )
            with ui.column().classes("gap-1"):
                ui.label(mode_name).style(
                    f"color: {COLORS.text_primary}; font-weight: 600; font-size: 1.2rem;"
                )
                ui.label(f"Mode value: {mode}").style(
                    f"color: {COLORS.text_muted}; font-size: 0.8rem;"
                )


def _render_virtual_switches(mh_props) -> None:
    """Render virtual switch configuration table."""
    with ui.card().classes("w-full p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    ):
        ui.label("Virtual Switches").classes("text-h6 mb-3").style(
            f"color: {COLORS.text_primary}"
        )

        if mh_props is None:
            ui.label("Virtual switch data unavailable.").style(
                f"color: {COLORS.text_muted}; font-size: 0.85rem;"
            )
            return

        vs_mask = mh_props.VS_EnabledMask
        if vs_mask == 0:
            ui.label("No virtual switches enabled (standard single-host mode).").style(
                f"color: {COLORS.text_secondary};"
            )
            return

        kv_pair("Enabled Mask", f"{vs_mask:#06x}")

        # Build table rows for each enabled VS
        rows = []
        for vs_idx in range(8):
            if not (vs_mask & (1 << vs_idx)):
                continue

            upstream_port = mh_props.VS_UpstreamPortNum[vs_idx]
            ds_mask = mh_props.VS_DownstreamPorts[vs_idx]
            ds_ports = bitmask_to_ports(ds_mask)
            ds_text = ", ".join(str(p) for p in ds_ports) if ds_ports else "None"

            rows.append({
                "vs": vs_idx,
                "upstream": upstream_port,
                "downstream": ds_text,
                "ds_count": len(ds_ports),
            })

        if rows:
            columns = [
                {"name": "vs", "label": "VS Index", "field": "vs", "align": "center"},
                {"name": "upstream", "label": "Upstream Port", "field": "upstream", "align": "center"},
                {"name": "ds_count", "label": "DS Ports", "field": "ds_count", "align": "center"},
                {"name": "downstream", "label": "Downstream Port List", "field": "downstream"},
            ]
            ui.table(columns=columns, rows=rows).classes("w-full mt-2").style(
                f"background: {COLORS.bg_card};"
            )


def _render_management_port(mh_props) -> None:
    """Render management port configuration card."""
    with ui.card().classes("w-full p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    ):
        ui.label("Management Port").classes("text-h6 mb-3").style(
            f"color: {COLORS.text_primary}"
        )

        if mh_props is None:
            ui.label("Management port data unavailable.").style(
                f"color: {COLORS.text_muted}; font-size: 0.85rem;"
            )
            return

        is_mgmt = bool(mh_props.bIsMgmtPort)
        mgmt_color = COLORS.green if is_mgmt else COLORS.text_muted

        with ui.row().classes("gap-8"):
            with ui.column().classes("gap-1"):
                kv_pair("Is Management Port", "Yes" if is_mgmt else "No", mgmt_color)

                active_en = bool(mh_props.bMgmtPortActiveEn)
                kv_pair("Active Enabled", "Yes" if active_en else "No")
                if active_en:
                    kv_pair("Active Port", str(mh_props.MgmtPortNumActive))

            with ui.column().classes("gap-1"):
                redundant_en = bool(mh_props.bMgmtPortRedundantEn)
                kv_pair("Redundant Enabled", "Yes" if redundant_en else "No")
                if redundant_en:
                    kv_pair("Redundant Port", str(mh_props.MgmtPortNumRedundant))


def _render_port_properties(port_props, device_info) -> None:
    """Render current port properties card."""
    with ui.card().classes("w-full p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    ):
        port_label = ""
        if device_info:
            port_label = f" (Port {device_info.port_number})"
        ui.label(f"Current Port Properties{port_label}").classes("text-h6 mb-3").style(
            f"color: {COLORS.text_primary}"
        )

        if port_props is None:
            ui.label("Port properties unavailable.").style(
                f"color: {COLORS.text_muted}; font-size: 0.85rem;"
            )
            return

        with ui.row().classes("w-full gap-8"):
            with ui.column().classes("gap-1"):
                kv_pair("Port Number", str(port_props.port_number))
                kv_pair("Port Type", f"{port_props.port_type}")
                pcie_color = COLORS.green if port_props.is_pcie else COLORS.text_muted
                kv_pair("PCIe Device", "Yes" if port_props.is_pcie else "No", pcie_color)

            with ui.column().classes("gap-1"):
                speed_text = port_props.max_link_speed.value.replace("_", " ").upper()
                kv_pair("Max Link Speed", speed_text)
                kv_pair("Max Link Width", f"x{port_props.max_link_width}")

            with ui.column().classes("gap-1"):
                kv_pair("Max Read Request", f"{port_props.max_read_req_size} bytes")
                kv_pair("Max Payload Supported", f"{port_props.max_payload_supported} bytes")


def _render_chip_port_map(chip_features) -> None:
    """Render chip port map with station visualization."""
    with ui.card().classes("w-full p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    ):
        ui.label("Chip Port Map").classes("text-h6 mb-3").style(
            f"color: {COLORS.text_primary}"
        )

        if chip_features is None:
            ui.label("Chip features unavailable.").style(
                f"color: {COLORS.text_muted}; font-size: 0.85rem;"
            )
            return

        with ui.row().classes("gap-8 mb-3"):
            kv_pair("Stations", str(chip_features.station_count))
            kv_pair("Ports per Station", str(chip_features.ports_per_station))
            kv_pair("Station Mask", f"{chip_features.station_mask:#06x}")

        if not chip_features.port_mask:
            return

        # Visual grid of stations and their ports
        for stn_idx in range(chip_features.station_count):
            if stn_idx >= len(chip_features.port_mask):
                break

            mask = chip_features.port_mask[stn_idx]
            ports = bitmask_to_ports(mask)
            port_count = len(ports)

            with ui.expansion(
                f"Station {stn_idx} — {port_count} ports",
                icon="developer_board",
            ).classes("w-full").style(
                f"background: {COLORS.bg_card}; color: {COLORS.text_primary};"
            ):
                if not ports:
                    ui.label("No ports in this station").style(
                        f"color: {COLORS.text_muted}; font-size: 0.85rem;"
                    )
                else:
                    with ui.row().classes("gap-2 flex-wrap"):
                        for port_num in ports:
                            ui.badge(f"P{port_num}").style(
                                f"background: {COLORS.bg_elevated}; color: {COLORS.cyan};"
                            )
                    ui.label(f"Port mask: {mask:#010x}").style(
                        f"color: {COLORS.text_muted}; font-size: 0.8rem; margin-top: 4px;"
                    )


