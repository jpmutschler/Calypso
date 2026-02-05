"""PCIe config space and link management CLI commands."""

from __future__ import annotations

import json

import click


@click.group()
def pcie():
    """PCIe config space and link management."""
    pass


@pcie.command("config-space")
@click.argument("device_index", type=int, default=0)
@click.option("--offset", type=int, default=0, help="Starting DWORD offset")
@click.option("--count", type=int, default=64, help="Number of DWORDs to read")
@click.option("--transport", type=click.Choice(["uart", "sdb", "pcie"]), default="pcie")
@click.option("--port", type=int, default=0)
@click.pass_context
def config_space(
    ctx: click.Context, device_index: int, offset: int, count: int, transport: str, port: int
) -> None:
    """Dump PCIe config space registers."""
    from calypso.bindings.library import load_library
    from calypso.bindings.functions import initialize
    from calypso.core.pcie_config import PcieConfigReader
    from calypso.core.switch import SwitchDevice

    load_library()
    initialize()

    from calypso.cli.main import _make_transport
    t = _make_transport(transport, port)

    with SwitchDevice(t) as sw:
        sw.open(device_index)
        reader = PcieConfigReader(sw._device_obj, sw._device_key)
        registers = reader.dump_config_space(offset=offset, count=count)

        if ctx.obj.get("json_output"):
            click.echo(json.dumps([r.model_dump() for r in registers], indent=2))
        else:
            click.echo(f"Config Space (offset=0x{offset:X}, count={count}):")
            for i in range(0, len(registers), 4):
                row_offset = registers[i].offset
                vals = " ".join(f"{r.value:08X}" for r in registers[i:i+4])
                click.echo(f"  0x{row_offset:03X}: {vals}")


@pcie.command("caps")
@click.argument("device_index", type=int, default=0)
@click.option("--transport", type=click.Choice(["uart", "sdb", "pcie"]), default="pcie")
@click.option("--port", type=int, default=0)
@click.pass_context
def caps(ctx: click.Context, device_index: int, transport: str, port: int) -> None:
    """List all PCI/PCIe capabilities."""
    from calypso.bindings.library import load_library
    from calypso.bindings.functions import initialize
    from calypso.core.pcie_config import PcieConfigReader
    from calypso.core.switch import SwitchDevice

    load_library()
    initialize()

    from calypso.cli.main import _make_transport
    t = _make_transport(transport, port)

    with SwitchDevice(t) as sw:
        sw.open(device_index)
        reader = PcieConfigReader(sw._device_obj, sw._device_key)
        std_caps = reader.walk_capabilities()
        ext_caps = reader.walk_extended_capabilities()

        if ctx.obj.get("json_output"):
            all_caps = std_caps + ext_caps
            click.echo(json.dumps([c.model_dump() for c in all_caps], indent=2))
        else:
            click.echo("Standard Capabilities:")
            for c in std_caps:
                click.echo(f"  [0x{c.offset:02X}] ID=0x{c.cap_id:02X} {c.cap_name}")
            if ext_caps:
                click.echo("\nExtended Capabilities:")
                for c in ext_caps:
                    click.echo(
                        f"  [0x{c.offset:03X}] ID=0x{c.cap_id:04X} {c.cap_name} v{c.version}"
                    )


