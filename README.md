# Calypso

PCIe Gen6 Atlas3 Host Card switch manager built with Python. Manages Broadcom PLX PCIe switches on the Serial Cables Atlas3 Host Card through a web dashboard, REST API, and CLI.

Supports A0 silicon (PEX90144/PEX90080) and B0 silicon (PEX90024 through PEX90096).

**For detailed usage instructions, hardware reference, and complete API/CLI documentation, see the [User Manual](docs/USER_MANUAL.md).**

## Requirements

- Python 3.10+
- Broadcom PLX SDK (PlxApi shared library, vendored in `vendor/plxsdk/`)
- **Linux**: PLX kernel driver (`PlxSvc` module) -- `calypso driver build && calypso driver install`
- **Windows**: PlxSvc kernel service -- `calypso driver install` (requires administrator)
- Serial connection to MCU (optional, for MCU and NVMe-MI features)

## Installation

```bash
pip install -e .
```

With dev dependencies:

```bash
pip install -e ".[dev]"
```

With NVMe workload generation (Linux only):

```bash
pip install -e ".[workloads]"
```

## Quick Start

The fastest way to get running is the one-click launcher:

- **Windows**: Double-click `launch.bat` (right-click "Run as administrator" for driver install)
- **Linux**: `chmod +x launch.sh && ./launch.sh` (run with `sudo` for driver install)

### Manual Setup

```bash
# Scan for devices on PCIe bus
calypso scan

# Show device info
calypso info 0

# List port statuses
calypso ports 0

# Start the web dashboard + API server
calypso serve --host 0.0.0.0 --port 8000
```

The web dashboard is available at `http://localhost:8000/`. Interactive API docs are at `http://localhost:8000/docs`.

## Key Features

- **Device discovery** across PCIe, UART, and SDB transports
- **Link diagnostics** -- port status, LTSSM tracing, equalization monitoring
- **Performance monitoring** -- real-time bandwidth/utilization via WebSocket
- **PHY analysis** -- SerDes diagnostics, User Test Patterns, lane margining
- **Compliance testing** -- 6 automated suites with HTML reports
- **Recipes and Workflows** -- 27 validation recipes across 6 categories, chainable into multi-step workflows
- **Gen6 Flit mode** -- BER measurement, FEC analysis, error injection, PAM4 eye sweep
- **NVMe workloads** -- SPDK and pynvme backends with combined host+switch metrics
- **MCU monitoring** -- thermal, fan, voltage, power, error counters, BIST, I2C/I3C bus, NVMe-MI

## Project Structure

```
src/calypso/
  bindings/       ctypes bindings to Broadcom PLX SDK
  transport/      Transport abstraction (PCIe, UART, SDB)
  sdk/            Pythonic wrappers over PLX SDK C functions
  hardware/       Atlas3 board definitions (station/connector/lane mapping)
  models/         Pydantic v2 data models
  core/           Domain logic (switch, ports, topology, perf, PHY, EEPROM)
  compliance/     PCIe compliance testing engine
  workflows/      Recipes and workflow validation system
  workloads/      NVMe workload generation (SPDK, pynvme)
  mcu/            MCU serial client
  mctp/           MCTP over I2C/I3C transport
  nvme_mi/        NVMe-MI client and drive discovery
  api/            FastAPI REST + WebSocket API
  cli/            Click CLI commands
  ui/             NiceGUI web dashboard
  driver/         PLX kernel driver build/install manager
  utils/          Logging utilities
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check src/

# Format
ruff format src/
```

Tests are organized under `tests/` with `unit/`, `integration/`, and `e2e/` subdirectories.

## Documentation

- **[User Manual](docs/USER_MANUAL.md)** -- Complete guide covering installation, all web dashboard pages, hardware reference, REST API reference, CLI reference, and troubleshooting.

## License

MIT
