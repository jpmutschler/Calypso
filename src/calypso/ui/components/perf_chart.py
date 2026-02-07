"""Performance monitoring chart components using ECharts."""

from __future__ import annotations

from nicegui import ui

from calypso.models.performance import PerfSnapshot
from calypso.ui.theme import COLORS


def bandwidth_chart(snapshots: list[PerfSnapshot], port_number: int | None = None) -> ui.echart:
    """Create a real-time bandwidth chart using ECharts."""
    chart = ui.echart({
        "backgroundColor": "transparent",
        "textStyle": {"color": COLORS.text_secondary},
        "tooltip": {"trigger": "axis"},
        "legend": {
            "data": ["Ingress", "Egress"],
            "textStyle": {"color": COLORS.text_secondary},
        },
        "xAxis": {
            "type": "category",
            "data": [],
            "axisLine": {"lineStyle": {"color": COLORS.border}},
        },
        "yAxis": {
            "type": "value",
            "name": "MB/s",
            "axisLine": {"lineStyle": {"color": COLORS.border}},
            "splitLine": {"lineStyle": {"color": COLORS.border + "40"}},
        },
        "series": [
            {
                "name": "Ingress",
                "type": "line",
                "smooth": True,
                "data": [],
                "lineStyle": {"color": COLORS.green},
                "itemStyle": {"color": COLORS.green},
                "areaStyle": {"color": COLORS.green + "20"},
            },
            {
                "name": "Egress",
                "type": "line",
                "smooth": True,
                "data": [],
                "lineStyle": {"color": COLORS.cyan},
                "itemStyle": {"color": COLORS.cyan},
                "areaStyle": {"color": COLORS.cyan + "20"},
            },
        ],
    }).classes("w-full").style("height: 300px")

    return chart


def utilization_gauge(utilization: float, label: str = "Utilization") -> ui.echart:
    """Create a utilization gauge using ECharts."""
    pct = utilization * 100

    if pct < 50:
        color = COLORS.green
    elif pct < 80:
        color = COLORS.yellow
    else:
        color = COLORS.red

    return ui.echart({
        "backgroundColor": "transparent",
        "series": [{
            "type": "gauge",
            "startAngle": 210,
            "endAngle": -30,
            "min": 0,
            "max": 100,
            "detail": {
                "formatter": f"{pct:.1f}%",
                "fontSize": 16,
                "color": COLORS.text_primary,
            },
            "title": {
                "show": True,
                "offsetCenter": [0, "80%"],
                "fontSize": 12,
                "color": COLORS.text_secondary,
            },
            "data": [{"value": round(pct, 1), "name": label}],
            "axisLine": {
                "lineStyle": {
                    "width": 10,
                    "color": [
                        [0.5, COLORS.green],
                        [0.8, COLORS.yellow],
                        [1, COLORS.red],
                    ],
                },
            },
            "pointer": {"length": "60%", "width": 4},
            "axisTick": {"show": False},
            "splitLine": {"show": False},
            "axisLabel": {"show": False},
        }],
    }).classes("w-full").style("height: 200px")
