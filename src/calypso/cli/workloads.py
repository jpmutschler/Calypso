"""CLI commands for NVMe workload generation."""

from __future__ import annotations

import json
import sys
import time

import click


@click.group()
def workloads() -> None:
    """NVMe workload generation (SPDK perf / pynvme)."""


@workloads.command()
@click.pass_context
def backends(ctx: click.Context) -> None:
    """Show available workload backends."""
    from calypso.workloads import available_backends

    avail = available_backends()
    if ctx.obj.get("json_output"):
        click.echo(json.dumps({"available": avail}))
    else:
        if not avail:
            click.echo("No workload backends available.")
            click.echo("  SPDK:   Install spdk_nvme_perf on PATH")
            click.echo("  pynvme: pip install 'calypso[workloads]' (Linux only)")
        else:
            click.echo("Available backends:")
            for b in avail:
                click.echo(f"  - {b}")


@workloads.command()
@click.option(
    "--bdf", required=True,
    help="PCIe BDF address of target NVMe device (e.g. 0000:01:00.0)",
)
@click.option(
    "--backend", type=click.Choice(["spdk", "pynvme"]),
    help="Backend to validate with (tests both if omitted)",
)
@click.pass_context
def validate(ctx: click.Context, bdf: str, backend: str | None) -> None:
    """Validate that a target NVMe device is accessible."""
    from calypso.workloads.manager import WorkloadManager

    mgr = WorkloadManager()
    results = {}

    for bt in mgr.available_backends:
        if backend is not None and bt.value != backend:
            continue
        results[bt.value] = mgr.validate_target(bt, bdf)

    if ctx.obj.get("json_output"):
        click.echo(json.dumps({"bdf": bdf, "results": results}))
    else:
        if not results:
            click.echo(f"No backends available to validate {bdf}")
        else:
            for name, ok in results.items():
                status = "OK" if ok else "FAILED"
                click.echo(f"  {name}: {status}")


@workloads.command()
@click.option("--backend", type=click.Choice(["spdk", "pynvme"]), required=True)
@click.option("--bdf", required=True, help="PCIe BDF address (e.g. 0000:01:00.0)")
@click.option("--workload", "workload_type", type=click.Choice([
    "randread", "randwrite", "read", "write", "randrw", "rw",
]), default="randread")
@click.option("--io-size", type=int, default=4096, help="I/O size in bytes")
@click.option("--queue-depth", type=int, default=128)
@click.option("--duration", type=int, default=30, help="Duration in seconds")
@click.option("--read-pct", type=int, default=100, help="Read percentage (for randrw/rw)")
@click.option("--workers", type=int, default=1, help="Number of I/O workers")
@click.option("--core-mask", default=None, help="CPU core mask (SPDK only, e.g. 0xFF)")
@click.option(
    "--with-switch-perf", is_flag=True,
    help="Also monitor switch-side performance counters",
)
@click.option("--device-index", type=int, default=0, help="Switch device index (for --with-switch-perf)")
@click.option("--transport", type=click.Choice(["uart", "sdb", "pcie"]), default="pcie")
@click.option("--port", type=int, default=0, help="Serial port number for UART/SDB")
@click.pass_context
def run(
    ctx: click.Context,
    backend: str,
    bdf: str,
    workload_type: str,
    io_size: int,
    queue_depth: int,
    duration: int,
    read_pct: int,
    workers: int,
    core_mask: str | None,
    with_switch_perf: bool,
    device_index: int,
    transport: str,
    port: int,
) -> None:
    """Run an NVMe workload."""
    from calypso.workloads.manager import WorkloadManager
    from calypso.workloads.models import BackendType, WorkloadConfig, WorkloadType

    config = WorkloadConfig(
        backend=BackendType(backend),
        target_bdf=bdf,
        workload_type=WorkloadType(workload_type),
        io_size_bytes=io_size,
        queue_depth=queue_depth,
        duration_seconds=duration,
        read_percentage=read_pct,
        num_workers=workers,
        core_mask=core_mask,
    )

    mgr = WorkloadManager()

    # Optional switch-side perf monitor
    switch_monitor = None
    switch_device = None
    if with_switch_perf:
        switch_monitor, switch_device = _setup_switch_monitor(transport, port, device_index)

    workload_id = None
    try:
        status = mgr.start_workload(config)
        workload_id = status.workload_id
        click.echo(f"Workload started: {workload_id}")
        click.echo(f"  Backend: {backend}, BDF: {bdf}")
        click.echo(f"  Type: {workload_type}, IO size: {io_size}B, QD: {queue_depth}")
        click.echo(f"  Duration: {duration}s, Workers: {workers}")
        click.echo()

        # Poll progress
        _poll_progress(
            mgr, workload_id, duration,
            switch_monitor=switch_monitor,
            json_output=ctx.obj.get("json_output", False),
        )

        # Final result
        final = mgr.get_status(workload_id)
        click.echo()

        if ctx.obj.get("json_output"):
            click.echo(json.dumps(final.model_dump(), indent=2, default=str))
        else:
            _print_result(final)

    except KeyboardInterrupt:
        click.echo("\nStopping workload...")
        if workload_id is not None:
            try:
                mgr.stop_workload(workload_id)
            except Exception:
                pass
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    finally:
        mgr.shutdown()
        if switch_monitor is not None:
            try:
                switch_monitor.stop()
            except Exception:
                pass
        if switch_device is not None:
            try:
                switch_device.close()
            except Exception:
                pass


