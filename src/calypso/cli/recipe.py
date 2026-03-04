"""CLI commands for managing and running validation recipes."""

from __future__ import annotations

import click


@click.group()
def recipe():
    """Manage and run validation recipes."""
    pass


# ---------------------------------------------------------------------------
# Shared setup helpers
# ---------------------------------------------------------------------------


def _init_sdk():
    from calypso.bindings.library import load_library
    from calypso.bindings.functions import initialize

    load_library()
    initialize()


def _make_transport_cli(transport: str, port: int):
    from calypso.cli.main import _make_transport

    return _make_transport(transport, port)


# ---------------------------------------------------------------------------
# recipe list
# ---------------------------------------------------------------------------


@recipe.command("list")
@click.option("--category", "-c", default=None, help="Filter by category")
@click.pass_context
def list_recipes(ctx: click.Context, category: str | None) -> None:
    """List all available recipes grouped by category."""
    from calypso.workflows import get_all_recipes, get_recipes_by_category
    from calypso.workflows.models import (
        CATEGORY_DISPLAY_NAMES,
        RecipeCategory,
    )

    if category:
        try:
            cat = RecipeCategory(category)
        except ValueError:
            valid = ", ".join(c.value for c in RecipeCategory)
            click.echo(f"Unknown category: {category}. Valid: {valid}", err=True)
            ctx.exit(1)
            return
        recipes = get_recipes_by_category(cat)
        _print_recipe_group(CATEGORY_DISPLAY_NAMES.get(cat, category), recipes)
        return

    all_recipes = get_all_recipes()
    if not all_recipes:
        click.echo("No recipes registered.")
        return

    # Group by category
    grouped: dict[RecipeCategory, list] = {}
    for r in all_recipes:
        grouped.setdefault(r.category, []).append(r)

    for cat in RecipeCategory:
        group = grouped.get(cat, [])
        if group:
            display_name = CATEGORY_DISPLAY_NAMES.get(cat, cat.value)
            _print_recipe_group(display_name, group)
            click.echo()


def _print_recipe_group(group_name: str, recipes: list) -> None:
    """Print a category header and its recipes."""
    click.echo(click.style(f"{group_name}", bold=True))
    click.echo(click.style("-" * 60, fg="bright_black"))
    for r in recipes:
        duration = f"~{r.estimated_duration_s}s" if r.estimated_duration_s else ""
        click.echo(f"  {click.style(r.recipe_id, fg='cyan'):<30} {r.name:<25} {duration}")


# ---------------------------------------------------------------------------
# recipe params <recipe_id>
# ---------------------------------------------------------------------------


@recipe.command()
@click.argument("recipe_id")
def params(recipe_id: str) -> None:
    """Show configurable parameters for a recipe."""
    from calypso.workflows import get_recipe
    from calypso.workflows.models import CATEGORY_DISPLAY_NAMES

    r = get_recipe(recipe_id)
    if r is None:
        click.echo(f"Unknown recipe: {recipe_id}", err=True)
        raise SystemExit(1)

    category_name = CATEGORY_DISPLAY_NAMES.get(r.category, r.category)
    click.echo(click.style(f"Recipe: {r.name}", bold=True))
    click.echo(f"  ID:          {r.recipe_id}")
    click.echo(f"  Category:    {category_name}")
    click.echo(f"  Description: {r.description}")
    click.echo(f"  Duration:    ~{r.estimated_duration_s}s")
    click.echo()

    if not r.parameters:
        click.echo("  No configurable parameters.")
        return

    click.echo(click.style("Parameters:", bold=True))
    click.echo(f"  {'Name':<20} {'Type':<8} {'Default':<12} {'Range':<16} {'Description'}")
    click.echo(click.style("  " + "-" * 76, fg="bright_black"))

    for p in r.parameters:
        range_str = _format_param_range(p)
        default_str = str(p.default) if p.default is not None else "-"
        if p.unit:
            default_str += f" {p.unit}"
        click.echo(
            f"  {p.name:<20} {p.param_type:<8} {default_str:<12} {range_str:<16} {p.description}"
        )


