"""Standalone HTML compliance report generator.

Produces a self-contained HTML file with inline CSS and SVG charts.
No external dependencies required to view the report.
"""

from __future__ import annotations

import html

from calypso.compliance.models import TestRun, TestSuiteResult

# Dark theme colours matching Calypso UI
_BG = "#0d1117"
_BG2 = "#161b22"
_TEXT = "#e6edf3"
_TEXT2 = "#8b949e"
_BORDER = "#30363d"
_CYAN = "#00d4ff"
_GREEN = "#3fb950"
_RED = "#f85149"
_YELLOW = "#d29922"
_GRAY = "#484f58"

_VERDICT_COLORS: dict[str, str] = {
    "pass": _GREEN,
    "fail": _RED,
    "warn": _YELLOW,
    "skip": _GRAY,
    "error": _RED,
}


def generate_report(run: TestRun) -> str:
    """Generate a complete standalone HTML compliance report."""
    sections = [
        _css(),
        _header(run),
        _executive_summary(run),
    ]

    for suite in run.suites:
        sections.append(_suite_section(suite))

    if run.eye_data:
        sections.append(_signal_integrity_charts(run))

    if run.ber_data:
        sections.append(_ber_results_table(run))

    sections.append(_footer(run))

    body = "\n".join(sections)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PCIe Compliance Test Report - {_esc(run.device.device_id)}</title>
{_css()}
</head>
<body>
{body}
</body>
</html>"""


def _css() -> str:
    return f"""<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    background: {_BG};
    color: {_TEXT};
    font-family: 'JetBrains Mono', 'Consolas', 'Courier New', monospace;
    font-size: 14px;
    line-height: 1.6;
    padding: 32px;
    max-width: 1200px;
    margin: 0 auto;
}}
h1 {{ color: {_CYAN}; font-size: 24px; margin-bottom: 8px; }}
h2 {{ color: {_TEXT}; font-size: 18px; margin: 24px 0 12px 0; border-bottom: 1px solid {_BORDER}; padding-bottom: 6px; }}
h3 {{ color: {_TEXT2}; font-size: 15px; margin: 16px 0 8px 0; }}
.card {{
    background: {_BG2};
    border: 1px solid {_BORDER};
    border-radius: 8px;
    padding: 20px;
    margin-bottom: 16px;
}}
.info-table {{ width: 100%; border-collapse: collapse; margin: 8px 0; }}
.info-table td {{ padding: 4px 12px 4px 0; }}
.info-table td:first-child {{ color: {_TEXT2}; white-space: nowrap; width: 160px; }}
.results-table {{ width: 100%; border-collapse: collapse; margin: 8px 0; }}
.results-table th {{
    text-align: left; padding: 8px 12px;
    background: {_BG}; color: {_TEXT2};
    border-bottom: 2px solid {_BORDER};
    font-size: 12px; text-transform: uppercase;
}}
.results-table td {{
    padding: 6px 12px;
    border-bottom: 1px solid {_BORDER};
    font-size: 13px;
}}
.verdict-badge {{
    display: inline-block; padding: 2px 10px;
    border-radius: 12px; font-size: 12px;
    font-weight: bold; text-transform: uppercase;
}}
.summary-bar {{ display: flex; gap: 16px; flex-wrap: wrap; margin: 12px 0; }}
.summary-stat {{
    display: flex; flex-direction: column;
    align-items: center; min-width: 80px;
}}
.summary-stat .value {{ font-size: 28px; font-weight: bold; }}
.summary-stat .label {{ font-size: 11px; color: {_TEXT2}; text-transform: uppercase; }}
.chart-container {{ margin: 12px 0; }}
.footer {{
    margin-top: 32px; padding-top: 16px;
    border-top: 1px solid {_BORDER};
    color: {_TEXT2}; font-size: 12px;
    text-align: center;
}}
</style>"""


def _header(run: TestRun) -> str:
    d = run.device
    return f"""<div class="card">
