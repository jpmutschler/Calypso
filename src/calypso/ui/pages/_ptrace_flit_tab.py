"""Flit / Condition tab builder for the PTrace page.

Extracted to keep the main ptrace.py page under 800 lines.
Provides filter control, condition attribute, and condition data
configuration sections for A0 Flit mode support.
"""

from __future__ import annotations

import json
import re

from nicegui import ui

from calypso.hardware.ptrace_regs import FilterSrcSel, FlitMatchSel, TriggerSrcId
from calypso.ui.theme import COLORS


def build_flit_tab(
    device_id: str,
    state: dict,
    _api_url,
) -> None:
    """Build the Flit / Condition tab content.

    Args:
        device_id: Current device ID.
        state: Shared page state dict (port_number, direction).
        _api_url: Helper to build API URLs.
    """

    # Sanitize device_id — interpolated into JavaScript fetch() URLs
    if not re.match(r"^[a-zA-Z0-9_-]+$", device_id):
        ui.label("Invalid device ID").style(f"color: {COLORS.red};")
        return

    # --- Filter Control section ---
    ui.label("Filter Control (A0 Only)").style(
        f"color: {COLORS.text_primary}; font-weight: bold;"
    )
    ui.label(
        "Configure filter source selection, Flit match modes, and CXL filter enables."
    ).style(f"color: {COLORS.text_muted}; font-size: 12px;")

    filter_src_options = {m.value: m.name.replace("_", " ").title() for m in FilterSrcSel}
    flit_match_options = {m.value: m.name.replace("_", " ").title() for m in FlitMatchSel}

    with ui.row().classes("items-end gap-4 flex-wrap mt-2"):
        fc_src_sel = (
            ui.select(filter_src_options, label="Filter Source", value=0)
            .props("dense outlined")
            .classes("w-40")
        )
        fc_match_sel0 = (
            ui.select(flit_match_options, label="Filter Match Sel 0", value=0)
            .props("dense outlined")
            .classes("w-44")
        )
        fc_match_sel1 = (
            ui.select(flit_match_options, label="Filter Match Sel 1", value=0)
            .props("dense outlined")
            .classes("w-44")
        )

    with ui.row().classes("items-center gap-4 mt-2 flex-wrap"):
        fc_dllp_enb = ui.switch("DLLP Type Enable").props("dense")
        fc_os_enb = ui.switch("OS Type Enable").props("dense")
        fc_256b = ui.switch("Filter 256B Enable").props("dense")

    with ui.row().classes("items-center gap-4 mt-1 flex-wrap"):
        fc_cxl_io = ui.switch("CXL IO Filter").props("dense")
        fc_cxl_cache = ui.switch("CXL Cache Filter").props("dense")
        fc_cxl_mem = ui.switch("CXL Mem Filter").props("dense")

    with ui.row().classes("items-center gap-4 mt-1 flex-wrap"):
        fc_dllp_inv = ui.switch("DLLP Type Invert").props("dense")
        fc_os_inv = ui.switch("OS Type Invert").props("dense")

    async def apply_filter_control():
        port = state["port_number"]
        direction = state["direction"]
        body = {
            "port_number": port,
            "direction": direction,
            "config": {
                "dllp_type_enb": fc_dllp_enb.value,
                "os_type_enb": fc_os_enb.value,
                "cxl_io_filter_enb": fc_cxl_io.value,
                "cxl_cache_filter_enb": fc_cxl_cache.value,
                "cxl_mem_filter_enb": fc_cxl_mem.value,
                "filter_256b_enb": fc_256b.value,
                "filter_src_sel": int(fc_src_sel.value or 0),
                "filter_match_sel0": int(fc_match_sel0.value or 0),
                "filter_match_sel1": int(fc_match_sel1.value or 0),
                "dllp_type_inv": fc_dllp_inv.value,
                "os_type_inv": fc_os_inv.value,
            },
        }
        url = _api_url("filter-control")
        body_json = json.dumps(body)
        try:
            resp = await ui.run_javascript(
                f'return await (await fetch("{url}", {{'
                f'method: "POST", headers: {{"Content-Type": "application/json"}},'
                f"body: '{body_json}'"
                f"}})).json()",
                timeout=10.0,
            )
            if resp.get("detail"):
                ui.notify(f"Error: {resp['detail']}", type="negative")
                return
            ui.notify("Filter Control applied", type="positive")
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    ui.button("Apply Filter Control", on_click=apply_filter_control).props(
        "flat color=primary dense"
    ).classes("mt-2")

    # --- Condition Attributes section ---
    ui.separator().style(f"background-color: {COLORS.border};").classes("my-3")
    ui.label("Condition Attributes").style(
        f"color: {COLORS.text_primary}; font-weight: bold;"
    )
    ui.label(
        "Configure trigger condition match attributes (LinkSpeed, Symbols, LTSSM, Flit/CXL mode)."
    ).style(f"color: {COLORS.text_muted}; font-size: 12px;")

    cond_attr_inputs: dict[int, dict] = {}

    for cond_id in range(2):
        ui.label(f"Condition {cond_id}").style(
            f"color: {COLORS.cyan}; font-weight: bold; font-size: 13px;"
        ).classes("mt-2" if cond_id else "mt-1")

        inputs: dict = {}
        with ui.row().classes("items-end gap-3 flex-wrap"):
            inputs["link_speed"] = (
                ui.number("Link Speed", value=0, min=0, max=15)
                .props("dense outlined")
                .classes("w-28")
            )
            inputs["link_speed_mask"] = (
                ui.number("Speed Mask", value=0, min=0, max=15)
                .props("dense outlined")
                .classes("w-28")
            )
            inputs["link_width"] = (
                ui.number("Link Width", value=0, min=0, max=7)
                .props("dense outlined")
                .classes("w-28")
            )
            inputs["link_width_mask"] = (
                ui.number("Width Mask", value=0, min=0, max=7)
                .props("dense outlined")
                .classes("w-28")
            )

        with ui.row().classes("items-end gap-3 flex-wrap mt-1"):
            inputs["dllp_type"] = (
                ui.number("DLLP Type", value=0, min=0, max=255)
                .props("dense outlined")
                .classes("w-28")
            )
            inputs["dllp_type_mask"] = (
                ui.number("DLLP Mask", value=0, min=0, max=255)
                .props("dense outlined")
                .classes("w-28")
            )
            inputs["os_type"] = (
                ui.number("OS Type", value=0, min=0, max=255)
                .props("dense outlined")
                .classes("w-28")
            )
            inputs["os_type_mask"] = (
                ui.number("OS Mask", value=0, min=0, max=255)
                .props("dense outlined")
                .classes("w-28")
            )

        with ui.row().classes("items-end gap-3 flex-wrap mt-1"):
            inputs["ltssm_state"] = (
                ui.number("LTSSM State", value=0, min=0, max=511)
                .props("dense outlined")
                .classes("w-32")
            )
            inputs["ltssm_state_mask"] = (
                ui.number("LTSSM Mask", value=0, min=0, max=511)
                .props("dense outlined")
                .classes("w-32")
            )

        with ui.row().classes("items-center gap-4 mt-1 flex-wrap"):
            inputs["flit_mode"] = ui.switch("Flit Mode").props("dense")
            inputs["flit_mode_mask"] = ui.switch("Flit Mask").props("dense")
            inputs["cxl_mode"] = ui.switch("CXL Mode").props("dense")
            inputs["cxl_mode_mask"] = ui.switch("CXL Mask").props("dense")

        cond_attr_inputs[cond_id] = inputs

        async def apply_cond_attr(c=cond_id):
            port = state["port_number"]
            direction = state["direction"]
            inp = cond_attr_inputs[c]
            body = {
                "port_number": port,
                "direction": direction,
                "config": {
                    "condition_id": c,
                    "link_speed": int(inp["link_speed"].value or 0),
                    "link_speed_mask": int(inp["link_speed_mask"].value or 0),
                    "link_width": int(inp["link_width"].value or 0),
                    "link_width_mask": int(inp["link_width_mask"].value or 0),
                    "dllp_type": int(inp["dllp_type"].value or 0),
                    "dllp_type_mask": int(inp["dllp_type_mask"].value or 0),
                    "os_type": int(inp["os_type"].value or 0),
                    "os_type_mask": int(inp["os_type_mask"].value or 0),
                    "ltssm_state": int(inp["ltssm_state"].value or 0),
                    "ltssm_state_mask": int(inp["ltssm_state_mask"].value or 0),
                    "flit_mode": inp["flit_mode"].value,
                    "flit_mode_mask": inp["flit_mode_mask"].value,
                    "cxl_mode": inp["cxl_mode"].value,
                    "cxl_mode_mask": inp["cxl_mode_mask"].value,
                },
            }
            url = _api_url("condition-attributes")
            body_json = json.dumps(body)
            try:
                resp = await ui.run_javascript(
                    f'return await (await fetch("{url}", {{'
                    f'method: "POST", headers: {{"Content-Type": "application/json"}},'
                    f"body: '{body_json}'"
                    f"}})).json()",
                    timeout=10.0,
                )
                if resp.get("detail"):
                    ui.notify(f"Error: {resp['detail']}", type="negative")
                    return
                ui.notify(f"Condition {c} attributes applied", type="positive")
            except Exception as e:
                ui.notify(f"Error: {e}", type="negative")

        ui.button(
            f"Apply Cond {cond_id} Attributes",
            on_click=lambda _, c=cond_id: apply_cond_attr(c),
        ).props("flat color=primary dense").classes("mt-1")

    # --- Condition Data section ---
    ui.separator().style(f"background-color: {COLORS.border};").classes("my-3")
    ui.label("Condition Data (512-bit Match/Mask)").style(
        f"color: {COLORS.text_primary}; font-weight: bold;"
    )
    ui.label(
        "128-char hex strings for 512-bit condition match and mask data."
    ).style(f"color: {COLORS.text_muted}; font-size: 12px;")

    cond_data_inputs: dict[int, dict] = {}

    for cond_id in range(2):
        ui.label(f"Condition {cond_id} Data").style(
            f"color: {COLORS.cyan}; font-weight: bold; font-size: 13px;"
        ).classes("mt-2" if cond_id else "mt-1")

        dinputs: dict = {}
        dinputs["match"] = (
            ui.input("Match (128 hex chars)", value="0" * 128)
            .props("dense outlined")
            .classes("w-full")
            .style("font-family: monospace; font-size: 11px;")
        )
        dinputs["mask"] = (
            ui.input("Mask (128 hex chars)", value="0" * 128)
            .props("dense outlined")
            .classes("w-full")
            .style("font-family: monospace; font-size: 11px;")
        )
        cond_data_inputs[cond_id] = dinputs

        async def apply_cond_data(c=cond_id):
            port = state["port_number"]
            direction = state["direction"]
            dinp = cond_data_inputs[c]
            match_hex = dinp["match"].value or ("0" * 128)
            mask_hex = dinp["mask"].value or ("0" * 128)
            body = {
                "port_number": port,
                "direction": direction,
                "config": {
                    "condition_id": c,
                    "match_hex": match_hex.ljust(128, "0")[:128],
                    "mask_hex": mask_hex.ljust(128, "0")[:128],
                },
            }
            url = _api_url("condition-data")
            body_json = json.dumps(body)
            try:
                resp = await ui.run_javascript(
                    f'return await (await fetch("{url}", {{'
                    f'method: "POST", headers: {{"Content-Type": "application/json"}},'
                    f"body: '{body_json}'"
                    f"}})).json()",
                    timeout=10.0,
                )
                if resp.get("detail"):
                    ui.notify(f"Error: {resp['detail']}", type="negative")
                    return
                ui.notify(f"Condition {c} data applied", type="positive")
            except Exception as e:
                ui.notify(f"Error: {e}", type="negative")

        ui.button(
            f"Apply Cond {cond_id} Data",
            on_click=lambda _, c=cond_id: apply_cond_data(c),
        ).props("flat color=primary dense").classes("mt-1")


def get_trigger_src_options() -> dict[int, str]:
    """Return trigger source ID options for the trigger source dropdown."""
    return {m.value: m.name.replace("_", " ").title() for m in TriggerSrcId}
