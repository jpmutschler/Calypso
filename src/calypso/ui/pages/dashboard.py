"""Switch dashboard page - overview of device status."""

from __future__ import annotations

from nicegui import ui

from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS


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
        # Get device info
        device_info = device.device_info
        if device_info is None:
            ui.label("Unable to retrieve device information.").style(
                f"color: {COLORS.red}"
            )
            return

        # Device info card
        with ui.row().classes("w-full gap-4"):
            with ui.card().classes("flex-1 p-4").style(
                f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
            ):
                ui.label("Device Info").classes("text-subtitle2 mb-2").style(
                    f"color: {COLORS.text_primary}"
                )

                with ui.column().classes("gap-2"):
                    # Chip info
                    ui.label(f"Chip: {device_info.chip_family.upper()} (ID: {device_info.chip_id:#06x})").style(
                        f"color: {COLORS.text_primary}; font-weight: 600;"
                    )

                    # BDF location
                    bdf = f"{device_info.domain:04X}:{device_info.bus:02X}:{device_info.slot:02X}.{device_info.function}"
                    ui.label(f"Location: {bdf}").style(
                        f"color: {COLORS.text_secondary}; font-size: 0.9rem;"
                    )

                    # Revision
                    ui.label(f"Revision: {device_info.chip_revision:#04x}").style(
                        f"color: {COLORS.text_secondary}; font-size: 0.9rem;"
                    )

                    # Vendor/Device ID
                    ui.label(f"Vendor ID: {device_info.vendor_id:#06x}").style(
                        f"color: {COLORS.text_secondary}; font-size: 0.9rem;"
                    )
                    ui.label(f"Device ID: {device_info.device_id:#06x}").style(
                        f"color: {COLORS.text_secondary}; font-size: 0.9rem;"
                    )

            # Driver info card
            with ui.card().classes("flex-1 p-4").style(
                f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
            ):
                ui.label("Driver Info").classes("text-subtitle2 mb-2").style(
                    f"color: {COLORS.text_primary}"
                )

                try:
                    driver_info = device.get_driver_info()
                    with ui.column().classes("gap-2"):
                        ui.label(f"Driver: {driver_info.name}").style(
                            f"color: {COLORS.text_primary}; font-weight: 600;"
                        )
                        ui.label(
                            f"Version: {driver_info.version_major}.{driver_info.version_minor}.{driver_info.version_revision}"
                        ).style(
                            f"color: {COLORS.text_secondary}; font-size: 0.9rem;"
                        )
                        service_type = "Service Driver" if driver_info.is_service_driver else "Standard Driver"
                        ui.label(f"Type: {service_type}").style(
                            f"color: {COLORS.text_secondary}; font-size: 0.9rem;"
                        )
                except Exception as e:
                    ui.label(f"Unable to get driver info: {e}").style(
                        f"color: {COLORS.text_muted}; font-size: 0.85rem;"
                    )

        # Chip features card
        with ui.card().classes("w-full p-4 mt-4").style(
            f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
        ):
            ui.label("Chip Features").classes("text-subtitle2 mb-2").style(
                f"color: {COLORS.text_primary}"
            )

            try:
                chip_features = device.get_chip_features()
                with ui.row().classes("gap-8"):
                    ui.label(f"Stations: {chip_features.station_count}").style(
                        f"color: {COLORS.text_secondary};"
                    )
                    ui.label(f"Ports per Station: {chip_features.ports_per_station}").style(
                        f"color: {COLORS.text_secondary};"
                    )
                    ui.label(f"Station Mask: {chip_features.station_mask:#x}").style(
                        f"color: {COLORS.text_secondary};"
                    )
            except Exception as e:
                ui.label(f"Unable to get chip features: {e}").style(
                    f"color: {COLORS.text_muted}; font-size: 0.85rem;"
                )

        # Quick links
        with ui.card().classes("w-full p-4 mt-4").style(
            f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
        ):
            ui.label("Quick Actions").classes("text-subtitle2 mb-2").style(
                f"color: {COLORS.text_primary}"
            )
            with ui.row().classes("gap-2"):
                ui.button(
                    "Port Status", icon="storage",
                    on_click=lambda: ui.navigate.to(f"/switch/{device_id}/ports")
                ).style(f"background: {COLORS.blue}")
                ui.button(
                    "Performance Monitor", icon="speed",
                    on_click=lambda: ui.navigate.to(f"/switch/{device_id}/performance")
                ).style(f"background: {COLORS.green}")
                ui.button(
                    "Error Overview", icon="error_outline",
                    on_click=lambda: ui.navigate.to(f"/switch/{device_id}/errors")
                ).style(f"background: {COLORS.yellow}")

    page_layout("Switch Dashboard", content, device_id=device_id)