<h1>PCIe Compliance Test Report</h1>
<table class="info-table">
<tr><td>Device ID</td><td>{_esc(d.device_id)}</td></tr>
<tr><td>Description</td><td>{_esc(d.description)}</td></tr>
<tr><td>Vendor / Device</td><td>{_esc(d.vendor_id)} / {_esc(d.device_id_hex)}</td></tr>
<tr><td>Chip Revision</td><td>{_esc(d.chip_revision)}</td></tr>
<tr><td>Timestamp</td><td>{_esc(d.timestamp)}</td></tr>
<tr><td>Run ID</td><td>{_esc(run.run_id)}</td></tr>
<tr><td>Duration</td><td>{run.duration_ms / 1000:.1f}s</td></tr>
</table>
</div>"""


def _executive_summary(run: TestRun) -> str:
    verdict_color = _VERDICT_COLORS.get(run.overall_verdict.value, _GRAY)
    total = run.total_pass + run.total_fail + run.total_warn + run.total_skip + run.total_error

    # Summary bar SVG
    bar_width = 600
    segments = []
    offset = 0
    for count, color in [
        (run.total_pass, _GREEN),
        (run.total_warn, _YELLOW),
        (run.total_fail, _RED),
        (run.total_error, _RED),
        (run.total_skip, _GRAY),
    ]:
        if count > 0 and total > 0:
            w = (count / total) * bar_width
            segments.append(f'<rect x="{offset}" y="0" width="{w}" height="20" fill="{color}" rx="2"/>')
            offset += w

    svg_bar = f"""<svg width="{bar_width}" height="20" class="chart-container">
{''.join(segments)}
</svg>"""

    return f"""<div class="card">
<h2>Executive Summary</h2>
<div class="summary-bar">
    <div class="summary-stat">
        <span class="value" style="color: {verdict_color}">{run.overall_verdict.value.upper()}</span>
        <span class="label">Overall</span>
    </div>
    <div class="summary-stat">
        <span class="value" style="color: {_GREEN}">{run.total_pass}</span>
        <span class="label">Pass</span>
    </div>
    <div class="summary-stat">
        <span class="value" style="color: {_RED}">{run.total_fail}</span>
        <span class="label">Fail</span>
    </div>
    <div class="summary-stat">
        <span class="value" style="color: {_YELLOW}">{run.total_warn}</span>
        <span class="label">Warn</span>
    </div>
    <div class="summary-stat">
        <span class="value" style="color: {_GRAY}">{run.total_skip}</span>
        <span class="label">Skip</span>
    </div>
    <div class="summary-stat">
        <span class="value" style="color: {_TEXT2}">{total}</span>
        <span class="label">Total</span>
    </div>
</div>
{svg_bar}
</div>"""


def _suite_section(suite: TestSuiteResult) -> str:
    pass_count = suite.pass_count
    fail_count = suite.fail_count
    total = len(suite.tests)

    badge_color = _GREEN if fail_count == 0 else _RED
    badge_text = f"{pass_count}/{total} pass" if fail_count == 0 else f"{fail_count} fail"

    rows = []
    for t in suite.tests:
        v_color = _VERDICT_COLORS.get(t.verdict.value, _GRAY)
        rows.append(f"""<tr>
<td>{_esc(t.test_id)}</td>
<td>{_esc(t.test_name)}</td>
<td><span class="verdict-badge" style="background: {v_color}20; color: {v_color}">{t.verdict.value.upper()}</span></td>
<td>{_esc(t.message)}</td>
<td style="color: {_TEXT2}">{t.duration_ms:.0f}ms</td>
</tr>""")

    return f"""<div class="card">
<h2>{_esc(suite.suite_name)}
    <span class="verdict-badge" style="background: {badge_color}20; color: {badge_color}; margin-left: 8px; font-size: 12px;">
        {badge_text}
    </span>
