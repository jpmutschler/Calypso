"""CSS/SVG chart primitives for self-contained HTML reports.

All rendering is pure HTML/CSS — no JavaScript dependencies.
Uses Calypso dark theme colors inline.
"""

from __future__ import annotations

import html

# Theme colors (matching calypso.ui.theme)
# Public constants — canonical source of truth for all report modules.
BG_PRIMARY = "#0d1117"
BG_CARD = "#1c2128"
BG_ELEVATED = "#21262d"
TEXT_PRIMARY = "#e6edf3"
TEXT_SECONDARY = "#8b949e"
TEXT_MUTED = "#484f58"
CYAN = "#00d4ff"
GREEN = "#3fb950"
YELLOW = "#d29922"
RED = "#f85149"
BORDER = "#30363d"

_STATUS_COLORS = {
    "pass": GREEN,
    "fail": RED,
    "warn": YELLOW,
    "skip": TEXT_MUTED,
    "error": RED,
    "running": CYAN,
    "pending": TEXT_MUTED,
}


def status_color(status_value: str) -> str:
    """Get the color for a status value string."""
    return _STATUS_COLORS.get(status_value, TEXT_MUTED)


def status_badge(status: str, text: str = "") -> str:
    """Render an inline status badge."""
    color = _STATUS_COLORS.get(status, TEXT_MUTED)
    label = html.escape(text or status.upper())
    return (
        f'<span style="display:inline-block; padding:2px 10px; border-radius:4px; '
        f"font-size:12px; font-weight:600; "
        f"background:{color}20; color:{color}; "
        f'border:1px solid {color}40;">{label}</span>'
    )


def metric_card(label: str, value: str, color: str = TEXT_PRIMARY) -> str:
    """Render a metric card with label and large value."""
    return (
        f'<div style="display:inline-block; text-align:center; padding:12px 20px; '
        f"background:{BG_CARD}; border:1px solid {BORDER}; border-radius:8px; "
        f'margin:4px;">'
        f'<div style="font-size:24px; font-weight:700; color:{color};">{html.escape(value)}</div>'
        f'<div style="font-size:11px; color:{TEXT_MUTED}; margin-top:4px;">{html.escape(label)}</div>'
        f"</div>"
    )


def bar_chart(
    data: list[tuple[str, float]],
    max_value: float | None = None,
    bar_color: str = CYAN,
    height_px: int = 20,
) -> str:
    """Render a horizontal bar chart.

    Args:
        data: List of (label, value) tuples.
        max_value: Maximum value for scaling. Auto-detected if None.
        bar_color: Bar fill color.
        height_px: Height of each bar.
    """
    if not data:
        return ""

    max_val = max_value or max(v for _, v in data) or 1
    rows: list[str] = []

    for label, value in data:
        pct = min(value / max_val * 100, 100) if max_val > 0 else 0
        rows.append(
            f'<div style="display:flex; align-items:center; margin:4px 0;">'
            f'<div style="width:120px; font-size:12px; color:{TEXT_SECONDARY}; '
            f'text-align:right; padding-right:8px; white-space:nowrap;">{html.escape(str(label))}</div>'
            f'<div style="flex:1; background:{BG_ELEVATED}; border-radius:4px; '
            f'height:{height_px}px; overflow:hidden;">'
            f'<div style="width:{pct:.1f}%; height:100%; background:{bar_color}; '
            f'border-radius:4px; transition:width 0.3s;"></div>'
            f"</div>"
            f'<div style="width:80px; font-size:12px; color:{TEXT_PRIMARY}; '
            f'padding-left:8px; text-align:right;">{value:.2f}</div>'
            f"</div>"
        )

    return f'<div style="padding:8px 0;">{"".join(rows)}</div>'


def results_table(
    columns: list[str],
    rows: list[list[str]],
    status_column: int | None = None,
) -> str:
    """Render an HTML results table.

    Args:
        columns: Column headers.
        rows: Row data (list of lists of strings).
        status_column: Column index that contains status values (for coloring).
    """
    header_cells = "".join(
        f'<th style="text-align:left; padding:8px 12px; color:{TEXT_SECONDARY}; '
        f'font-size:12px; font-weight:600; border-bottom:1px solid {BORDER};">'
        f"{html.escape(col)}</th>"
        for col in columns
    )

    body_rows: list[str] = []
    for row in rows:
        cells: list[str] = []
        for i, cell in enumerate(row):
            if status_column is not None and i == status_column:
                cell_html = status_badge(cell.lower(), cell)
            else:
                cell_html = html.escape(str(cell))
            cells.append(
                f'<td style="padding:6px 12px; border-bottom:1px solid {BORDER}; '
                f'font-size:13px; color:{TEXT_PRIMARY};">{cell_html}</td>'
            )
        body_rows.append(f"<tr>{''.join(cells)}</tr>")

    return (
        f'<table style="width:100%; border-collapse:collapse; '
        f'background:{BG_CARD}; border-radius:8px; overflow:hidden;">'
        f"<thead><tr>{header_cells}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        f"</table>"
    )


def section_header(title: str, subtitle: str = "") -> str:
    """Render a section header."""
    sub = (
        f'<div style="font-size:13px; color:{TEXT_MUTED}; margin-top:4px;">'
        f"{html.escape(subtitle)}</div>"
        if subtitle
        else ""
    )
    return (
        f'<div style="margin:24px 0 12px 0;">'
        f'<div style="font-size:18px; font-weight:600; color:{TEXT_PRIMARY};">'
        f"{html.escape(title)}</div>"
        f"{sub}"
        f"</div>"
    )


def key_value_table(data: dict[str, str], title: str = "") -> str:
    """Render a 2-column key-value table with dark theme styling.

    Args:
        data: Key-value pairs to display.
        title: Optional title shown above the table.

    Returns:
        Self-contained HTML fragment.
    """
    if not data:
        return ""

    title_html = (
        f'<div style="font-size:14px; font-weight:600; color:{TEXT_PRIMARY}; '
        f'margin-bottom:8px;">{html.escape(title)}</div>'
        if title
        else ""
    )

    rows: list[str] = []
    for key, value in data.items():
        rows.append(
            f"<tr>"
            f'<td style="padding:6px 12px; border-bottom:1px solid {BORDER}; '
            f"color:{TEXT_SECONDARY}; font-size:13px; white-space:nowrap; "
            f'width:1%; font-weight:500;">{html.escape(key)}</td>'
            f'<td style="padding:6px 12px; border-bottom:1px solid {BORDER}; '
            f'color:{TEXT_PRIMARY}; font-size:13px;">{html.escape(value)}</td>'
            f"</tr>"
        )

    table = (
        f'<table style="width:100%; border-collapse:collapse; '
        f"background:{BG_CARD}; border:1px solid {BORDER}; "
        f'border-radius:8px; overflow:hidden;">'
        f"<tbody>{''.join(rows)}</tbody>"
        f"</table>"
    )

    return f'<div style="margin:12px 0;">{title_html}{table}</div>'


def divider() -> str:
    """Render a horizontal divider."""
    return f'<hr style="border:none; border-top:1px solid {BORDER}; margin:16px 0;">'
