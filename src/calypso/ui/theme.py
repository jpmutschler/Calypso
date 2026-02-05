"""Dark theme configuration for the web dashboard."""

from __future__ import annotations

COLORS = {
    "bg_primary": "#0d1117",
    "bg_secondary": "#161b22",
    "bg_tertiary": "#21262d",
    "border": "#30363d",
    "text_primary": "#e6edf3",
    "text_secondary": "#8b949e",
    "text_muted": "#484f58",
    "accent_blue": "#58a6ff",
    "accent_green": "#3fb950",
    "accent_red": "#f85149",
    "accent_yellow": "#d29922",
    "accent_purple": "#bc8cff",
    "accent_orange": "#d18616",
    "link_up": "#3fb950",
    "link_down": "#f85149",
    "port_active": "#58a6ff",
    "port_inactive": "#484f58",
}

CSS = """
body {
    background-color: #0d1117 !important;
    color: #e6edf3 !important;
    font-family: 'JetBrains Mono', 'Fira Code', monospace !important;
}
.q-card {
    background-color: #161b22 !important;
    border: 1px solid #30363d !important;
}
.q-table {
    background-color: #161b22 !important;
}
.q-table th {
    color: #8b949e !important;
}
.q-drawer {
    background-color: #161b22 !important;
    border-right: 1px solid #30363d !important;
}
.q-header {
    background-color: #161b22 !important;
    border-bottom: 1px solid #30363d !important;
}
.q-btn {
    text-transform: none !important;
}
"""