</h2>
<table class="results-table">
<thead><tr>
<th>ID</th><th>Test Name</th><th>Verdict</th><th>Message</th><th>Duration</th>
</tr></thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
</div>"""


def _signal_integrity_charts(run: TestRun) -> str:
    """Generate SVG bar charts for per-lane eye measurements."""
    measurements = run.eye_data.get("lane_measurements", [])
    if not measurements:
        return ""

    chart_width = 600
    bar_height = 22
    bar_gap = 4
    label_width = 60
    chart_height = len(measurements) * (bar_height + bar_gap) + 40

    # Find max values for scaling
    max_width_ui = max((float(m.get("eye_width_ui", 0)) for m in measurements), default=1.0) * 1.2
    max_height_mv = max((float(m.get("eye_height_mv", 0)) for m in measurements), default=1.0) * 1.2

    if max_width_ui <= 0:
        max_width_ui = 1.0
    if max_height_mv <= 0:
        max_height_mv = 1.0

    avail_width = chart_width - label_width - 20

    # Width chart
    width_bars = []
    for i, m in enumerate(measurements):
        y = 30 + i * (bar_height + bar_gap)
        w = float(m.get("eye_width_ui", 0))
        bar_w = (w / max_width_ui) * avail_width
        width_bars.append(
            f'<text x="0" y="{y + 15}" fill="{_TEXT2}" font-size="11">L{m.get("lane", i)}</text>'
            f'<rect x="{label_width}" y="{y}" width="{bar_w}" height="{bar_height}" fill="{_CYAN}" rx="3"/>'
            f'<text x="{label_width + bar_w + 6}" y="{y + 15}" fill="{_TEXT}" font-size="11">{w:.4f} UI</text>'
        )

    # Height chart
    height_bars = []
    for i, m in enumerate(measurements):
        y = 30 + i * (bar_height + bar_gap)
        h = float(m.get("eye_height_mv", 0))
        bar_w = (h / max_height_mv) * avail_width
        height_bars.append(
            f'<text x="0" y="{y + 15}" fill="{_TEXT2}" font-size="11">L{m.get("lane", i)}</text>'
            f'<rect x="{label_width}" y="{y}" width="{bar_w}" height="{bar_height}" fill="{_GREEN}" rx="3"/>'
            f'<text x="{label_width + bar_w + 6}" y="{y + 15}" fill="{_TEXT}" font-size="11">{h:.1f} mV</text>'
        )

    return f"""<div class="card">
<h2>Signal Integrity - Eye Measurements</h2>
<h3>Eye Width (UI)</h3>
<svg width="{chart_width}" height="{chart_height}" class="chart-container">
<text x="{label_width}" y="18" fill="{_TEXT2}" font-size="12">Eye Width per Lane</text>
{''.join(width_bars)}
</svg>
<h3>Eye Height (mV)</h3>
<svg width="{chart_width}" height="{chart_height}" class="chart-container">
<text x="{label_width}" y="18" fill="{_TEXT2}" font-size="12">Eye Height per Lane</text>
{''.join(height_bars)}
</svg>
</div>"""


def _ber_results_table(run: TestRun) -> str:
    """Generate BER results table."""
    rows = []

    # Current speed BER
    current = run.ber_data.get("current_speed", {})
    lane_bers = current.get("lane_bers", [])
    gen = current.get("gen", 0)

    for entry in lane_bers:
        ber_val = entry.get("ber", 0)
        color = _GREEN if ber_val == 0 else (_YELLOW if ber_val < 1e-12 else _RED)
        rows.append(f"""<tr>
<td>Gen{gen}</td>
<td>Lane {entry.get('lane', '?')}</td>
<td style="color: {color}">{ber_val:.2e}</td>
<td>{entry.get('error_count', 0)}</td>
<td>{'Yes' if entry.get('synced') else 'No'}</td>
</tr>""")

    # Multi-speed BER
    multi = run.ber_data.get("multi_speed", [])
    for speed_entry in multi:
        gen_name = speed_entry.get("gen_name", "")
        for entry in speed_entry.get("lane_bers", []):
            ber_val = entry.get("ber", 0)
            color = _GREEN if ber_val == 0 else (_YELLOW if ber_val < 1e-12 else _RED)
            rows.append(f"""<tr>
<td>{_esc(gen_name)}</td>
<td>Lane {entry.get('lane', '?')}</td>
<td style="color: {color}">{ber_val:.2e}</td>
<td>{entry.get('error_count', 0)}</td>
<td>{'Yes' if entry.get('synced') else 'No'}</td>
</tr>""")

    if not rows:
        return ""

    return f"""<div class="card">
<h2>BER Test Results</h2>
<table class="results-table">
<thead><tr>
<th>Speed</th><th>Lane</th><th>BER</th><th>Errors</th><th>Synced</th>
</tr></thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
</div>"""


def _footer(run: TestRun) -> str:
    return f"""<div class="footer">
Generated by Calypso - Serial Cables Atlas3 PCIe Switch Manager | Run {_esc(run.run_id)} | {_esc(run.device.timestamp)}
</div>"""


def _esc(text: str) -> str:
    """HTML-escape a string."""
    return html.escape(str(text))
