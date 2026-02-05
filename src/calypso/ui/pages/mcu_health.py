"""MCU health monitoring page - thermal, fan, voltage, and power status."""

from __future__ import annotations

from nicegui import app, run, ui

from calypso.mcu import pool
from calypso.ui.components.mcu_common import (
    no_mcu_message,
    page_header,
    set_status_error,
    set_status_live,
    stat_card,
    status_indicator,
)
from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS


def _temp_color(celsius: float) -> str:
    """Return color based on temperature threshold."""
    if celsius < 60:
        return COLORS["accent_green"]
    if celsius < 80:
        return COLORS["accent_yellow"]
    return COLORS["accent_red"]


def mcu_health_page() -> None:
    """Render the MCU health monitoring page."""

    def content():
        mcu_port = app.storage.user.get("mcu_port")
        if not mcu_port:
            no_mcu_message()
            return

        page_header("Health Monitoring", f"MCU: {mcu_port}")

        # Temperature and Fan
        with ui.row().classes("w-full gap-4 flex-wrap"):
            temp_label = stat_card("Temperature", "thermostat")
            fan_label = stat_card("Fan Speed", "air")

        # Voltage rails
        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS['bg_secondary']}; "
            f"border: 1px solid {COLORS['border']}"
        ):
            with ui.row().classes("items-center gap-2 mb-3"):
                ui.icon("bolt").classes("text-lg").style(
                    f"color: {COLORS['accent_blue']}"
                )
                ui.label("Voltage Rails").classes("text-subtitle2").style(
                    f"color: {COLORS['text_primary']}"
                )
            with ui.row().classes("w-full gap-6 flex-wrap"):
                v_labels: dict[str, ui.label] = {}
                for name in ["1V5", "VDD", "VDDA", "VDDA12"]:
                    with ui.column().classes("items-center min-w-[100px]"):
                        ui.label(name).classes("text-caption").style(
                            f"color: {COLORS['text_muted']}"
                        )
                        v_labels[name] = ui.label("-- V").classes("text-h6").style(
                            f"color: {COLORS['text_primary']}"
                        )

        # Power consumption
        with ui.card().classes("w-full p-4").style(
            f"background: {COLORS['bg_secondary']}; "
            f"border: 1px solid {COLORS['border']}"
        ):
            with ui.row().classes("items-center gap-2 mb-3"):
                ui.icon("power").classes("text-lg").style(
                    f"color: {COLORS['accent_blue']}"
                )
                ui.label("Power Consumption").classes("text-subtitle2").style(
                    f"color: {COLORS['text_primary']}"
                )
            with ui.row().classes("w-full gap-6 flex-wrap"):
                pwr_items: dict[str, ui.label] = {}
                for name, unit in [("Voltage", "V"), ("Current", "A"), ("Power", "W")]:
                    with ui.column().classes("items-center min-w-[100px]"):
                        ui.label(name).classes("text-caption").style(
                            f"color: {COLORS['text_muted']}"
                        )
                        pwr_items[name] = ui.label(f"-- {unit}").classes("text-h6").style(
                            f"color: {COLORS['text_primary']}"
                        )

        status = status_indicator()

        async def refresh():
            current_port = app.storage.user.get("mcu_port")
            if not current_port:
                set_status_error(status, Exception("MCU disconnected"))
                return
            try:
                s = await run.io_bound(
                    lambda: pool.get_client(current_port).get_thermal_status()
                )

                temp_c = s.thermal.switch_temperature_celsius
                temp_label.text = f"{temp_c:.1f}\u00b0C"
                temp_label.style(f"color: {_temp_color(temp_c)}")

                fan_label.text = f"{s.fan.switch_fan_rpm} RPM"

                v_labels["1V5"].text = f"{s.voltages.voltage_1v5:.3f} V"
                v_labels["VDD"].text = f"{s.voltages.voltage_vdd:.3f} V"
                v_labels["VDDA"].text = f"{s.voltages.voltage_vdda:.3f} V"
                v_labels["VDDA12"].text = f"{s.voltages.voltage_vdda12:.3f} V"

                pwr_items["Voltage"].text = f"{s.power.power_voltage:.2f} V"
                pwr_items["Current"].text = f"{s.power.load_current:.2f} A"
                pwr_items["Power"].text = f"{s.power.load_power:.2f} W"

                set_status_live(status)
            except Exception as exc:
                set_status_error(status, exc)

        ui.timer(2.0, refresh)

    page_layout("MCU Health", content)
