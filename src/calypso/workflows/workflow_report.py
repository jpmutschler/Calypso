"""Self-contained HTML report generator for workflow/recipe results.

Generates a single HTML file with embedded CSS — no external dependencies.
Uses Calypso dark theme colors.
"""

from __future__ import annotations

import html as html_mod
import importlib.metadata
from datetime import datetime, timezone

from calypso.workflows.models import RecipeSummary, StepStatus
from calypso.workflows.report_charts import (
    divider,
    key_value_table,
    metric_card,
    section_header,
    status_badge,
    status_color,
)
from calypso.workflows.report_sections import render_recipe_section


def format_duration(ms: float) -> str:
    """Format milliseconds into a human-readable duration string."""
    if ms >= 60_000:
        return f"{ms / 60_000:.1f}min"
    if ms >= 1000:
        return f"{ms / 1000:.1f}s"
    return f"{ms:.0f}ms"


def generate_report(
    summaries: list[RecipeSummary],
    title: str = "Workflow Report",
    device_id: str = "",
    device_info: dict[str, str] | None = None,
    environment: dict[str, str] | None = None,
) -> str:
    """Generate a self-contained HTML report from recipe summaries.

    Args:
        summaries: List of recipe execution summaries.
        title: Report title.
        device_id: Device identifier for the report header.
        device_info: Optional device identification (chip_type, revision, etc.).
        environment: Optional test environment metadata (OS, SDK version, driver, etc.).

    Returns:
        Complete HTML string.
    """
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    try:
        version = importlib.metadata.version("calypso")
    except importlib.metadata.PackageNotFoundError:
        version = "dev"

    # Compute aggregate stats
    total_pass = sum(s.total_pass for s in summaries)
    total_fail = sum(s.total_fail for s in summaries)
    total_warn = sum(s.total_warn for s in summaries)
    total_duration_ms = sum(s.duration_ms for s in summaries)
    recipe_count = len(summaries)

    if any(s.status in (StepStatus.FAIL, StepStatus.ERROR) for s in summaries):
        overall = StepStatus.FAIL
    elif any(s.status == StepStatus.WARN for s in summaries):
        overall = StepStatus.WARN
    else:
        overall = StepStatus.PASS

    overall_color = status_color(overall.value)

    # Build header section
    header_html = (
        f'<div style="text-align:center; padding:32px 0;">'
        f'<h1 style="color:#00d4ff; font-size:28px; margin:0; letter-spacing:0.1em;">'
        f"CALYPSO</h1>"
        f'<div style="color:#8b949e; font-size:14px; margin-top:8px;">'
        f"Serial Cables Atlas3 PCIe Switch Manager</div>"
        f'<h2 style="color:#e6edf3; font-size:22px; margin-top:16px;">'
        f"{html_mod.escape(title)}</h2>"
        f'<div style="color:#484f58; font-size:12px; margin-top:8px;">'
        f"Generated: {now} | Calypso v{html_mod.escape(version)}"
        f"{f' | Device: {html_mod.escape(device_id)}' if device_id else ''}"
        f"</div>"
        f"</div>"
    )

    # Metrics row
    metrics_html = (
        f'<div style="display:flex; flex-wrap:wrap; justify-content:center; '
        f'gap:8px; margin:16px 0;">'
        f"{metric_card('Overall', overall.value.upper(), overall_color)}"
        f"{metric_card('Recipes', str(recipe_count), '#00d4ff')}"
        f"{metric_card('Pass', str(total_pass), '#3fb950')}"
        f"{metric_card('Fail', str(total_fail), '#f85149')}"
        f"{metric_card('Warn', str(total_warn), '#d29922')}"
        f"{metric_card('Duration', format_duration(total_duration_ms), '#8b949e')}"
        f"</div>"
    )

    # Recipe summary table
    summary_header = section_header("Recipe Summary")
    summary_rows: list[str] = []
    for s in summaries:
        summary_rows.append(
            f"<tr>"
            f'<td style="padding:8px 12px; border-bottom:1px solid #30363d; '
            f'color:#e6edf3; font-size:13px;">{html_mod.escape(s.recipe_name)}</td>'
            f'<td style="padding:8px 12px; border-bottom:1px solid #30363d;">'
            f"{status_badge(s.status.value)}</td>"
            f'<td style="padding:8px 12px; border-bottom:1px solid #30363d; '
            f'color:#8b949e; font-size:13px; text-align:right;">'
            f"{s.total_steps} steps</td>"
            f'<td style="padding:8px 12px; border-bottom:1px solid #30363d; '
            f'color:#8b949e; font-size:13px; text-align:right;">'
            f"{format_duration(s.duration_ms)}</td>"
            f"</tr>"
        )

    summary_table = (
        f'<table style="width:100%; border-collapse:collapse; '
        f'background:#1c2128; border-radius:8px; overflow:hidden;">'
        f"<thead><tr>"
        f'<th style="text-align:left; padding:8px 12px; color:#8b949e; '
        f'font-size:12px; border-bottom:1px solid #30363d;">Recipe</th>'
        f'<th style="text-align:left; padding:8px 12px; color:#8b949e; '
        f'font-size:12px; border-bottom:1px solid #30363d;">Status</th>'
        f'<th style="text-align:right; padding:8px 12px; color:#8b949e; '
        f'font-size:12px; border-bottom:1px solid #30363d;">Steps</th>'
        f'<th style="text-align:right; padding:8px 12px; color:#8b949e; '
        f'font-size:12px; border-bottom:1px solid #30363d;">Duration</th>'
        f"</tr></thead>"
        f"<tbody>{''.join(summary_rows)}</tbody>"
        f"</table>"
    )

    # Device information section
    device_info_html = ""
    if device_info:
        _key_labels = {
            "chip_type": "Chip Type",
            "chip_id": "Chip ID",
            "revision": "Revision",
            "firmware_version": "Firmware Version",
            "bdf": "BDF Address",
            "serial_number": "Serial Number",
        }
        display_data = {_key_labels.get(k, k): v for k, v in device_info.items() if v}
        if display_data:
            device_info_html = key_value_table(display_data, "Device Information")

    # Test environment section
    environment_html = ""
    if environment:
        _env_labels = {
            "os": "Operating System",
            "os_version": "OS Version",
            "python_version": "Python Version",
            "sdk_version": "PLX SDK Version",
            "driver_version": "Driver Version",
            "board_profile": "Board Profile",
            "chip_type": "Chip Type",
            "downstream_bdf": "Downstream BDF",
            "downstream_vendor_id": "Downstream Vendor ID",
            "downstream_device_id": "Downstream Device ID",
        }
        env_display = {_env_labels.get(k, k): v for k, v in environment.items() if v}
        if env_display:
            environment_html = key_value_table(env_display, "Test Environment")

    # Detailed recipe sections
    detail_sections: list[str] = []
    for s in summaries:
        detail_sections.append(divider())
        params_html = _render_parameters(s.parameters)
        detail_sections.append(params_html)
        detail_sections.append(render_recipe_section(s))

    body = (
        f"{header_html}"
        f"{device_info_html}"
        f"{environment_html}"
        f"{metrics_html}"
        f"{divider()}"
        f"{summary_header}"
        f"{summary_table}"
        f"{''.join(detail_sections)}"
    )

    return wrap_html(title, body)


