#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "=================================================="
echo " Calypso - Atlas3 PCIe Switch Manager"
echo "=================================================="
echo

# Check Python is available
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] python3 not found. Install Python 3.10+ and try again."
    exit 1
fi

# Create venv if it doesn't exist
if [ ! -f "venv/bin/activate" ]; then
    echo "[1/4] Creating virtual environment..."
    python3 -m venv venv
else
    echo "[1/4] Virtual environment found."
fi

# Activate venv
source venv/bin/activate

# Ask about workloads support
INSTALL_EXTRAS=""
read -r -p "Install with NVMe workload generation (pynvme)? [y/N] " response
if [[ "$response" =~ ^[Yy]$ ]]; then
    INSTALL_EXTRAS=".[workloads]"
else
    INSTALL_EXTRAS="."
fi

# Install/update package
echo "[2/4] Installing Calypso..."
pip install -e "$INSTALL_EXTRAS" --quiet

# Check driver status and install if needed
echo "[3/4] Checking PLX driver..."
if calypso driver status &>/dev/null; then
    echo "      PlxSvc module is loaded."
else
    echo "      PlxSvc module not loaded. Attempting install..."
    if [ "$(id -u)" -eq 0 ]; then
        calypso driver build
        calypso driver install
        echo "      PlxSvc module built and loaded."
    else
        echo
        echo "[WARNING] Not running as root."
        echo "          To install the PLX driver, run:"
        echo "            sudo calypso driver build && sudo calypso driver install"
        echo "          Or re-run this script with sudo."
        echo "          Continuing without driver -- device connection will fail."
        echo
    fi
fi

# Launch server
echo "[4/4] Starting Calypso server..."
echo
echo " Dashboard: http://localhost:8000"
echo " API docs:  http://localhost:8000/docs"
echo " Press Ctrl+C to stop."
echo
calypso serve --host 0.0.0.0 --port 8000
