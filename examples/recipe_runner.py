"""Standalone CLI script for running Calypso validation recipes.

Demonstrates the recipe generator protocol: each recipe yields
RecipeResult objects as it progresses through steps, then returns
a final RecipeSummary via StopIteration.value.

Usage examples:
    # List all available recipes
    python recipe_runner.py --list

    # Show parameters for a specific recipe
    python recipe_runner.py --params port_sweep

    # Run a recipe on device index 0
    python recipe_runner.py port_sweep 0

    # Run with custom parameters
    python recipe_runner.py ber_soak 0 --param duration_s=60 --param target_ber=1e-12
"""

from __future__ import annotations

import argparse
import sys

from calypso.core.switch import SwitchDevice
from calypso.transport.pcie import PcieTransport
from calypso.utils.logging import get_logger
from calypso.workflows import get_all_recipes, get_recipe
from calypso.workflows.models import (
    RecipeCategory,
    RecipeParameter,
    RecipeResult,
    RecipeSummary,
    StepStatus,
)

logger = get_logger(__name__)

# Status symbols for terminal output
STATUS_SYMBOLS: dict[StepStatus, str] = {
    StepStatus.PASS: "[PASS]",
    StepStatus.FAIL: "[FAIL]",
    StepStatus.WARN: "[WARN]",
    StepStatus.SKIP: "[SKIP]",
    StepStatus.ERROR: "[ERR ]",
    StepStatus.RUNNING: "[....]",
    StepStatus.PENDING: "[    ]",
}


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the recipe runner CLI."""
    parser = argparse.ArgumentParser(
        description="Run Calypso validation recipes on Atlas3 PCIe switches.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  %(prog)s --list\n"
            "  %(prog)s --params port_sweep\n"
            "  %(prog)s port_sweep 0\n"
            "  %(prog)s ber_soak 0 --param duration_s=60\n"
        ),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available recipes and exit.",
    )
    parser.add_argument(
        "--params",
        metavar="RECIPE_ID",
        help="Show configurable parameters for a recipe and exit.",
    )
    parser.add_argument(
        "recipe_id",
        nargs="?",
        help="Recipe ID to run (see --list for available recipes).",
    )
    parser.add_argument(
        "device_index",
        nargs="?",
        type=int,
        default=0,
        help="Device index from discovery scan (default: 0).",
    )
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Recipe parameter as key=value (repeatable).",
    )
    return parser


def list_recipes() -> None:
    """Print all registered recipes grouped by category."""
    recipes = get_all_recipes()
    if not recipes:
        print("No recipes registered.")
        return

    # Group recipes by category without mutating the original list
    by_category: dict[RecipeCategory, list] = {}
    for recipe in recipes:
        group = by_category.setdefault(recipe.category, [])
        by_category[recipe.category] = [*group, recipe]

    print(f"\nAvailable recipes ({len(recipes)} total):\n")
    for category in RecipeCategory:
        group = by_category.get(category, [])
        if not group:
            continue
        print(f"  {category.value.upper().replace('_', ' ')}")
        print(f"  {'=' * 40}")
        for recipe in sorted(group, key=lambda r: r.recipe_id):
            est = f"~{recipe.estimated_duration_s}s"
            print(f"    {recipe.recipe_id:<30s} {est:>6s}  {recipe.name}")
            print(f"    {'':30s}        {recipe.description}")
        print()


def show_params(recipe_id: str) -> None:
    """Print the configurable parameters for a recipe."""
    recipe = get_recipe(recipe_id)
    if recipe is None:
        print(f"Error: recipe '{recipe_id}' not found. Use --list to see options.")
        sys.exit(1)

    print(f"\nRecipe: {recipe.name} ({recipe.recipe_id})")
    print(f"Category: {recipe.category.value}")
    print(f"Description: {recipe.description}")
    print(f"Estimated duration: ~{recipe.estimated_duration_s}s\n")

    params: list[RecipeParameter] = recipe.parameters
    if not params:
        print("  No configurable parameters.")
        return

    print(f"  {'Name':<20s} {'Type':<8s} {'Default':<12s} {'Description'}")
    print(f"  {'-' * 20} {'-' * 8} {'-' * 12} {'-' * 30}")
    for p in params:
        default_str = str(p.default) if p.default is not None else "-"
        unit_suffix = f" ({p.unit})" if p.unit else ""
        range_info = ""
        if p.min_value is not None or p.max_value is not None:
            lo = str(p.min_value) if p.min_value is not None else ""
            hi = str(p.max_value) if p.max_value is not None else ""
            range_info = f" [{lo}..{hi}]"
        if p.choices:
            range_info = f" choices: {', '.join(p.choices)}"
        desc = f"{p.description}{unit_suffix}{range_info}"
        print(f"  {p.name:<20s} {p.param_type:<8s} {default_str:<12s} {desc}")
    print()


def parse_param_args(raw_params: list[str]) -> dict[str, str]:
    """Parse --param KEY=VALUE arguments into a dictionary.

    Returns string values; the recipe will handle type coercion internally.
    """
    parsed: dict[str, str] = {}
    for item in raw_params:
        if "=" not in item:
            print(f"Error: invalid parameter format '{item}' (expected KEY=VALUE).")
            sys.exit(1)
        key, _, value = item.partition("=")
        parsed = {**parsed, key.strip(): value.strip()}
    return parsed


def print_step_result(result: RecipeResult) -> None:
    """Print a single recipe step result to stdout."""
    symbol = STATUS_SYMBOLS.get(result.status, "[????]")
    port_info = ""
    if result.port_number is not None:
        port_info = f" port={result.port_number}"
        if result.lane is not None:
            port_info += f" lane={result.lane}"
    duration_info = ""
    if result.duration_ms > 0:
        duration_info = f" ({result.duration_ms:.1f}ms)"
    print(f"  {symbol} {result.step_name}{port_info}{duration_info}")
    if result.message and result.status != StepStatus.RUNNING:
        print(f"         {result.message}")
    if result.measured_values:
        for key, val in result.measured_values.items():
            print(f"           {key}: {val}")


def print_summary(summary: RecipeSummary) -> None:
    """Print the final recipe summary."""
    status_label = summary.status.value.upper()
    print(f"\n{'=' * 60}")
    print(f"  Recipe:   {summary.recipe_name} ({summary.recipe_id})")
    print(f"  Status:   {status_label}")
    print(f"  Duration: {summary.duration_ms:.1f}ms")
    print(f"  Steps:    {summary.total_steps} total")
    print(
        f"    PASS={summary.total_pass}  FAIL={summary.total_fail}  "
        f"WARN={summary.total_warn}  SKIP={summary.total_skip}  "
        f"ERROR={summary.total_error}"
    )
    print(f"  Pass rate: {summary.pass_rate}%")
    if summary.parameters:
        print(f"  Parameters: {summary.parameters}")
    print(f"{'=' * 60}\n")


def run_recipe(recipe_id: str, device_index: int, params: dict[str, str]) -> int:
    """Open a device, run the recipe, and print results.

    Returns 0 on overall PASS/WARN, 1 on FAIL/ERROR.
    """
    recipe = get_recipe(recipe_id)
    if recipe is None:
        print(f"Error: recipe '{recipe_id}' not found. Use --list to see options.")
        return 1

    print(f"\nRunning recipe: {recipe.name}")
    print(f"Device index:   {device_index}")
    if params:
        print(f"Parameters:     {params}")
    print(f"{'-' * 60}")

    # Open the device via PCIe transport and context manager
    transport = PcieTransport()
    device = SwitchDevice(transport)
    try:
        device.open(device_index)
    except Exception as exc:
        logger.exception("device_open_failed")
        print(f"Error: failed to open device {device_index}: {exc}")
        return 1

    try:
        dev_obj = device._require_open()
        dev_key = device.device_key
        if dev_obj is None or dev_key is None:
            print("Error: device opened but internal objects are None.")
            return 1

        # Cancellation flag — recipes check this dict to support early abort
        cancel: dict[str, bool] = {"cancelled": False}

        # Run the recipe generator and iterate over yielded step results.
        # The generator returns RecipeSummary via StopIteration.value.
        gen = recipe.run(dev_obj, dev_key, cancel, **params)
        summary: RecipeSummary | None = None

        while True:
            try:
                result = next(gen)
                print_step_result(result)
            except StopIteration as stop:
                summary = stop.value
                break
            except KeyboardInterrupt:
                print("\n  Cancellation requested...")
                cancel["cancelled"] = True
                # Drain remaining results after cancellation
                try:
                    while True:
                        result = next(gen)
                        print_step_result(result)
                except StopIteration as stop:
                    summary = stop.value

        if summary is not None:
            print_summary(summary)
            if summary.status in (StepStatus.FAIL, StepStatus.ERROR):
                return 1
            return 0

        print("Warning: recipe completed without returning a summary.")
        return 1

    except Exception as exc:
        logger.exception("recipe_execution_failed")
        print(f"Error: recipe execution failed: {exc}")
        return 1
    finally:
        device.close()


def main() -> None:
    """Entry point for the recipe runner CLI."""
    parser = build_parser()
    args = parser.parse_args()

    # Handle --list mode
    if args.list:
        list_recipes()
        return

    # Handle --params mode
    if args.params:
        show_params(args.params)
        return

    # Run mode requires a recipe ID
    if not args.recipe_id:
        parser.print_help()
        sys.exit(1)

    params = parse_param_args(args.param)
    exit_code = run_recipe(args.recipe_id, args.device_index, params)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
