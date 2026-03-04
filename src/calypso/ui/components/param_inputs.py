"""Widget factory for rendering RecipeParameter inputs in NiceGUI."""

from __future__ import annotations

from nicegui import ui

from calypso.ui.theme import COLORS
from calypso.workflows.models import RecipeParameter


def param_input(
    param: RecipeParameter,
    value_store: dict,
    key_prefix: str = "",
) -> None:
    """Render an input widget for a recipe parameter.

    Creates the appropriate NiceGUI widget based on ``param.param_type``
    and stores the current value in *value_store* keyed by param name.

    Args:
        param: The parameter descriptor.
        value_store: Mutable dict that receives the live widget values.
        key_prefix: Optional prefix for the value_store key.
    """
    store_key = f"{key_prefix}{param.name}" if key_prefix else param.name

    # Seed the store with the default value if not already present
    if store_key not in value_store:
        value_store[store_key] = param.default

    with ui.column().classes("q-mb-sm"):
        if param.param_type == "bool":
            ui.checkbox(
                param.label,
                value=bool(param.default),
                on_change=lambda e, k=store_key: value_store.update({k: e.value}),
            ).props("dense").tooltip(param.description)

        elif param.param_type == "choice":
            ui.select(
                options=param.choices,
                value=param.default
                if param.default in param.choices
                else (param.choices[0] if param.choices else None),
                label=param.label,
                on_change=lambda e, k=store_key: value_store.update({k: e.value}),
            ).props("dense outlined").classes("w-48").tooltip(param.description)

        elif param.param_type == "str":
            ui.input(
                label=param.label,
                value=str(param.default or ""),
                on_change=lambda e, k=store_key: value_store.update({k: e.value}),
            ).props("dense outlined").classes("w-48").tooltip(param.description)

        elif param.param_type == "float":
            with ui.row().classes("items-center gap-1"):
                ui.number(
                    label=param.label,
                    value=float(param.default or 0),
                    min=param.min_value,
                    max=param.max_value,
                    step=0.1,
                    on_change=lambda e, k=store_key: value_store.update(
                        {k: float(e.value) if e.value is not None else 0.0}
                    ),
                ).props("dense outlined").classes("w-36").tooltip(param.description)
                if param.unit:
                    ui.label(param.unit).style(f"color: {COLORS.text_muted}; font-size: 12px;")

        else:
            # Default: int
            with ui.row().classes("items-center gap-1"):
                ui.number(
                    label=param.label,
                    value=int(param.default or 0),
                    min=param.min_value,
                    max=param.max_value,
                    step=1,
                    on_change=lambda e, k=store_key: value_store.update(
                        {k: int(e.value) if e.value is not None else 0}
                    ),
                ).props("dense outlined").classes("w-36").tooltip(param.description)
                if param.unit:
                    ui.label(param.unit).style(f"color: {COLORS.text_muted}; font-size: 12px;")

        # Description hint below the input (except bool, which uses tooltip)
        if param.description and param.param_type != "bool":
            ui.label(param.description).style(
                f"color: {COLORS.text_muted}; font-size: 11px; margin-top: -4px;"
            )


def extract_values(
    params: list[RecipeParameter],
    value_store: dict,
    key_prefix: str = "",
) -> dict:
    """Extract typed values from the value store.

    Converts each stored value to the correct Python type based on the
    parameter's ``param_type``.

    Args:
        params: List of parameter descriptors.
        value_store: The dict populated by ``param_input`` widgets.
        key_prefix: Prefix used when rendering the inputs.

    Returns:
        A dict mapping parameter name to its typed value.
    """
    result: dict = {}
    for param in params:
        store_key = f"{key_prefix}{param.name}" if key_prefix else param.name
        raw = value_store.get(store_key, param.default)

        if raw is None:
            result[param.name] = param.default
            continue

        if param.param_type == "int":
            result[param.name] = int(raw)
        elif param.param_type == "float":
            result[param.name] = float(raw)
        elif param.param_type == "bool":
            result[param.name] = bool(raw)
        elif param.param_type == "str":
            result[param.name] = str(raw)
        elif param.param_type == "choice":
            result[param.name] = str(raw)
        else:
            result[param.name] = raw

    return result


def binding_input(
    param_name: str,
    value_store: dict,
    key: str = "",
) -> None:
    """Render a binding expression input for workflow step parameters.

    Bindings let a workflow step reference a value from a previous step,
    e.g. ``step_0.total_pass``.

    Args:
        param_name: The parameter name this binding overrides.
        value_store: Dict to store the binding expression string.
        key: Storage key (defaults to ``param_name``).
    """
    store_key = key or param_name
    ui.input(
        label=f"Bind: {param_name}",
        placeholder="e.g. step_0.total_pass",
        value=str(value_store.get(store_key, "")),
        on_change=lambda e, k=store_key: value_store.update({k: e.value}),
    ).props("dense outlined").classes("w-64").tooltip(
        f"Expression to resolve {param_name} from a previous step result"
    )