@pcie.command("aer")
@click.argument("device_index", type=int, default=0)
@click.option("--clear", is_flag=True, help="Clear AER error registers")
@click.option("--transport", type=click.Choice(["uart", "sdb", "pcie"]), default="pcie")
@click.option("--port", type=int, default=0)
@click.pass_context
def aer(
    ctx: click.Context, device_index: int, clear: bool, transport: str, port: int
) -> None:
    """Show or clear AER error status."""
    from calypso.bindings.library import load_library
    from calypso.bindings.functions import initialize
    from calypso.core.pcie_config import PcieConfigReader
    from calypso.core.switch import SwitchDevice

    load_library()
    initialize()

    from calypso.cli.main import _make_transport
    t = _make_transport(transport, port)

    with SwitchDevice(t) as sw:
        sw.open(device_index)
        reader = PcieConfigReader(sw._device_obj, sw._device_key)

        if clear:
            reader.clear_aer_errors()
            click.echo("AER errors cleared.")
            return

        status = reader.get_aer_status()
        if status is None:
            click.echo("AER capability not found.")
            return

        if ctx.obj.get("json_output"):
            click.echo(json.dumps(status.model_dump(), indent=2))
        else:
            click.echo(f"AER Status (offset=0x{status.aer_offset:X}):")
            click.echo(f"  First Error Pointer: {status.first_error_pointer}")
            click.echo(f"\n  Uncorrectable (raw=0x{status.uncorrectable.raw_value:08X}):")
            for field_name in [
                "data_link_protocol", "surprise_down", "poisoned_tlp",
                "flow_control_protocol", "completion_timeout", "completer_abort",
                "unexpected_completion", "receiver_overflow", "malformed_tlp",
                "ecrc_error", "unsupported_request", "acs_violation",
            ]:
                val = getattr(status.uncorrectable, field_name)
                marker = "!!" if val else "  "
                click.echo(f"    {marker} {field_name}: {val}")

            click.echo(f"\n  Correctable (raw=0x{status.correctable.raw_value:08X}):")
            for field_name in [
                "receiver_error", "bad_tlp", "bad_dllp",
                "replay_num_rollover", "replay_timer_timeout", "advisory_non_fatal",
            ]:
                val = getattr(status.correctable, field_name)
                marker = "!!" if val else "  "
                click.echo(f"    {marker} {field_name}: {val}")

            click.echo(f"\n  Header Log: {' '.join(f'0x{h:08X}' for h in status.header_log)}")


@pcie.command("link")
@click.argument("device_index", type=int, default=0)
@click.option("--transport", type=click.Choice(["uart", "sdb", "pcie"]), default="pcie")
@click.option("--port", type=int, default=0)
@click.pass_context
def link(ctx: click.Context, device_index: int, transport: str, port: int) -> None:
    """Show link capabilities and status."""
    from calypso.bindings.library import load_library
    from calypso.bindings.functions import initialize
    from calypso.core.pcie_config import PcieConfigReader
    from calypso.core.switch import SwitchDevice

    load_library()
    initialize()

    from calypso.cli.main import _make_transport
    t = _make_transport(transport, port)

    with SwitchDevice(t) as sw:
        sw.open(device_index)
        reader = PcieConfigReader(sw._device_obj, sw._device_key)
        link_cap = reader.get_link_capabilities()
        link_status = reader.get_link_status()

        if ctx.obj.get("json_output"):
            click.echo(json.dumps({
                "capabilities": link_cap.model_dump(),
                "status": link_status.model_dump(),
            }, indent=2))
        else:
            click.echo("Link Capabilities:")
            click.echo(f"  Max Speed: {link_cap.max_link_speed}")
            click.echo(f"  Max Width: x{link_cap.max_link_width}")
            click.echo(f"  ASPM Support: {link_cap.aspm_support}")
            click.echo(f"  Port Number: {link_cap.port_number}")
            click.echo(f"  DLL Active Capable: {link_cap.dll_link_active_capable}")
            click.echo(f"  Surprise Down Capable: {link_cap.surprise_down_capable}")
            click.echo("\nLink Status:")
            click.echo(f"  Current Speed: {link_status.current_speed}")
            click.echo(f"  Current Width: x{link_status.current_width}")
            click.echo(f"  Target Speed: {link_status.target_speed}")
            click.echo(f"  ASPM Control: {link_status.aspm_control}")
            click.echo(f"  Link Training: {link_status.link_training}")
            click.echo(f"  DLL Active: {link_status.dll_link_active}")


