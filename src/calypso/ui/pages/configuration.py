"""Switch configuration page."""

from __future__ import annotations

import asyncio

from nicegui import ui

from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS


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
            from calypso.core.pcie_config import PcieConfigReader

            try:
                def _read_config():
                    reader = PcieConfigReader(device._device_obj, device._device_key)

                    config = {
                        "capabilities": [],
                        "ext_capabilities": [],
                        "device_caps": None,
                        "device_control": None,
                        "link_caps": None,
                        "link_status": None,
                        "supported_speeds": None,
                        "aer_status": None,
                        "header_regs": {},
                    }

                    # Read basic config space header
                    try:
                        config["header_regs"]["vendor_device"] = reader.read_config_register(0x00)
                        config["header_regs"]["status_command"] = reader.read_config_register(0x04)
                        config["header_regs"]["class_rev"] = reader.read_config_register(0x08)
                        config["header_regs"]["cap_pointer"] = reader.read_config_register(0x34)
                    except Exception:
                        pass

                    # Walk capabilities
                    try:
                        config["capabilities"] = reader.walk_capabilities()
                    except Exception:
                        pass

                    try:
                        config["ext_capabilities"] = reader.walk_extended_capabilities()
                    except Exception:
                        pass

                    # Try to read PCIe-specific data (may fail if no PCIe cap)
                    try:
                        config["device_caps"] = reader.get_device_capabilities()
                    except Exception:
                        pass

                    try:
                        config["device_control"] = reader.get_device_control()
                    except Exception:
                        pass

                    try:
                        config["link_caps"] = reader.get_link_capabilities()
                    except Exception:
                        pass

                    try:
                        config["link_status"] = reader.get_link_status()
                    except Exception:
                        pass

                    try:
                        config["supported_speeds"] = reader.get_supported_speeds()
                    except Exception:
                        pass

                    try:
                        config["aer_status"] = reader.get_aer_status()
                    except Exception:
                        pass

                    return config

                config = await asyncio.to_thread(_read_config)

                loading_container.visible = False
                config_container.visible = True
                config_container.clear()

                with config_container:
                    _render_config(config, device, device_id)

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


