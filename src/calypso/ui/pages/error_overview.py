"""Combined Error Overview page -- merges AER, MCU, and LTSSM error sources."""

from __future__ import annotations

from urllib.parse import quote

from nicegui import app, ui

from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS


def error_overview_page(device_id: str) -> None:
    """Render the combined error overview page."""

    def content():
        _error_overview_content(device_id)

    page_layout("Error Overview", content, device_id=device_id)


def _error_overview_content(device_id: str) -> None:
    """Build the error overview page content."""

    state: dict = {"auto_refresh": False, "data": None}

    # ---- Summary cards ----
    with ui.row().classes("w-full gap-4 flex-wrap"):
        aer_uncorr_card = _stat_card("AER Uncorrectable", "--")
        aer_corr_card = _stat_card("AER Correctable", "--")
        mcu_card = _stat_card("MCU Total Errors", "--")
        ltssm_card = _stat_card("LTSSM Recoveries", "--")

    # ---- AER detail card ----
    with ui.card().classes("w-full p-4 mt-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    ):
        ui.label("Advanced Error Reporting (AER)").classes("text-h6 mb-2").style(
            f"color: {COLORS.text_primary}"
        )

        with ui.row().classes("w-full gap-8"):
            with ui.column().classes("flex-1"):
                ui.label("Uncorrectable Errors").style(
                    f"color: {COLORS.text_secondary}; font-weight: bold"
                )
                aer_uncorr_raw = ui.label("Raw: --").style(
                    f"color: {COLORS.text_muted}; font-size: 12px; "
                    f"font-family: 'JetBrains Mono', monospace"
                )
                aer_uncorr_badges = ui.row().classes("flex-wrap gap-1 mt-1")

            with ui.column().classes("flex-1"):
                ui.label("Correctable Errors").style(
                    f"color: {COLORS.text_secondary}; font-weight: bold"
                )
                aer_corr_raw = ui.label("Raw: --").style(
                    f"color: {COLORS.text_muted}; font-size: 12px; "
                    f"font-family: 'JetBrains Mono', monospace"
                )
                aer_corr_badges = ui.row().classes("flex-wrap gap-1 mt-1")

        async def clear_aer():
            try:
                await ui.run_javascript(
                    f'return await (await fetch("/api/devices/{device_id}'
                    f'/errors/clear-aer", {{method: "POST"}})).json()'
                )
                ui.notify("AER errors cleared", type="positive")
                await refresh()
            except Exception as exc:
                ui.notify(f"Clear AER failed: {exc}", type="negative")

        ui.button("Clear AER", icon="delete_sweep", on_click=clear_aer).props(
            "flat color=negative size=sm"
        ).classes("mt-2")

    # ---- Per-port error table ----
    port_columns = [
        {"name": "port_number", "label": "Port", "field": "port_number", "align": "center"},
        {"name": "mcu_bad_tlp", "label": "MCU Bad TLP", "field": "mcu_bad_tlp", "align": "right"},
        {"name": "mcu_bad_dllp", "label": "MCU Bad DLLP", "field": "mcu_bad_dllp", "align": "right"},
        {"name": "mcu_link_down", "label": "MCU Link Down", "field": "mcu_link_down", "align": "right"},
        {"name": "mcu_total", "label": "MCU Total", "field": "mcu_total", "align": "right"},
        {"name": "ltssm_recovery_count", "label": "LTSSM Recovery", "field": "ltssm_recovery_count", "align": "right"},
        {"name": "ltssm_link_down_count", "label": "LTSSM Link Down", "field": "ltssm_link_down_count", "align": "right"},
        {"name": "ltssm_rx_eval_count", "label": "LTSSM Rx Eval", "field": "ltssm_rx_eval_count", "align": "right"},
    ]

    with ui.card().classes("w-full p-4 mt-4").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}"
    ):
        ui.label("Per-Port Error Breakdown").classes("text-h6 mb-2").style(
            f"color: {COLORS.text_primary}"
        )

        port_table = ui.table(
            columns=port_columns,
            rows=[],
            row_key="port_number",
        ).classes("w-full")

        mcu_clear_container = ui.row().classes("mt-2")

    # ---- Controls ----
    with ui.row().classes("items-center gap-4 mt-4"):
        ui.button("Refresh", icon="refresh", on_click=lambda: refresh()).props(
            "flat color=primary"
        )
        auto_toggle = ui.switch("Auto-refresh (5s)").style(f"color: {COLORS.text_secondary}")

    status_label = ui.label("").style(f"color: {COLORS.text_muted}; font-size: 12px")

    def on_auto_toggle(e):
        state["auto_refresh"] = e.value
        if e.value:
            timer.activate()
        else:
            timer.deactivate()

    auto_toggle.on("update:model-value", on_auto_toggle)

    async def refresh():
        mcu_port = app.storage.user.get("mcu_port", "")
        url = f"/api/devices/{device_id}/errors/overview"
        if mcu_port:
            url += f"?mcu_port={quote(mcu_port, safe='')}"

        try:
            data = await ui.run_javascript(
                f'return await (await fetch("{url}")).json()'
            )
            state["data"] = data
            _update_ui(data)
            status_label.text = "Last updated: OK"
            status_label.style(f"color: {COLORS.green}; font-size: 12px")
        except Exception as exc:
            status_label.text = f"Error: {exc}"
            status_label.style(f"color: {COLORS.red}; font-size: 12px")

    def _update_ui(data: dict) -> None:
        """Push fetched data into all UI elements."""
        # Summary cards
        uncorr = data.get("total_aer_uncorrectable", 0)
        corr = data.get("total_aer_correctable", 0)
        mcu_total = data.get("total_mcu_errors", 0)
        ltssm_total = data.get("total_ltssm_recoveries", 0)
        mcu_connected = data.get("mcu_connected", False)

        _update_stat_card(aer_uncorr_card, str(uncorr),
                          COLORS.red if uncorr > 0 else COLORS.green)
        _update_stat_card(aer_corr_card, str(corr),
                          COLORS.yellow if corr > 0 else COLORS.green)
        _update_stat_card(
            mcu_card,
            str(mcu_total) if mcu_connected else "N/A",
            COLORS.red if mcu_total > 0 else (
                COLORS.green if mcu_connected else COLORS.text_muted
            ),
        )
        _update_stat_card(ltssm_card, str(ltssm_total),
                          COLORS.orange if ltssm_total > 0 else COLORS.green)

        # AER detail
        aer_uncorr_raw.text = f"Raw: 0x{data.get('aer_uncorrectable_raw', 0):08X}"
        aer_corr_raw.text = f"Raw: 0x{data.get('aer_correctable_raw', 0):08X}"

        aer_uncorr_badges.clear()
        with aer_uncorr_badges:
            for name in data.get("aer_uncorrectable_active", []):
                ui.badge(name.replace("_", " ")).style(
                    f"background: {COLORS.red_dim}; color: {COLORS.red}"
                )
            if not data.get("aer_uncorrectable_active"):
                ui.label("None").style(f"color: {COLORS.green}; font-size: 12px")

        aer_corr_badges.clear()
        with aer_corr_badges:
            for name in data.get("aer_correctable_active", []):
                ui.badge(name.replace("_", " ")).style(
                    f"background: {COLORS.yellow_dim}; color: {COLORS.yellow}"
                )
            if not data.get("aer_correctable_active"):
                ui.label("None").style(f"color: {COLORS.green}; font-size: 12px")

        # Per-port table
        rows = []
        for pe in data.get("port_errors", []):
            rows.append({
                "port_number": pe.get("port_number", 0),
                "mcu_bad_tlp": _fmt_val(pe.get("mcu_bad_tlp")),
                "mcu_bad_dllp": _fmt_val(pe.get("mcu_bad_dllp")),
                "mcu_link_down": _fmt_val(pe.get("mcu_link_down")),
                "mcu_total": _fmt_val(pe.get("mcu_total")),
                "ltssm_recovery_count": _fmt_val(pe.get("ltssm_recovery_count")),
                "ltssm_link_down_count": _fmt_val(pe.get("ltssm_link_down_count")),
                "ltssm_rx_eval_count": _fmt_val(pe.get("ltssm_rx_eval_count")),
            })
        port_table.rows = rows
        port_table.update()

        # MCU clear button
        mcu_clear_container.clear()
        if mcu_connected:
            with mcu_clear_container:
                async def clear_mcu():
                    mcu_port = app.storage.user.get("mcu_port", "")
                    if not mcu_port:
                        ui.notify("No MCU port configured", type="warning")
                        return
                    try:
                        encoded_port = quote(mcu_port, safe="")
                        await ui.run_javascript(
                            f'return await (await fetch("/api/devices/{device_id}'
                            f'/errors/clear-mcu?mcu_port={encoded_port}",'
                            f' {{method: "POST"}})).json()'
                        )
                        ui.notify("MCU counters cleared", type="positive")
                        await refresh()
                    except Exception as exc:
                        ui.notify(f"Clear MCU failed: {exc}", type="negative")

                ui.button("Clear MCU Counters", icon="delete_sweep", on_click=clear_mcu).props(
                    "flat color=negative size=sm"
                )

    timer = ui.timer(5.0, refresh, active=False)


def _fmt_val(v: int | None) -> str:
    """Format a counter value, showing '--' for None."""
    if v is None:
        return "--"
    return str(v)


def _stat_card(title: str, value: str) -> dict:
    """Create a summary stat card returning refs to update later."""
    with ui.element("div").classes("p-4 rounded flex-1").style(
        f"background: {COLORS.bg_secondary}; border: 1px solid {COLORS.border}; "
        f"min-width: 160px"
    ):
        lbl_title = ui.label(title).style(
            f"color: {COLORS.text_secondary}; font-size: 12px"
        )
        lbl_value = ui.label(value).classes("text-h5").style(
            f"color: {COLORS.text_primary}"
        )
    return {"title": lbl_title, "value": lbl_value}


def _update_stat_card(card: dict, value: str, color: str) -> None:
    """Update a stat card's value and color."""
    card["value"].text = value
    card["value"].style(f"color: {color}")
