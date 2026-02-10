"""CLI subcommands for PLX driver management."""

from __future__ import annotations

import json
import sys

import click


def _require_linux(ctx: click.Context) -> bool:
    """Check platform is Linux, emit error and exit if not. Returns True if OK."""
    if sys.platform != "linux":
        click.echo("ERROR: This command is only supported on Linux.")
        click.echo(f"Current platform: {sys.platform}")
        click.echo()
        click.echo("On Windows, the driver and library are prebuilt.")
        ctx.exit(1)
        return False
    return True


def _get_manager(ctx: click.Context):
    """Create a DriverManager, handling FileNotFoundError."""
    from calypso.driver.manager import DriverManager

    try:
        return DriverManager(ctx.obj.get("sdk_dir"))
    except FileNotFoundError as exc:
        click.echo(f"ERROR: {exc}")
        ctx.exit(1)
        return None


@click.group()
@click.option(
    "--sdk-dir",
    envvar="PLX_SDK_DIR",
    default=None,
    help="Path to PLX SDK directory (or set PLX_SDK_DIR env var)",
)
@click.pass_context
def driver(ctx: click.Context, sdk_dir: str | None) -> None:
    """Manage the PLX driver for PCIe transport.

    The PCIe transport requires the PlxSvc driver to be active.
    On Linux, these commands build and load the kernel module.
    On Windows, these commands install and manage the PlxSvc service.
    """
    ctx.ensure_object(dict)
    ctx.obj["sdk_dir"] = sdk_dir


@driver.command()
@click.pass_context
def check(ctx: click.Context) -> None:
    """Check prerequisites for driver installation."""
    mgr = _get_manager(ctx)
    if mgr is None:
        return

    report = mgr.check_prerequisites()

    click.echo("PLX Driver Prerequisites")
    click.echo("=" * 50)

    all_ok = True
    for prereq in report.items:
        icon = "OK" if prereq.satisfied else "MISSING"
        click.echo(f"  [{icon:>7}]  {prereq.name}: {prereq.description}")
        if prereq.detail:
            click.echo(f"             {prereq.detail}")
        if not prereq.satisfied:
            all_ok = False

    click.echo()
    if all_ok:
        click.echo("All prerequisites satisfied. Ready to install.")
    else:
        click.echo("Some prerequisites are missing. See details above.")
        ctx.exit(1)


@driver.command()
@click.option("--library-only", is_flag=True, help="Only build PlxApi.so, skip kernel module")
@click.option("--driver-only", is_flag=True, help="Only build kernel module, skip PlxApi.so")
@click.pass_context
def build(ctx: click.Context, library_only: bool, driver_only: bool) -> None:
    """Build the PlxSvc kernel module and PlxApi shared library (Linux only)."""
    if not _require_linux(ctx):
        return

    if library_only and driver_only:
        click.echo("ERROR: --library-only and --driver-only are mutually exclusive.")
        ctx.exit(1)
        return

    mgr = _get_manager(ctx)
    if mgr is None:
        return

    # Check prerequisites first
    report = mgr.check_prerequisites()
    if not report.all_satisfied:
        click.echo("ERROR: Prerequisites not met. Run 'calypso driver check' for details.")
        ctx.exit(1)
        return

    had_failure = False

    if not library_only:
        click.echo("Building PlxSvc kernel module...")
        result = mgr.build_driver()
        if result.success:
            click.echo(f"  Built: {result.artifact}")
        else:
            click.echo(f"  FAILED: {result.error}")
            if result.output:
                click.echo(f"  Output: {result.output[-500:]}")
            had_failure = True

    if not driver_only:
        click.echo("Building PlxApi shared library...")
        result = mgr.build_library()
        if result.success:
            click.echo(f"  Built: {result.artifact}")
        else:
            click.echo(f"  FAILED: {result.error}")
            if result.output:
                click.echo(f"  Output: {result.output[-500:]}")
            had_failure = True

    if had_failure:
        ctx.exit(1)
    else:
        click.echo()
        click.echo("Build complete. Run 'calypso driver install' to load the module.")


@driver.command()
@click.pass_context
def install(ctx: click.Context) -> None:
    """Install and start the PLX driver (requires elevated privileges)."""
    mgr = _get_manager(ctx)
    if mgr is None:
        return

    if sys.platform == "linux":
        click.echo("Loading PlxSvc kernel module...")
    else:
        click.echo("Installing PlxSvc service...")

    result = mgr.install_driver()

    if result.success:
        click.echo(result.output or "  Driver installed successfully.")
        if sys.platform == "linux":
            status = mgr.get_status()
            if status.device_nodes:
                click.echo("  Device nodes:")
                for node in status.device_nodes:
                    click.echo(f"    {node}")
    else:
        click.echo(f"  FAILED: {result.error}")
        if result.output:
            click.echo(f"  Output: {result.output[-500:]}")
        ctx.exit(1)


@driver.command()
@click.pass_context
def uninstall(ctx: click.Context) -> None:
    """Stop and remove the PLX driver (requires elevated privileges)."""
    mgr = _get_manager(ctx)
    if mgr is None:
        return

    if sys.platform == "linux":
        click.echo("Unloading PlxSvc kernel module...")
    else:
        click.echo("Removing PlxSvc service...")

    result = mgr.uninstall_driver()

    if result.success:
        click.echo(result.output or "  Driver removed successfully.")
    else:
        click.echo(f"  FAILED: {result.error}")
        if result.output:
            click.echo(f"  Output: {result.output[-500:]}")
        ctx.exit(1)


@driver.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show current driver status."""
    mgr = _get_manager(ctx)
    if mgr is None:
        return

    st = mgr.get_status()

    if ctx.obj.get("json_output"):
        click.echo(json.dumps({
            "module_loaded": st.is_loaded,
            "module_name": st.module_name,
            "device_nodes": list(st.device_nodes),
            "sdk_path": st.sdk_path,
            "driver_built": st.driver_built,
            "library_built": st.library_built,
            "service_state": st.service_state,
        }, indent=2))
    else:
        click.echo("PLX Driver Status")
        click.echo("=" * 50)
        click.echo(f"  SDK Path:       {st.sdk_path}")
        click.echo(f"  Driver Built:   {'Yes' if st.driver_built else 'No'}")
        click.echo(f"  Library Built:  {'Yes' if st.library_built else 'No'}")

        if sys.platform == "linux":
            loaded_str = "Loaded" if st.is_loaded else "Not loaded"
            click.echo(f"  Module Status:  {loaded_str}")
            if st.device_nodes:
                click.echo("  Device Nodes:")
                for node in st.device_nodes:
                    click.echo(f"    {node}")
            else:
                click.echo("  Device Nodes:   None")
        elif sys.platform == "win32":
            click.echo(f"  Service State:  {st.service_state}")
        else:
            click.echo(f"  Platform:       {sys.platform} (unsupported)")