def _render_config(config: dict, device, device_id: str) -> None:
    """Render the configuration data."""
    device_caps = config.get("device_caps")
    device_control = config.get("device_control")
    link_caps = config.get("link_caps")
    link_status = config.get("link_status")
    supported_speeds = config.get("supported_speeds")
    aer_status = config.get("aer_status")
    capabilities = config.get("capabilities", [])
    ext_capabilities = config.get("ext_capabilities", [])
    header_regs = config.get("header_regs", {})

    # Device Info Card (always show this)
    with ui.card().classes("w-full p-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    ):
        ui.label("Device Information").classes("text-h6 mb-3").style(
            f"color: {COLORS.text_primary}"
        )

        device_info = device.device_info
        if device_info:
            with ui.row().classes("w-full gap-8"):
                with ui.column().classes("gap-2"):
                    _config_item("Chip", f"{device_info.chip_family.upper()} ({device_info.chip_id:#06x})")
                    bdf = f"{device_info.domain:04X}:{device_info.bus:02X}:{device_info.slot:02X}.{device_info.function}"
                    _config_item("Location", bdf)
                with ui.column().classes("gap-2"):
                    _config_item("Vendor ID", f"{device_info.vendor_id:#06x}")
                    _config_item("Device ID", f"{device_info.device_id:#06x}")
                with ui.column().classes("gap-2"):
                    _config_item("Revision", f"{device_info.chip_revision:#04x}")
                    _config_item("Port", str(device_info.port_number))

    # Capabilities Card
    if capabilities or ext_capabilities:
        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
        ):
            ui.label("PCI Capabilities").classes("text-h6 mb-3").style(
                f"color: {COLORS.text_primary}"
            )

            if capabilities:
                ui.label("Standard Capabilities:").style(
                    f"color: {COLORS.text_secondary}; font-weight: 600;"
                )
                with ui.row().classes("gap-2 flex-wrap mt-1 mb-3"):
                    for cap in capabilities:
                        ui.badge(f"{cap.cap_name} @ 0x{cap.offset:02X}").style(
                            f"background: {COLORS.blue};"
                        )

            if ext_capabilities:
                ui.label("Extended Capabilities:").style(
                    f"color: {COLORS.text_secondary}; font-weight: 600;"
                )
                with ui.row().classes("gap-2 flex-wrap mt-1"):
                    for cap in ext_capabilities:
                        ui.badge(f"{cap.cap_name} @ 0x{cap.offset:03X}").style(
                            f"background: {COLORS.purple};"
                        )

    # Check if PCIe capability data is available
    has_pcie_data = any([link_status, link_caps, device_control, device_caps])

    if not has_pcie_data:
        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.yellow}"
        ):
            with ui.row().classes("items-center gap-3"):
                ui.icon("info").style(f"color: {COLORS.yellow}; font-size: 1.5rem;")
                ui.label(
                    "PCIe capability registers not accessible via this connection. "
                    "Basic device information is shown above."
                ).style(f"color: {COLORS.text_secondary};")
        return

    # Link Status Card
    if link_status:
        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
        ):
            ui.label("Link Status").classes("text-h6 mb-3").style(
                f"color: {COLORS.text_primary}"
            )

            with ui.row().classes("w-full gap-8"):
                with ui.column().classes("gap-2"):
                    _config_item("Current Speed", link_status.current_speed, COLORS.green)
                    _config_item("Current Width", f"x{link_status.current_width}", COLORS.green)
                    _config_item("Target Speed", link_status.target_speed)
                with ui.column().classes("gap-2"):
                    _config_item("DLL Active", "Yes" if link_status.dll_link_active else "No",
                               COLORS.green if link_status.dll_link_active else COLORS.red)
                    _config_item("Link Training", "Yes" if link_status.link_training else "No")
                    _config_item("ASPM Control", link_status.aspm_control)

    # Link Capabilities Card
    if link_caps:
        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
        ):
            ui.label("Link Capabilities").classes("text-h6 mb-3").style(
                f"color: {COLORS.text_primary}"
            )

            with ui.row().classes("w-full gap-8"):
                with ui.column().classes("gap-2"):
                    _config_item("Max Link Speed", link_caps.max_link_speed)
                    _config_item("Max Link Width", f"x{link_caps.max_link_width}")
                    _config_item("Port Number", str(link_caps.port_number))
                with ui.column().classes("gap-2"):
                    _config_item("ASPM Support", link_caps.aspm_support)
                    _config_item("DLL Active Capable", "Yes" if link_caps.dll_link_active_capable else "No")
                    _config_item("Surprise Down", "Yes" if link_caps.surprise_down_capable else "No")

            # Supported speeds
            if supported_speeds:
                ui.label("Supported Speeds:").classes("mt-3").style(
                    f"color: {COLORS.text_secondary}; font-weight: 600;"
                )
                with ui.row().classes("gap-2 mt-1"):
                    speeds = [
                        ("Gen1", supported_speeds.gen1),
                        ("Gen2", supported_speeds.gen2),
                        ("Gen3", supported_speeds.gen3),
                        ("Gen4", supported_speeds.gen4),
                        ("Gen5", supported_speeds.gen5),
                        ("Gen6", supported_speeds.gen6),
                    ]
                    for name, supported in speeds:
                        color = COLORS.green if supported else COLORS.text_muted
                        with ui.badge(name).style(
                            f"background: {'transparent' if not supported else color}; "
                            f"color: {color}; border: 1px solid {color};"
                        ):
                            pass

    # Device Control Card (with controls)
    if device_control:
        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
        ):
            ui.label("Device Control").classes("text-h6 mb-3").style(
                f"color: {COLORS.text_primary}"
            )

            with ui.row().classes("w-full gap-8"):
                with ui.column().classes("gap-2"):
                    _config_item("Max Payload Size (MPS)", f"{device_control.max_payload_size} bytes")
                    _config_item("Max Read Request (MRRS)", f"{device_control.max_read_request_size} bytes")
                    _config_item("Relaxed Ordering", "Enabled" if device_control.relaxed_ordering else "Disabled")
                with ui.column().classes("gap-2"):
                    _config_item("No Snoop", "Enabled" if device_control.no_snoop else "Disabled")
                    _config_item("Extended Tag", "Enabled" if device_control.extended_tag_enabled else "Disabled")

            ui.separator().classes("my-3")

            ui.label("Error Reporting:").style(
                f"color: {COLORS.text_secondary}; font-weight: 600;"
            )
            with ui.row().classes("gap-4 mt-1"):
                _error_badge("Correctable", device_control.correctable_error_reporting)
                _error_badge("Non-Fatal", device_control.non_fatal_error_reporting)
                _error_badge("Fatal", device_control.fatal_error_reporting)
                _error_badge("Unsupported Req", device_control.unsupported_request_reporting)

    # Device Capabilities Card
    if device_caps:
        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
        ):
            ui.label("Device Capabilities").classes("text-h6 mb-3").style(
                f"color: {COLORS.text_primary}"
            )

            with ui.row().classes("w-full gap-8"):
                with ui.column().classes("gap-2"):
                    _config_item("Max Payload Supported", f"{device_caps.max_payload_supported} bytes")
                    _config_item("FLR Capable", "Yes" if device_caps.flr_capable else "No")
                with ui.column().classes("gap-2"):
                    _config_item("Extended Tag", "Supported" if device_caps.extended_tag_supported else "Not Supported")
                    _config_item("Role-Based Error Reporting", "Yes" if device_caps.role_based_error_reporting else "No")

    # AER Status Card
    if aer_status:
        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
        ):
            ui.label("Advanced Error Reporting (AER)").classes("text-h6 mb-3").style(
                f"color: {COLORS.text_primary}"
            )

            has_uncorr = aer_status.uncorrectable.raw_value != 0
            has_corr = aer_status.correctable.raw_value != 0

            if not has_uncorr and not has_corr:
                ui.label("No errors recorded").style(f"color: {COLORS.green}")
            else:
                if has_uncorr:
                    ui.label("Uncorrectable Errors:").style(
                        f"color: {COLORS.red}; font-weight: 600;"
                    )
                    with ui.row().classes("gap-2 flex-wrap mt-1 mb-2"):
                        uncorr = aer_status.uncorrectable
                        if uncorr.data_link_protocol:
                            ui.badge("DL Protocol").style(f"background: {COLORS.red}")
                        if uncorr.poisoned_tlp:
                            ui.badge("Poisoned TLP").style(f"background: {COLORS.red}")
                        if uncorr.completion_timeout:
                            ui.badge("Completion Timeout").style(f"background: {COLORS.red}")
                        if uncorr.unexpected_completion:
                            ui.badge("Unexpected Completion").style(f"background: {COLORS.red}")
                        if uncorr.malformed_tlp:
                            ui.badge("Malformed TLP").style(f"background: {COLORS.red}")
                        if uncorr.ecrc_error:
                            ui.badge("ECRC Error").style(f"background: {COLORS.red}")
                        if uncorr.unsupported_request:
                            ui.badge("Unsupported Request").style(f"background: {COLORS.red}")

                if has_corr:
                    ui.label("Correctable Errors:").style(
                        f"color: {COLORS.yellow}; font-weight: 600;"
                    )
                    with ui.row().classes("gap-2 flex-wrap mt-1"):
                        corr = aer_status.correctable
                        if corr.receiver_error:
                            ui.badge("Receiver Error").style(f"background: {COLORS.yellow}")
                        if corr.bad_tlp:
                            ui.badge("Bad TLP").style(f"background: {COLORS.yellow}")
                        if corr.bad_dllp:
                            ui.badge("Bad DLLP").style(f"background: {COLORS.yellow}")
                        if corr.replay_num_rollover:
                            ui.badge("Replay Rollover").style(f"background: {COLORS.yellow}")
                        if corr.replay_timer_timeout:
                            ui.badge("Replay Timeout").style(f"background: {COLORS.yellow}")


def _config_item(label: str, value: str, value_color: str | None = None) -> None:
    """Render a single configuration item."""
    with ui.row().classes("items-center gap-2"):
        ui.label(f"{label}:").style(f"color: {COLORS.text_secondary};")
        ui.label(value).style(
            f"color: {value_color or COLORS.text_primary}; font-weight: 600;"
        )


def _error_badge(label: str, enabled: bool) -> None:
    """Render an error reporting badge."""
    color = COLORS.green if enabled else COLORS.text_muted
    with ui.badge(label).style(
        f"background: transparent; color: {color}; border: 1px solid {color};"
    ):
        pass
