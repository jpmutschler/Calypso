"""Recipe card component for the workflows page."""

from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from calypso.ui.theme import COLORS
from calypso.workflows.base import Recipe
from calypso.workflows.models import (
    CATEGORY_DISPLAY_NAMES,
    CATEGORY_ICONS,
    RecipeCategory,
)

# Category badge background tints
_CATEGORY_COLORS: dict[RecipeCategory, str] = {
    RecipeCategory.LINK_HEALTH: COLORS.green,
    RecipeCategory.SIGNAL_INTEGRITY: COLORS.cyan,
    RecipeCategory.PERFORMANCE: COLORS.blue,
    RecipeCategory.CONFIGURATION: COLORS.yellow,
    RecipeCategory.DEBUG: COLORS.orange,
    RecipeCategory.ERROR_TESTING: COLORS.red,
}


def recipe_card(
    recipe: Recipe,
    device_id: str,
    on_run: Callable,
    *,
    active: bool = False,
    disabled: bool = False,
) -> None:
    """Render a card showing recipe info with a Run button.

    Args:
        recipe: The recipe instance to display.
        device_id: The connected device ID.
        on_run: Callback invoked with ``(recipe, device_id)`` when Run is clicked.
        active: When ``True`` the card is highlighted with a pulsing cyan left
            border to indicate this recipe is currently executing.
        disabled: When ``True`` the Run button is disabled and shows a loading
            spinner, preventing duplicate launches while a recipe is active.
    """
    cat_color = _CATEGORY_COLORS.get(recipe.category, COLORS.text_secondary)
    cat_icon = CATEGORY_ICONS.get(recipe.category, "help_outline")
    cat_label = CATEGORY_DISPLAY_NAMES.get(recipe.category, recipe.category.value)

    active_border = (
        f"border-left: 3px solid {COLORS.cyan};"
        f" box-shadow: -2px 0 8px {COLORS.cyan}40;"
        if active
        else ""
    )

    with (
        ui.card()
        .classes("w-full")
        .style(
            f"background: {COLORS.bg_card}; border: 1px solid {COLORS.border};"
            f" min-width: 280px; max-width: 420px; {active_border}"
        )
    ):
        with ui.column().classes("q-pa-md q-gutter-sm w-full"):
            # Title row
            with ui.row().classes("items-center gap-2 w-full"):
                ui.icon(cat_icon).style(f"color: {cat_color}; font-size: 1.3rem;")
                ui.label(recipe.name).classes("text-subtitle1").style(
                    f"color: {COLORS.text_primary}; font-weight: 600;"
                )

            # Category badge
            ui.badge(cat_label).style(
                f"background: {cat_color}20; color: {cat_color}; font-size: 11px; padding: 2px 8px;"
            )

            # Description
            ui.label(recipe.description).style(f"color: {COLORS.text_secondary}; font-size: 13px;")

            # Parameter count hint
            param_count = len(recipe.parameters)
            if param_count > 0:
                ui.label(
                    f"{param_count} configurable parameter{'s' if param_count != 1 else ''}"
                ).style(f"color: {COLORS.text_muted}; font-size: 11px;")

            # Bottom row: duration estimate + run button
            with ui.row().classes("items-center justify-between w-full q-mt-sm"):
                duration_s = recipe.estimated_duration_s
                if duration_s >= 60:
                    dur_text = f"~{duration_s // 60}m {duration_s % 60}s"
                else:
                    dur_text = f"~{duration_s}s"

                ui.label(dur_text).style(f"color: {COLORS.text_muted}; font-size: 12px;").tooltip(
                    "Estimated duration"
                )

                btn = ui.button(
                    "Run" if not disabled else "Running...",
                    icon="play_arrow" if not disabled else "sync",
                    on_click=lambda _, r=recipe: on_run(r, device_id),
                ).props("color=positive dense")
                if disabled:
                    btn.props("disable loading")