def _format_param_range(param) -> str:
    """Format min/max or choices for display."""
    if param.choices:
        return "{" + ",".join(param.choices) + "}"
    parts: list[str] = []
    if param.min_value is not None:
        parts.append(f">={param.min_value}")
    if param.max_value is not None:
        parts.append(f"<={param.max_value}")
    if parts:
        result = " ".join(parts)
        if param.unit:
            result += f" {param.unit}"
        return result
    return "-"


# ---------------------------------------------------------------------------
# recipe run <recipe_id> <device_index>
# ---------------------------------------------------------------------------


@recipe.command()
@click.argument("recipe_id")
@click.argument("device_index", type=int, default=0)
@click.option(
    "--transport",
    type=click.Choice(["uart", "sdb", "pcie"]),
    default="pcie",
)
@click.option("--port", type=int, default=0)
@click.option(
    "--param",
    "-p",
    multiple=True,
    help="Parameter as key=value (repeatable)",
)
@click.pass_context
def run(
    ctx: click.Context,
    recipe_id: str,
    device_index: int,
    transport: str,
    port: int,
    param: tuple[str, ...],
) -> None:
    """Run a validation recipe against a device.

    Parameters are passed with -p key=value, e.g.:

        calypso recipe run all_port_sweep 0 -p timeout_s=10 -p include_disabled=true
    """
    from calypso.core.switch import SwitchDevice
    from calypso.workflows import get_recipe
    from calypso.workflows.workflow_executor import run_single_recipe

    r = get_recipe(recipe_id)
    if r is None:
        click.echo(f"Unknown recipe: {recipe_id}", err=True)
        ctx.exit(1)
        return

    # Parse --param key=value options and coerce types
    kwargs = _parse_param_options(param, r.parameters)

    _init_sdk()
    t = _make_transport_cli(transport, port)

    with SwitchDevice(t) as sw:
        sw.open(device_index)

        device_id = f"cli-{device_index}"

        click.echo(
            click.style(f"Running recipe: {r.name}", bold=True)
            + click.style(f" ({recipe_id})", fg="bright_black")
        )
        if kwargs:
            click.echo(f"  Parameters: {kwargs}")
        click.echo()

        try:
            summary = run_single_recipe(
                recipe_id,
                sw._device_obj,
                sw._device_key,
                device_id,
                **kwargs,
            )
        except Exception as exc:
            click.echo(click.style(f"Recipe execution failed: {exc}", fg="red"), err=True)
            ctx.exit(1)
            return

        # Print formatted results
        from calypso.cli.monitor_format import format_summary_table

        click.echo(format_summary_table(summary))

        # Exit with non-zero on failure
        if summary.status in ("fail", "error"):
            ctx.exit(1)


# ---------------------------------------------------------------------------
# recipe list-workflows
# ---------------------------------------------------------------------------


@recipe.command("list-workflows")
def list_workflows_cmd() -> None:
    """List all saved workflows."""
    from calypso.workflows.workflow_storage import list_workflows

    workflows = list_workflows()
    if not workflows:
        click.echo("No saved workflows found.")
        return

    click.echo(click.style("Saved Workflows", bold=True))
    click.echo(click.style("-" * 60, fg="bright_black"))
    click.echo(f"  {'ID':<12} {'Name':<25} {'Recipes':<8} {'Tags'}")
    click.echo(click.style("  " + "-" * 56, fg="bright_black"))

    for wf in workflows:
        tags = ", ".join(wf.tags) if wf.tags else "-"
        click.echo(f"  {wf.workflow_id:<12} {wf.name:<25} {wf.recipe_count:<8} {tags}")


