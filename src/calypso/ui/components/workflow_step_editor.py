"""Editor component for a single workflow step."""

from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from calypso.ui.components.param_inputs import binding_input, param_input
from calypso.ui.theme import COLORS
from calypso.workflows import get_all_recipes, get_recipe
from calypso.workflows.workflow_models import OnFailAction


def workflow_step_editor(
    step_data: dict,
    step_index: int,
    on_update: Callable,
    on_delete: Callable,
) -> None:
    """Render an editor for one workflow step.

    Args:
        step_data: Mutable dict with keys ``recipe_id``, ``label``,
            ``parameters``, ``on_fail``, ``loop_count``, ``loop_delay_s``,
            ``loop_stop_on_fail``, ``condition_expression``, ``bindings``,
            ``enabled``.
        step_index: Zero-based index of this step in the workflow.
        on_update: Callback invoked after any change with ``(step_index, step_data)``.
        on_delete: Callback invoked with ``(step_index,)`` when the delete button
            is clicked.
    """
    recipes = get_all_recipes()
    recipe_options = {r.recipe_id: r.name for r in recipes}

    with (
        ui.card()
        .classes("w-full q-pa-md")
        .style(f"background: {COLORS.bg_card}; border: 1px solid {COLORS.border};")
    ):
        # Header row
        with ui.row().classes("items-center w-full gap-2"):
            enabled = step_data.get("enabled", True)
            ui.checkbox(
                "",
                value=enabled,
                on_change=lambda e: _update_field(
                    step_data, "enabled", e.value, step_index, on_update
                ),
            ).props("dense").tooltip("Enable/disable this step")

            ui.label(f"Step {step_index + 1}").classes("text-subtitle2").style(
                f"color: {COLORS.cyan}; font-weight: 600;"
            )

            label_val = step_data.get("label", "")
            ui.input(
                label="Label",
                value=label_val,
                on_change=lambda e: _update_field(
                    step_data, "label", e.value, step_index, on_update
                ),
            ).props("dense outlined").classes("flex-grow")

            ui.space()

            ui.button(
                icon="delete",
                on_click=lambda _, idx=step_index: on_delete(idx),
            ).props("flat dense color=negative").tooltip("Remove step")

        # Recipe picker
        current_recipe_id = step_data.get("recipe_id", "")
        step_data.setdefault("parameters", {})
        param_container = ui.column().classes("w-full")

        def _on_recipe_change(e, container=param_container) -> None:
            new_id = e.value
            step_data["recipe_id"] = new_id
            step_data["parameters"] = {}
            _rebuild_params(container, new_id, step_data, step_index, on_update)
            on_update(step_index, step_data)

        ui.select(
            options=recipe_options,
            value=current_recipe_id if current_recipe_id in recipe_options else None,
            label="Recipe",
            on_change=_on_recipe_change,
        ).props("dense outlined").classes("w-full q-mt-sm")

        # Parameter inputs for selected recipe
        _rebuild_params(param_container, current_recipe_id, step_data, step_index, on_update)

        # Advanced settings (expansion)
        with (
            ui.expansion("Advanced", icon="tune")
            .classes("w-full q-mt-sm")
            .style(f"background: {COLORS.bg_primary};")
        ):
            with ui.column().classes("q-pa-sm q-gutter-sm w-full"):
                # On-fail action
                ui.select(
                    options={a.value: a.value for a in OnFailAction},
                    value=step_data.get("on_fail", OnFailAction.STOP.value),
                    label="On Failure",
                    on_change=lambda e: _update_field(
                        step_data, "on_fail", e.value, step_index, on_update
                    ),
                ).props("dense outlined").classes("w-48")

                # Loop config
                with ui.row().classes("items-end gap-3"):
                    ui.number(
                        label="Loop Count",
                        value=int(step_data.get("loop_count", 1)),
                        min=1,
                        max=1000,
                        step=1,
                        on_change=lambda e: _update_field(
                            step_data,
                            "loop_count",
                            int(e.value) if e.value else 1,
                            step_index,
                            on_update,
                        ),
                    ).props("dense outlined").classes("w-28")

                    ui.number(
                        label="Loop Delay (s)",
                        value=float(step_data.get("loop_delay_s", 0.0)),
                        min=0.0,
                        max=3600.0,
                        step=0.5,
                        on_change=lambda e: _update_field(
                            step_data,
                            "loop_delay_s",
                            float(e.value) if e.value else 0.0,
                            step_index,
                            on_update,
                        ),
                    ).props("dense outlined").classes("w-32")

                    ui.checkbox(
                        "Stop loop on fail",
                        value=bool(step_data.get("loop_stop_on_fail", True)),
                        on_change=lambda e: _update_field(
                            step_data,
                            "loop_stop_on_fail",
                            e.value,
                            step_index,
                            on_update,
                        ),
                    ).props("dense")

                # Condition expression
                ui.input(
                    label="Condition Expression",
                    placeholder="e.g. step_0.total_pass > 0",
                    value=step_data.get("condition_expression", ""),
                    on_change=lambda e: _update_field(
                        step_data,
                        "condition_expression",
                        e.value,
                        step_index,
                        on_update,
                    ),
                ).props("dense outlined").classes("w-full")

                # Bindings
                bindings = step_data.setdefault("bindings", {})
                recipe = get_recipe(step_data.get("recipe_id", ""))
                if recipe and recipe.parameters:
                    ui.label("Parameter Bindings").style(
                        f"color: {COLORS.text_secondary}; font-size: 12px;"
                    )
                    for param in recipe.parameters:
                        binding_input(
                            param.name,
                            bindings,
                            key=param.name,
                        )


def _rebuild_params(
    container,
    recipe_id: str,
    step_data: dict,
    step_index: int,
    on_update: Callable,
) -> None:
    """Rebuild parameter input widgets for the selected recipe."""
    container.clear()
    recipe = get_recipe(recipe_id)
    if recipe is None or not recipe.parameters:
        return

    param_store = step_data.setdefault("parameters", {})

    with container:
        ui.label("Parameters").classes("text-caption q-mt-sm").style(
            f"color: {COLORS.text_secondary};"
        )
        for p in recipe.parameters:
            param_input(p, param_store)

    on_update(step_index, step_data)


def _update_field(
    step_data: dict,
    field: str,
    value: object,
    step_index: int,
    on_update: Callable,
) -> None:
    """Update a single field in step_data and notify the parent."""
    step_data[field] = value
    on_update(step_index, step_data)
