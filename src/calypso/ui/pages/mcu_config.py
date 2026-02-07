"""MCU configuration page - mode, clock, spread, FLIT, SDB settings."""

from __future__ import annotations

from nicegui import app, run, ui

from calypso.mcu import pool
from calypso.ui.components.mcu_common import (
    card_header,
    card_style,
    no_mcu_message,
    page_header,
    set_status_error,
    set_status_live,
    status_indicator,
    update_badge,
)
from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS


def mcu_config_page() -> None:
    """Render the MCU configuration page."""

    def content():
        mcu_port = app.storage.user.get("mcu_port")
        if not mcu_port:
            no_mcu_message()
            return

        page_header("Configuration", f"MCU: {mcu_port}")

        # Operation Mode
        with ui.card().classes("w-full p-4").style(card_style()):
            card_header("Operation Mode", "tune")
            with ui.row().classes("items-end gap-4"):
                mode_select = ui.select(
                    {1: "Mode 1", 2: "Mode 2", 3: "Mode 3", 4: "Mode 4"},
                    value=1,
                    label="Mode",
                ).classes("w-40")

                async def set_mode():
                    current_port = app.storage.user.get("mcu_port")
                    if not current_port:
                        return
                    try:
                        await run.io_bound(
                            lambda: pool.get_client(current_port).set_mode(mode_select.value)
                        )
                        ui.notify(f"Mode set to {mode_select.value}", type="positive")
                    except Exception as exc:
                        ui.notify(f"Failed: {exc}", type="negative")

                ui.button("Apply", icon="check", on_click=set_mode).style(
                    f"background: {COLORS.blue}"
                )

        # Clock Output
        with ui.card().classes("w-full p-4 mt-4").style(card_style()):
            card_header("Clock Output", "schedule")
            clock_labels: dict[str, ui.element] = {}
            with ui.row().classes("gap-6"):
                for name in ["Straddle", "Ext MCIO", "Int MCIO"]:
                    with ui.column().classes("items-center gap-1"):
                        ui.label(name).classes("text-caption").style(
                            f"color: {COLORS.text_muted}"
                        )
                        clock_labels[name] = ui.badge("--", color="grey")

        # Spread Spectrum
        with ui.card().classes("w-full p-4 mt-4").style(card_style()):
            card_header("Spread Spectrum", "waves")
            with ui.row().classes("items-end gap-4"):
                spread_status = ui.label("--").classes("text-body1").style(
                    f"color: {COLORS.text_primary}"
                )
                spread_select = ui.select(
                    ["off", "down_2500ppm", "down_5000ppm"],
                    value="off",
                    label="Mode",
                ).classes("w-48")

                async def set_spread():
                    current_port = app.storage.user.get("mcu_port")
                    if not current_port:
                        return
                    try:
                        await run.io_bound(
                            lambda: pool.get_client(current_port).set_spread(spread_select.value)
                        )
                        ui.notify(f"Spread set to {spread_select.value}", type="positive")
                        await refresh()
                    except Exception as exc:
                        ui.notify(f"Failed: {exc}", type="negative")

                ui.button("Apply", icon="check", on_click=set_spread).style(
                    f"background: {COLORS.blue}"
                )

        # FLIT Mode
        with ui.card().classes("w-full p-4 mt-4").style(card_style()):
            card_header("FLIT Mode", "memory")
            flit_labels: dict[str, ui.element] = {}
            with ui.row().classes("gap-6"):
                for station in ["Station 2", "Station 5", "Station 7", "Station 8"]:
                    with ui.column().classes("items-center gap-1"):
                        ui.label(station).classes("text-caption").style(
                            f"color: {COLORS.text_muted}"
                        )
                        flit_labels[station] = ui.badge("--", color="grey")

        # SDB Target
        with ui.card().classes("w-full p-4 mt-4").style(card_style()):
            card_header("SDB Target", "swap_horiz")
            with ui.row().classes("items-end gap-4"):
                sdb_label = ui.label("--").classes("text-body1").style(
                    f"color: {COLORS.text_primary}"
                )
                sdb_select = ui.select(
                    ["usb", "mcu"],
                    value="usb",
                    label="Target",
                ).classes("w-40")

                async def set_sdb():
                    current_port = app.storage.user.get("mcu_port")
                    if not current_port:
                        return
                    try:
                        await run.io_bound(
                            lambda: pool.get_client(current_port).set_sdb_target(sdb_select.value)
                        )
                        ui.notify(f"SDB target set to {sdb_select.value}", type="positive")
                        await refresh()
                    except Exception as exc:
                        ui.notify(f"Failed: {exc}", type="negative")

                ui.button("Apply", icon="check", on_click=set_sdb).style(
                    f"background: {COLORS.blue}"
                )

        status = status_indicator()

        async def refresh():
            current_port = app.storage.user.get("mcu_port")
            if not current_port:
                set_status_error(status, Exception("MCU disconnected"))
                return
            try:
                client_port = current_port

                clock = await run.io_bound(
                    lambda: pool.get_client(client_port).get_clock_status()
                )
                update_badge(clock_labels["Straddle"], clock.straddle_enabled)
                update_badge(clock_labels["Ext MCIO"], clock.ext_mcio_enabled)
                update_badge(clock_labels["Int MCIO"], clock.int_mcio_enabled)

                spread = await run.io_bound(
                    lambda: pool.get_client(client_port).get_spread_status()
                )
                spread_text = f"{'Enabled' if spread.enabled else 'Disabled'}"
                if spread.mode:
                    spread_text += f" ({spread.mode})"
                spread_status.text = spread_text

                flit = await run.io_bound(
                    lambda: pool.get_client(client_port).get_flit_status()
                )
                update_badge(flit_labels["Station 2"], flit.station2)
                update_badge(flit_labels["Station 5"], flit.station5)
                update_badge(flit_labels["Station 7"], flit.station7)
                update_badge(flit_labels["Station 8"], flit.station8)

                sdb = await run.io_bound(
                    lambda: pool.get_client(client_port).get_sdb_target()
                )
                sdb_label.text = f"Current: {sdb}"

                set_status_live(status)
            except Exception as exc:
                set_status_error(status, exc)

        ui.timer(5.0, refresh)

    page_layout("MCU Configuration", content)