def _setup_switch_monitor(transport: str, port: int, device_index: int):
    """Create a PerfMonitor for switch-side metrics."""
    from calypso.bindings.library import load_library
    from calypso.bindings.functions import initialize
    from calypso.core.perf_monitor import PerfMonitor
    from calypso.core.switch import SwitchDevice
    from calypso.cli.main import _make_transport

    load_library()
    initialize()

    t = _make_transport(transport, port)
    sw = SwitchDevice(t)
    sw.open(device_index)

    monitor = PerfMonitor(sw._device_obj, sw._device_key)
    monitor.start()
    return monitor, sw


def _poll_progress(
    mgr,
    workload_id: str,
    duration: int,
    switch_monitor=None,
    json_output: bool = False,
) -> None:
    """Poll and display workload progress until completion."""
    from calypso.workloads.models import WorkloadState

    while True:
        time.sleep(1.0)
        try:
            status = mgr.get_status(workload_id)
        except Exception:
            break

        if status.state not in (WorkloadState.PENDING, WorkloadState.RUNNING):
            break

        if status.progress is not None:
            prog = status.progress
            pct = (
                prog.elapsed_seconds / prog.total_seconds * 100
                if prog.total_seconds > 0 else 0
            )

            line = (
                f"\r  [{pct:5.1f}%] "
                f"{prog.elapsed_seconds:.0f}/{prog.total_seconds:.0f}s  "
                f"IOPS: {prog.current_iops:,.0f}  "
                f"BW: {prog.current_bandwidth_mbps:,.1f} MB/s"
            )

            if switch_monitor is not None:
                try:
                    snap = switch_monitor.read_snapshot()
                    total_in = sum(
                        ps.ingress_payload_byte_rate for ps in snap.port_stats
                    ) / (1024 * 1024)
                    total_out = sum(
                        ps.egress_payload_byte_rate for ps in snap.port_stats
                    ) / (1024 * 1024)
                    line += f"  | Switch In: {total_in:.1f} MB/s Out: {total_out:.1f} MB/s"
                except Exception:
                    pass

            click.echo(line, nl=False)

    click.echo()  # newline after progress


def _print_result(status) -> None:
    """Pretty-print a final workload result."""
    click.echo(f"Workload {status.workload_id}: {status.state.value}")

    if status.result is not None and status.result.stats is not None:
        s = status.result.stats
        click.echo(f"  Duration:   {status.result.duration_ms:.0f} ms")
        click.echo(f"  IOPS:       {s.iops_total:>12,.0f} total")
        click.echo(f"              {s.iops_read:>12,.0f} read")
        click.echo(f"              {s.iops_write:>12,.0f} write")
        click.echo(f"  Bandwidth:  {s.bandwidth_total_mbps:>10,.1f} MB/s total")
        click.echo(f"              {s.bandwidth_read_mbps:>10,.1f} MB/s read")
        click.echo(f"              {s.bandwidth_write_mbps:>10,.1f} MB/s write")
        click.echo(f"  Latency:    avg={s.latency_avg_us:.1f}us  max={s.latency_max_us:.1f}us")
        if s.latency_p50_us > 0 or s.latency_p99_us > 0:
            click.echo(
                f"              p50={s.latency_p50_us:.1f}us  "
                f"p99={s.latency_p99_us:.1f}us  "
                f"p999={s.latency_p999_us:.1f}us"
            )
        if s.cpu_usage_percent > 0:
            click.echo(f"  CPU:        {s.cpu_usage_percent:.1f}%")

    if status.result is not None and status.result.error:
        click.echo(f"  Error: {status.result.error}")
