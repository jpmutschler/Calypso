"""Port status page."""

from __future__ import annotations

import asyncio

from nicegui import ui

from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS


def ports_page(device_id: str) -> None:
    """Render the port status page."""
    from calypso.api.app import get_device_registry

    registry = get_device_registry()
    device = registry.get(device_id)

    if device is None:
        def content():
            ui.label("Device not found. Please reconnect.").style(
                f"color: {COLORS.red}"
            )
        page_layout("Port Status", content, device_id=device_id)
        return

    def content():
        # Header with refresh button
        with ui.row().classes("w-full items-center mb-4"):
            ui.label("Upstream & Downstream Ports").classes("text-h5").style(
                f"color: {COLORS.text_primary}"
            )
            ui.space()
            refresh_btn = ui.button("Refresh", icon="refresh").style(
                f"background: {COLORS.blue}"
            )

        # Loading spinner
        spinner_container = ui.column().classes("w-full items-center justify-center py-8")
        with spinner_container:
            ui.spinner("dots", size="xl").style(f"color: {COLORS.cyan}")
            ui.label("Loading port data...").style(f"color: {COLORS.text_secondary}")

        # Port data container
        port_container = ui.column().classes("w-full gap-2")
        port_container.visible = False

        async def load_ports():
            """Fetch and display port data."""
            from calypso.core.port_manager import PortManager

            try:
                # Fetch port data in background thread
                def _get_ports():
                    pm = PortManager(device._device_obj, device._device_key)
                    return pm.get_all_port_statuses()

                ports = await asyncio.to_thread(_get_ports)

                # Hide spinner, show port data
                spinner_container.visible = False
                port_container.visible = True

                # Clear previous data
                port_container.clear()

                if not ports:
                    with port_container:
                        ui.label("No ports found.").style(f"color: {COLORS.text_muted}")
                    return

                # Filter to only Upstream and Downstream ports
                from calypso.models.port import PortRole
                filtered_ports = [
                    p for p in ports
                    if p.role in (PortRole.UPSTREAM, PortRole.DOWNSTREAM)
                ]

                if not filtered_ports:
                    with port_container:
                        ui.label("No upstream or downstream ports found.").style(
                            f"color: {COLORS.text_muted}"
                        )
                    return

                # Group ports by role for better organization
                role_groups: dict[str, list] = {}
                for port in filtered_ports:
                    role_name = port.role.value.replace("_", " ").title()
                    if role_name not in role_groups:
                        role_groups[role_name] = []
                    role_groups[role_name].append(port)

                # Display ports grouped by role (Upstream first, then Downstream)
                role_order = ["Upstream", "Downstream"]
                with port_container:
                    for role_name in role_order:
                        if role_name not in role_groups:
                            continue
                        role_ports = role_groups[role_name]

                        # Role section header
                        ui.label(f"{role_name} Ports ({len(role_ports)})").classes(
                            "text-subtitle1 mt-4 mb-2"
                        ).style(f"color: {COLORS.cyan}")

                        # Port grid
                        with ui.grid(columns="repeat(auto-fill, minmax(300px, 1fr))").classes("w-full gap-3"):
                            for port in role_ports:
                                _render_port_card(port)

            except Exception as e:
                spinner_container.visible = False
                port_container.visible = True
                port_container.clear()
                with port_container:
                    with ui.card().classes("w-full p-4").style(
                        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.red}"
                    ):
                        ui.label(f"Error loading ports: {e}").style(f"color: {COLORS.red}")

        def _render_port_card(port):
            """Render a single port status card."""
            # Determine status color
            if port.is_link_up:
                status_color = COLORS.green
                status_icon = "link"
                status_text = "Link Up"
            else:
                status_color = COLORS.text_muted
                status_icon = "link_off"
                status_text = "Link Down"

            with ui.card().classes("p-3").style(
                f"background: {COLORS.bg_card}; border: 1px solid {COLORS.border}"
            ):
                with ui.row().classes("w-full items-center mb-2"):
                    ui.icon(status_icon).style(f"color: {status_color}; font-size: 1.5rem;")
                    ui.label(f"Port {port.port_number}").classes("text-subtitle2").style(
                        f"color: {COLORS.text_primary}; font-weight: 600;"
                    )
                    ui.space()
                    ui.label(status_text).style(
                        f"color: {status_color}; font-size: 0.85rem; font-weight: 600;"
                    )

                with ui.column().classes("gap-1"):
                    if port.is_link_up:
                        # Link speed
                        speed_text = port.link_speed.value.replace("_", " ").upper()
                        ui.label(f"Speed: {speed_text}").style(
                            f"color: {COLORS.text_secondary}; font-size: 0.85rem;"
                        )

                        # Link width
                        ui.label(f"Width: x{port.link_width}").style(
                            f"color: {COLORS.text_secondary}; font-size: 0.85rem;"
                        )

                        # Max payload size
                        ui.label(f"MPS: {port.max_payload_size} bytes").style(
                            f"color: {COLORS.text_secondary}; font-size: 0.85rem;"
                        )
                    else:
                        ui.label("No link detected").style(
                            f"color: {COLORS.text_muted}; font-size: 0.85rem;"
                        )

        # Initial load
        ui.timer(0.1, load_ports, once=True)

        # Refresh button handler
        refresh_btn.on_click(lambda: (
            spinner_container.set_visibility(True),
            port_container.set_visibility(False),
            ui.timer(0.1, load_ports, once=True)
        ))

    page_layout("Port Status", content, device_id=device_id)