def generate_single_report(
    summary: RecipeSummary,
    device_id: str = "",
    device_info: dict[str, str] | None = None,
    environment: dict[str, str] | None = None,
) -> str:
    """Generate a report for a single recipe run."""
    return generate_report(
        [summary],
        title=f"Recipe Report: {summary.recipe_name}",
        device_id=device_id,
        device_info=device_info,
        environment=environment,
    )


def _format_param_value(value: object) -> str:
    """Format a parameter value for display."""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        # Use reasonable precision: no trailing zeros
        return f"{value:g}"
    return str(value)


def _render_parameters(parameters: dict[str, object]) -> str:
    """Render recipe parameters as a key-value table."""
    if not parameters:
        return ""
    display = {k: _format_param_value(v) for k, v in parameters.items()}
    return key_value_table(display, "Test Parameters")


def wrap_html(title: str, body: str) -> str:
    """Wrap content in a full HTML document with embedded CSS."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:;">
<title>{html_mod.escape(title)} - Calypso</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
    background-color: #0d1117;
    color: #e6edf3;
    line-height: 1.5;
    padding: 24px;
    max-width: 1200px;
    margin: 0 auto;
}}
table {{ border-spacing: 0; }}
.mono {{
    font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
}}
@media print {{
    body {{ background: white; color: #1a1a1a; padding: 12px; }}
    table td, table th {{ color: #1a1a1a !important; }}
    table {{ page-break-inside: auto; }}
    tr {{ page-break-inside: avoid; page-break-after: auto; }}
    thead {{ display: table-header-group; }}
    .recipe-section {{ page-break-before: auto; }}
    h2, h3 {{ page-break-after: avoid; }}
    details {{ page-break-inside: avoid; }}
    @page {{ margin: 15mm; }}
}}
</style>
</head>
<body>
{body}
<div style="text-align:center; margin-top:48px; padding:16px; color:#484f58; font-size:11px;">
    Generated by Calypso - Serial Cables Atlas3 PCIe Switch Manager
</div>
</body>
</html>"""
