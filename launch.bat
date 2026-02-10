@echo off
setlocal

title Calypso - Atlas3 PCIe Switch Manager
cd /d "%~dp0"

echo ==================================================
echo  Calypso - Atlas3 PCIe Switch Manager
echo ==================================================
echo.

:: Check Python is available
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found on PATH. Install Python 3.10+ and try again.
    pause
    exit /b 1
)

:: Create venv if it doesn't exist
if not exist "venv\Scripts\activate.bat" (
    echo [1/4] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
) else (
    echo [1/4] Virtual environment found.
)

:: Activate venv
call venv\Scripts\activate.bat

:: Ask about workloads support (pynvme is Linux-only, but SPDK works if on PATH)
set INSTALL_TARGET=.
set /p WORKLOADS="Install with NVMe workload generation (pynvme, Linux only)? [y/N] "
if /i "%WORKLOADS%"=="y" (
    echo      Note: pynvme is Linux-only. On Windows, use the SPDK backend instead.
    echo      Installing base package...
) else (
    echo.
)

:: Install/update package
echo [2/4] Installing Calypso...
pip install -e %INSTALL_TARGET% --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install Calypso.
    pause
    exit /b 1
)

:: Check driver status and install if needed
echo [3/4] Checking PLX driver...
calypso driver status >nul 2>&1
if errorlevel 1 (
    echo      PlxSvc service not running. Attempting install...
    :: Check admin privileges
    net session >nul 2>&1
    if errorlevel 1 (
        echo.
        echo [WARNING] Not running as administrator.
        echo          To install the PlxSvc driver, right-click this script
        echo          and select "Run as administrator".
        echo          Continuing without driver -- device connection will fail.
        echo.
    ) else (
        calypso driver install
        if errorlevel 1 (
            echo [WARNING] Driver install failed. Device connection may fail.
        ) else (
            echo      PlxSvc service installed and started.
        )
    )
) else (
    echo      PlxSvc service is running.
)

:: Launch server
echo [4/4] Starting Calypso server...
echo.
echo  Dashboard: http://localhost:8000
echo  API docs:  http://localhost:8000/docs
echo  Press Ctrl+C to stop.
echo.
calypso serve --host 0.0.0.0 --port 8000

endlocal