@pcie.command("retrain")
@click.argument("device_index", type=int, default=0)
@click.option("--transport", type=click.Choice(["uart", "sdb", "pcie"]), default="pcie")
@click.option("--port", type=int, default=0)
def retrain(device_index: int, transport: str, port: int) -> None:
    """Initiate link retraining."""
    from calypso.bindings.library import load_library
    from calypso.bindings.functions import initialize
    from calypso.core.pcie_config import PcieConfigReader
    from calypso.core.switch import SwitchDevice

    load_library()
    initialize()

    from calypso.cli.main import _make_transport
    t = _make_transport(transport, port)

    with SwitchDevice(t) as sw:
        sw.open(device_index)
        reader = PcieConfigReader(sw._device_obj, sw._device_key)
        reader.retrain_link()
        click.echo("Link retraining initiated.")


@pcie.command("set-speed")
@click.argument("device_index", type=int, default=0)
@click.option(
    "--speed",
    type=click.Choice(["1", "2", "3", "4", "5", "6"]),
    required=True,
    help="Target speed: 1=Gen1, 2=Gen2, ... 6=Gen6",
)
@click.option("--transport", type=click.Choice(["uart", "sdb", "pcie"]), default="pcie")
@click.option("--port", type=int, default=0)
def set_speed(device_index: int, speed: str, transport: str, port: int) -> None:
    """Set target link speed."""
    from calypso.bindings.library import load_library
    from calypso.bindings.functions import initialize
    from calypso.core.pcie_config import PcieConfigReader
    from calypso.core.switch import SwitchDevice

    load_library()
    initialize()

    from calypso.cli.main import _make_transport
    t = _make_transport(transport, port)

    speed_int = int(speed)
    speed_names = {1: "Gen1", 2: "Gen2", 3: "Gen3", 4: "Gen4", 5: "Gen5", 6: "Gen6"}

    with SwitchDevice(t) as sw:
        sw.open(device_index)
        reader = PcieConfigReader(sw._device_obj, sw._device_key)
        reader.set_target_link_speed(speed_int)
        click.echo(f"Target link speed set to {speed_names[speed_int]}.")


@pcie.command("device-control")
@click.argument("device_index", type=int, default=0)
@click.option("--mps", type=click.Choice(["128", "256", "512", "1024", "2048", "4096"]), default=None)
@click.option("--mrrs", type=click.Choice(["128", "256", "512", "1024", "2048", "4096"]), default=None)
@click.option("--transport", type=click.Choice(["uart", "sdb", "pcie"]), default="pcie")
@click.option("--port", type=int, default=0)
@click.pass_context
def device_control(
    ctx: click.Context, device_index: int, mps: str | None, mrrs: str | None,
    transport: str, port: int
) -> None:
    """Show or set device control (MPS/MRRS)."""
    from calypso.bindings.library import load_library
    from calypso.bindings.functions import initialize
    from calypso.core.pcie_config import PcieConfigReader
    from calypso.core.switch import SwitchDevice

    load_library()
    initialize()

    from calypso.cli.main import _make_transport
    t = _make_transport(transport, port)

    with SwitchDevice(t) as sw:
        sw.open(device_index)
        reader = PcieConfigReader(sw._device_obj, sw._device_key)

        if mps is not None or mrrs is not None:
            mps_val = int(mps) if mps else None
            mrrs_val = int(mrrs) if mrrs else None
            status = reader.set_device_control(mps=mps_val, mrrs=mrrs_val)
            click.echo("Device control updated.")
        else:
            status = reader.get_device_control()

        if ctx.obj.get("json_output"):
            click.echo(json.dumps(status.model_dump(), indent=2))
        else:
            click.echo("Device Control:")
            click.echo(f"  Max Payload Size: {status.max_payload_size} bytes")
            click.echo(f"  Max Read Request Size: {status.max_read_request_size} bytes")
            click.echo(f"  Relaxed Ordering: {status.relaxed_ordering}")
            click.echo(f"  No Snoop: {status.no_snoop}")
            click.echo(f"  Extended Tag: {status.extended_tag_enabled}")
            click.echo(f"  Correctable Error Reporting: {status.correctable_error_reporting}")
            click.echo(f"  Non-Fatal Error Reporting: {status.non_fatal_error_reporting}")
            click.echo(f"  Fatal Error Reporting: {status.fatal_error_reporting}")
            click.echo(f"  Unsupported Request Reporting: {status.unsupported_request_reporting}")
