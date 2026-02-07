"""NiceGUI web dashboard setup and page registration."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import FastAPI
from nicegui import app, ui

_STATIC_DIR = Path(__file__).parent / "static"


def setup_ui(fastapi_app: FastAPI) -> None:
    """Register NiceGUI pages with the FastAPI application."""

    app.add_static_files("/static", str(_STATIC_DIR))

    @ui.page("/")
    def index():
        from calypso.ui.pages.discovery import discovery_page
        discovery_page()

    @ui.page("/switch/{device_id}")
    def dashboard(device_id: str):
        from calypso.ui.pages.dashboard import dashboard_page
        dashboard_page(device_id)

    @ui.page("/switch/{device_id}/ports")
    def ports(device_id: str):
        from calypso.ui.pages.ports import ports_page
        ports_page(device_id)

    @ui.page("/switch/{device_id}/perf")
    def performance(device_id: str):
        from calypso.ui.pages.performance import performance_page
        performance_page(device_id)

    @ui.page("/switch/{device_id}/config")
    def configuration(device_id: str):
        from calypso.ui.pages.configuration import configuration_page
        configuration_page(device_id)

    @ui.page("/switch/{device_id}/topology")
    def topology(device_id: str):
        from calypso.ui.pages.topology import topology_page
        topology_page(device_id)

    @ui.page("/switch/{device_id}/registers")
    def registers(device_id: str):
        from calypso.ui.pages.pcie_registers import pcie_registers_page
        pcie_registers_page(device_id)

    @ui.page("/switch/{device_id}/eeprom")
    def eeprom_page(device_id: str):
        from calypso.ui.pages.eeprom_viewer import eeprom_viewer_page
        eeprom_viewer_page(device_id)

    @ui.page("/switch/{device_id}/phy")
    def phy(device_id: str):
        from calypso.ui.pages.phy_monitor import phy_monitor_page
        phy_monitor_page(device_id)

    @ui.page("/switch/{device_id}/eye")
    def eye_diagram(device_id: str):
        from calypso.ui.pages.eye_diagram import eye_diagram_page
        eye_diagram_page(device_id)

    @ui.page("/switch/{device_id}/workloads")
    def workloads_ui(device_id: str):
        from calypso.ui.pages.workloads import workloads_page
        workloads_page(device_id)

    # MCU pages
    @ui.page("/mcu/health")
    def mcu_health():
        from calypso.ui.pages.mcu_health import mcu_health_page
        mcu_health_page()

    @ui.page("/mcu/ports")
    def mcu_ports():
        from calypso.ui.pages.mcu_ports import mcu_ports_page
        mcu_ports_page()

    @ui.page("/mcu/errors")
    def mcu_errors():
        from calypso.ui.pages.mcu_errors import mcu_errors_page
        mcu_errors_page()

    @ui.page("/mcu/config")
    def mcu_config():
        from calypso.ui.pages.mcu_config import mcu_config_page
        mcu_config_page()

    @ui.page("/mcu/diagnostics")
    def mcu_diagnostics():
        from calypso.ui.pages.mcu_diagnostics import mcu_diagnostics_page
        mcu_diagnostics_page()

    storage_secret = os.environ.get("CALYPSO_STORAGE_SECRET") or secrets.token_hex(32)

    ui.run_with(
        fastapi_app,
        title="Calypso - Atlas3 Switch Manager",
        storage_secret=storage_secret,
    )
