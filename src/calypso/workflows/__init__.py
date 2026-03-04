"""Workflows & Recipes system for structured hardware validation.

Provides a registry of recipes (individual test sequences) and
a workflow engine for chaining recipes into multi-step validation runs.
"""

from __future__ import annotations

import threading

from calypso.workflows.base import Recipe
from calypso.workflows.models import RecipeCategory

# Global recipe registry
RECIPE_REGISTRY: dict[str, Recipe] = {}


def register_recipe(recipe: Recipe) -> None:
    """Register a recipe instance in the global registry."""
    RECIPE_REGISTRY[recipe.recipe_id] = recipe


def get_recipe(recipe_id: str) -> Recipe | None:
    """Look up a recipe by ID."""
    _ensure_loaded()
    return RECIPE_REGISTRY.get(recipe_id)


def get_all_recipes() -> list[Recipe]:
    """Return all registered recipes."""
    _ensure_loaded()
    return list(RECIPE_REGISTRY.values())


def get_recipes_by_category(category: RecipeCategory) -> list[Recipe]:
    """Return recipes filtered by category."""
    _ensure_loaded()
    return [r for r in RECIPE_REGISTRY.values() if r.category == category]


_loaded = False
_load_lock = threading.Lock()


def _ensure_loaded() -> None:
    """Lazily import and register all recipes on first access."""
    global _loaded
    if _loaded:
        return
    with _load_lock:
        if _loaded:
            return
        _loaded = True

        try:
            from calypso.workflows.recipes import register_all

            register_all()
        except ImportError:
            pass
