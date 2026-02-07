"""
Dark theme configuration for the Calypso dashboard.

Hardware-engineer aesthetic matching the Serial Cables Phoenix design system.
Cyan accent, green/yellow/red status indicators, JetBrains Mono for hex values.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Colors:
    """Dashboard color palette."""

    # Background layers
    bg_primary: str = "#0d1117"
    bg_secondary: str = "#161b22"
    bg_card: str = "#1c2128"
    bg_elevated: str = "#21262d"

    # Text
    text_primary: str = "#e6edf3"
    text_secondary: str = "#8b949e"
    text_muted: str = "#484f58"

    # Accent colors
    cyan: str = "#00d4ff"
    cyan_dim: str = "#0a6e82"
    blue: str = "#58a6ff"
    purple: str = "#bc8cff"

    # Status colors
    green: str = "#3fb950"
    green_dim: str = "#1a4731"
    yellow: str = "#d29922"
    yellow_dim: str = "#4d3800"
    red: str = "#f85149"
    red_dim: str = "#5c1a1a"
    orange: str = "#db6d28"

    # Border
    border: str = "#30363d"
    border_active: str = "#58a6ff"


COLORS = Colors()

# Global CSS injected into every page
GLOBAL_CSS = f"""
:root {{
    --bg-primary: {COLORS.bg_primary};
    --bg-secondary: {COLORS.bg_secondary};
    --bg-card: {COLORS.bg_card};
    --bg-elevated: {COLORS.bg_elevated};
    --text-primary: {COLORS.text_primary};
    --text-secondary: {COLORS.text_secondary};
    --text-muted: {COLORS.text_muted};
    --cyan: {COLORS.cyan};
    --blue: {COLORS.blue};
    --green: {COLORS.green};
    --yellow: {COLORS.yellow};
    --red: {COLORS.red};
    --border: {COLORS.border};
}}

body {{
    background-color: {COLORS.bg_primary} !important;
    color: {COLORS.text_primary} !important;
}}

.q-page {{
    background-color: {COLORS.bg_primary} !important;
}}

.q-drawer {{
    background-color: {COLORS.bg_secondary} !important;
}}

.q-header {{
    background-color: {COLORS.bg_secondary} !important;
    border-bottom: 1px solid {COLORS.border} !important;
}}

.q-card {{
    background-color: {COLORS.bg_card} !important;
    border: 1px solid {COLORS.border} !important;
}}

.q-table {{
    background-color: {COLORS.bg_card} !important;
    color: {COLORS.text_primary} !important;
}}

.q-table th {{
    color: {COLORS.text_secondary} !important;
    border-bottom-color: {COLORS.border} !important;
}}

.q-table td {{
    border-bottom-color: {COLORS.border} !important;
}}

.q-item {{
    color: {COLORS.text_primary} !important;
}}

.q-tab {{
    color: {COLORS.text_secondary} !important;
}}

.q-tab--active {{
    color: {COLORS.cyan} !important;
}}

.q-field__control {{
    background-color: {COLORS.bg_elevated} !important;
    color: {COLORS.text_primary} !important;
}}

.q-field__label {{
    color: {COLORS.text_secondary} !important;
}}

.q-btn {{
    text-transform: none !important;
}}

.hex-value {{
    font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
    color: {COLORS.cyan};
    font-weight: 500;
}}

.status-green {{ color: {COLORS.green}; }}
.status-yellow {{ color: {COLORS.yellow}; }}
.status-red {{ color: {COLORS.red}; }}
.status-muted {{ color: {COLORS.text_muted}; }}

.calypso-card {{
    background-color: {COLORS.bg_card};
    border: 1px solid {COLORS.border};
    border-radius: 8px;
    padding: 16px;
}}

.section-title {{
    color: {COLORS.text_secondary};
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 8px;
}}

.mono {{
    font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
}}
"""


def link_color(is_up: bool) -> str:
    """Return color based on link state."""
    return COLORS.green if is_up else COLORS.text_muted