# ---------------------------------------------------------------------------
# recipe run-workflow <workflow_id> <device_index>
# ---------------------------------------------------------------------------


@recipe.command("run-workflow")
@click.argument("workflow_id")
@click.argument("device_index", type=int, default=0)
@click.option(
    "--transport",
    type=click.Choice(["uart", "sdb", "pcie"]),
    default="pcie",
)
@click.option("--port", type=int, default=0)
@click.pass_context
def run_workflow(
    ctx: click.Context,
    workflow_id: str,
    device_index: int,
    transport: str,
    port: int,
) -> None:
    """Run a saved workflow against a device."""
    from calypso.core.switch import SwitchDevice
    from calypso.workflows.workflow_executor import WorkflowExecutor
    from calypso.workflows.workflow_storage import load_workflow

    workflow = load_workflow(workflow_id)
    if workflow is None:
        click.echo(f"Workflow not found: {workflow_id}", err=True)
        ctx.exit(1)
        return

    _init_sdk()
    t = _make_transport_cli(transport, port)

    with SwitchDevice(t) as sw:
        sw.open(device_index)

        device_id = f"cli-{device_index}"

        click.echo(
            click.style(f"Running workflow: {workflow.name}", bold=True)
            + click.style(f" ({workflow_id})", fg="bright_black")
        )
        click.echo(f"  Steps: {workflow.recipe_count} recipes")
        click.echo()

        try:
            executor = WorkflowExecutor(sw._device_obj, sw._device_key, device_id)
            summaries = executor.run(workflow)
        except Exception as exc:
            click.echo(
                click.style(f"Workflow execution failed: {exc}", fg="red"),
                err=True,
            )
            ctx.exit(1)
            return

        # Print per-recipe summaries
        from calypso.cli.monitor_format import format_summary_table, format_workflow_summary

        for summary in summaries:
            click.echo(format_summary_table(summary))
            click.echo()

        # Print workflow-level summary
        click.echo(format_workflow_summary(summaries, workflow.name))

        # Exit with non-zero if any recipe failed
        has_failure = any(s.status in ("fail", "error") for s in summaries)
        if has_failure:
            ctx.exit(1)


# ---------------------------------------------------------------------------
# Parameter parsing helpers
# ---------------------------------------------------------------------------


def _parse_param_options(
    raw_params: tuple[str, ...],
    recipe_params: list,
) -> dict[str, object]:
    """Parse key=value parameter strings and coerce to correct types.

    Uses the recipe's parameter definitions to determine the expected type.
    """
    if not raw_params:
        return {}

    # Build a lookup of parameter definitions by name
    param_defs = {p.name: p for p in recipe_params}
    result: dict[str, object] = {}

    for raw in raw_params:
        if "=" not in raw:
            click.echo(
                f"Invalid parameter format: {raw!r} (expected key=value)",
                err=True,
            )
            raise SystemExit(1)

        key, _, value = raw.partition("=")
        key = key.strip()
        value = value.strip()

        param_def = param_defs.get(key)
        if param_def is None:
            valid_names = ", ".join(param_defs.keys()) if param_defs else "(none)"
            click.echo(
                f"Unknown parameter: {key!r}. Valid parameters: {valid_names}",
                err=True,
            )
            raise SystemExit(1)

        result[key] = _coerce_param_value(key, value, param_def.param_type)

    return result


def _coerce_param_value(name: str, value: str, param_type: str) -> object:
    """Convert a string value to the appropriate Python type."""
    try:
        if param_type == "int":
            return int(value)
        if param_type == "float":
            return float(value)
        if param_type == "bool":
            return value.lower() in ("true", "1", "yes", "on")
        if param_type == "choice":
            return value
        # Default: return as string
        return value
    except (ValueError, TypeError) as exc:
        click.echo(
            f"Invalid value for parameter {name!r}: {value!r} (expected {param_type}): {exc}",
            err=True,
        )
        raise SystemExit(1) from exc
