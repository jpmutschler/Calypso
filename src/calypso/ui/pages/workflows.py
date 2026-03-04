"""Recipes & Workflows page -- browse, configure, and run recipes."""

from __future__ import annotations

import asyncio
import json
import re

from nicegui import ui

from calypso.ui.components.param_inputs import extract_values, param_input
from calypso.ui.components.recipe_card import recipe_card
from calypso.ui.components.recipe_stepper import RecipeStepper
from calypso.ui.layout import page_layout
from calypso.ui.theme import COLORS
from calypso.workflows import get_recipes_by_category
from calypso.workflows.models import (
    CATEGORY_DISPLAY_NAMES,
    CATEGORY_ICONS,
    RecipeCategory,
)
from calypso.workflows.workflow_executor import cancel_recipe


def workflows_page(device_id: str) -> None:
    """Render the Recipes & Workflows page."""

    def content():
        _workflows_content(device_id)

    page_layout("Recipes & Workflows", content, device_id=device_id)


def _workflows_content(device_id: str) -> None:
    """Build the workflows page body."""
    if not re.match(r"^[a-zA-Z0-9_-]+$", device_id):
        ui.label("Invalid device ID").style("color: red;")
        return

    state: dict = {
        "active_stepper": None,
        "param_values": {},
    }

    # --- Actions ---

    def _on_run_clicked(recipe, dev_id: str) -> None:
        """Open the parameter dialog before running a recipe."""
        if recipe.parameters:
            _show_param_dialog(recipe, dev_id, state)
        else:
            _start_recipe_run(recipe.recipe_id, dev_id, {}, state)

    def _start_recipe_run(
        recipe_id: str,
        dev_id: str,
        params: dict,
        local_state: dict,
    ) -> None:
        """Launch a recipe via the REST API and show the stepper."""
        # Cancel any previous stepper
        prev = local_state.get("active_stepper")
        if prev is not None:
            prev.cancel()

        async def _launch():
            body = {"recipe_id": recipe_id, "parameters": params}
            try:
                await ui.run_javascript(
                    f'return await (await fetch("/api/devices/{dev_id}'
                    f'/recipes/run", {{'
                    f'method: "POST",'
                    f' headers: {{"Content-Type": "application/json"}},'
                    f" body: JSON.stringify({json.dumps(body)})"
                    f"}})).json()",
                    timeout=10.0,
                )
            except Exception as exc:
                ui.notify(f"Failed to start recipe: {exc}", type="negative")
                return

            # Show stepper
            stepper_container.clear()
            stepper_container.set_visibility(True)
            with stepper_container:
                stepper = RecipeStepper(dev_id)
                local_state["active_stepper"] = stepper

        asyncio.ensure_future(_launch())

    # --- Layout ---

    # Category tabs
    categories = list(RecipeCategory)
    with ui.tabs().classes("w-full").style(f"background: {COLORS.bg_secondary};") as tabs:
        for cat in categories:
            cat_label = CATEGORY_DISPLAY_NAMES.get(cat, cat.value)
            cat_icon = CATEGORY_ICONS.get(cat, "help_outline")
            ui.tab(cat.value, label=cat_label, icon=cat_icon)

    with (
        ui.tab_panels(tabs, value=categories[0].value)
        .classes("w-full")
        .style(f"background: {COLORS.bg_primary};")
    ):
        for cat in categories:
            with ui.tab_panel(cat.value):
                recipes = get_recipes_by_category(cat)
                if not recipes:
                    ui.label("No recipes in this category").style(f"color: {COLORS.text_muted};")
                else:
                    with ui.row().classes("w-full gap-4 flex-wrap"):
                        for r in recipes:
                            recipe_card(r, device_id, _on_run_clicked)

    # Navigation to builder
    with ui.row().classes("w-full q-mt-md gap-3 items-center"):
        ui.button(
            "Open Workflow Builder",
            icon="build",
            on_click=lambda: ui.navigate.to(f"/switch/{device_id}/workflow-builder"),
        ).props("flat color=primary")

        # Cancel button for active recipe
        ui.button(
            "Cancel Recipe",
            icon="stop",
            on_click=lambda: _cancel_active(device_id, state),
        ).props("flat color=negative")

    # Stepper container (hidden until a recipe is launched)
    stepper_container = ui.column().classes("w-full q-mt-md")
    stepper_container.set_visibility(False)


def _show_param_dialog(recipe, device_id: str, state: dict) -> None:
    """Open a dialog to configure recipe parameters before running."""
    param_values: dict = {}

    with (
        ui.dialog() as dialog,
        ui.card()
        .classes("q-pa-md")
        .style(
            f"background: {COLORS.bg_card}; border: 1px solid {COLORS.border}; min-width: 400px;"
        ),
    ):
        ui.label(f"Configure: {recipe.name}").classes("text-subtitle1").style(
            f"color: {COLORS.text_primary}; font-weight: 600;"
        )
        ui.label(recipe.description).style(f"color: {COLORS.text_secondary}; font-size: 13px;")

        ui.separator().style(f"background-color: {COLORS.border};")

        with ui.column().classes("q-mt-sm q-gutter-sm"):
            for p in recipe.parameters:
                param_input(p, param_values)

        with ui.row().classes("justify-end q-mt-md gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            ui.button(
                "Run",
                icon="play_arrow",
                on_click=lambda: _run_from_dialog(dialog, recipe, device_id, param_values, state),
            ).props("color=positive")

    dialog.open()


def _run_from_dialog(
    dialog,
    recipe,
    device_id: str,
    param_values: dict,
    state: dict,
) -> None:
    """Extract parameter values, close the dialog, and start the run."""
    extracted = extract_values(recipe.parameters, param_values)
    dialog.close()

    # Re-use the _start_recipe_run flow
    _start_recipe_run_api(recipe.recipe_id, device_id, extracted, state)


def _start_recipe_run_api(
    recipe_id: str,
    device_id: str,
    params: dict,
    local_state: dict,
) -> None:
    """Launch a recipe run through the API and display the stepper.

    This is a module-level version of ``_start_recipe_run`` used by the
    dialog callback which cannot close over the nested function.
    """
    prev = local_state.get("active_stepper")
    if prev is not None:
        prev.cancel()

    async def _launch():
        body = {"recipe_id": recipe_id, "parameters": params}
        try:
            await ui.run_javascript(
                f'return await (await fetch("/api/devices/{device_id}'
                f'/recipes/run", {{'
                f'method: "POST",'
                f' headers: {{"Content-Type": "application/json"}},'
                f" body: JSON.stringify({json.dumps(body)})"
                f"}})).json()",
                timeout=10.0,
            )
        except Exception as exc:
            ui.notify(f"Failed to start recipe: {exc}", type="negative")
            return

        ui.notify("Recipe started", type="positive")

    asyncio.ensure_future(_launch())


def _cancel_active(device_id: str, state: dict) -> None:
    """Request cancellation of the active recipe."""
    cancel_recipe(device_id)
    ui.notify("Cancellation requested", type="info")
    stepper = state.get("active_stepper")
    if stepper is not None:
        stepper.cancel()
