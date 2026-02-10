# Calypso

PCIe Gen6 Atlas3 Host Card (PEX90144/PEX90080) configuration and monitoring tool. Provides CLI, REST API, and web dashboard interfaces for switch management, PCIe link diagnostics, performance monitoring, compliance testing, and MCU communication.

## Hardware

Targets the **Broadcom PEX90144/PEX90080** PCIe Gen6 switch on the Serial Cables Atlas3 Host Card (Rev 1.1). Both variants share 5 physical connectors (CN0-CN4) but map them to different stations.

### PCI6-AD-X16HI-BG6-144 (PEX90144) -- 144 lanes, 6 stations

| Station | Port Range | Connector | Purpose |
|---------|-----------|-----------|---------|
| STN0 | 0-15 | -- | Root Complex |
| STN1 | 16-31 | -- | Reserved |
| STN2 | 32-47 | Golden Finger | Host PCIe x16 upstream |
| STN5 | 80-95 | CN4 (Straddle) | PCIe straddle connector |
| STN7 | 112-127 | CN0/CN1 (Ext MCIO) | External MCIO |
| STN8 | 128-143 | CN2/CN3 (Int MCIO) | Internal MCIO |

### PCI6-AD-X16HI-BG6-80 (PEX90080) -- 80 lanes, 4 stations

| Station | Port Range | Connector | Purpose |
|---------|-----------|-----------|---------|
| STN0 | 0-15 | CN2/CN3 (Int MCIO) | Internal MCIO |
| STN1 | 16-31 | Golden Finger | Host PCIe x16 upstream |
| STN2 | 32-47 | CN0/CN1 (Ext MCIO) | External MCIO |
| STN6 | 96-111 | CN4 (Straddle) | PCIe straddle connector |

### Connector Pinout (CN0-CN4)

| Connector | PEX90144 Lanes (Station) | PEX90080 Lanes (Station) | Type |
|-----------|-------------------------|-------------------------|------|
| CN0 | 120-127 (STN7) | 40-47 (STN2) | Ext MCIO |
| CN1 | 112-119 (STN7) | 32-39 (STN2) | Ext MCIO |
| CN2 | 136-143 (STN8) | 8-15 (STN0) | Int MCIO |
| CN3 | 128-135 (STN8) | 0-7 (STN0) | Int MCIO |
| CN4 | 80-95 (STN5) | 96-111 (STN6) | Straddle |

## Requirements

- Python 3.10+
- Broadcom PLX SDK (PlxApi shared library)
- **Linux**: PLX kernel driver (`PlxSvc` module) loaded -- use `calypso driver build && calypso driver install`
- **Windows**: PlxSvc kernel service running -- use `calypso driver install` (requires administrator). `PlxApi.dll` loaded via `ctypes.WinDLL` (`__stdcall`). Both `PlxSvc.sys` and `PlxApi.dll` are vendored in `vendor/plxsdk/`.
- Serial connection to MCU (optional, for MCU features -- requires `serialcables-atlas3` package)
- SPDK `spdk_nvme_perf` on PATH (optional, for SPDK workload generation)
- pynvme (optional, Linux only, for pynvme workload generation)

## Installation

```bash
pip install -e .
```

Or with dev dependencies:

```bash
pip install -e ".[dev]"
```

With NVMe workload generation (pynvme backend, Linux only):

```bash
pip install -e ".[workloads]"
```

For the SPDK backend, install `spdk_nvme_perf` as a system package and ensure it is on your PATH. See the [SPDK documentation](https://spdk.io/doc/getting_started.html) for build instructions.

## PLX SDK Setup

Calypso searches for the PLX SDK shared library in the following order:

1. **Vendored SDK** -- `vendor/plxsdk/` in the project root (recommended for distribution)
2. **`PLX_SDK_DIR` environment variable** -- explicit path to the SDK root
3. **Legacy SDK directory** -- `Broadcom_PCIe_SDK_Linux_v23_2_44_0_Alpha_*/PlxSdk` in the project root
4. **System paths** (Linux only) -- `/usr/local/lib`, `/usr/lib`, `/opt/plx/lib`
5. **System PATH / LD_LIBRARY_PATH** -- fallback name-based load (`PlxApi.dll` or `libPlxApi.so`)

On **Windows**, the library is loaded with `ctypes.WinDLL` (`__stdcall` calling convention). On **Linux**, `ctypes.CDLL` (`__cdecl`) is used.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PLX_SDK_DIR` | Path to Broadcom PLX SDK root directory | Auto-detected (vendor/plxsdk) |
| `CALYPSO_STORAGE_SECRET` | Secret key for NiceGUI browser session storage | Random 32-byte hex per launch |

## Quick Start

The fastest way to get running is the one-click launcher script, which handles venv creation, package installation, driver setup, and server launch:

- **Windows**: Double-click `launch.bat` (right-click "Run as administrator" for driver install)
- **Linux**: `chmod +x launch.sh && ./launch.sh` (run with `sudo` for driver install)

On Linux, the launcher will prompt to install with NVMe workload generation support (pynvme).

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

## Architecture

```
src/calypso/
├── bindings/       # ctypes bindings to Broadcom PLX SDK (PlxApi)
├── transport/      # Transport abstraction (PCIe, UART, SDB/USB)
├── sdk/            # Low-level SDK wrappers (device, registers, EEPROM, DMA, etc.)
├── hardware/       # Atlas3 board definitions (station/connector/lane mapping, PHY)
├── models/         # Pydantic data models
├── core/           # Domain logic (switch, ports, topology, perf, PCIe config, PHY, EEPROM)
├── compliance/     # PCIe compliance testing (6 suites, HTML reports)
├── workloads/      # Optional NVMe workload generation (SPDK perf, pynvme)
├── mcu/            # MCU serial client (health, ports, errors, BIST, config)
├── api/            # FastAPI REST + WebSocket API
├── cli/            # Click CLI commands
├── ui/             # NiceGUI web dashboard
├── driver/         # PLX kernel driver build/install manager
└── utils/          # Logging utilities
```

## CLI

### Device Operations

```bash
calypso scan                          # Discover devices
calypso scan --transport uart --port COM3  # Discover via UART
calypso info 0                        # Device details
calypso ports 0                       # All port statuses
calypso perf 0 --interval 1 --count 10    # Performance counters
```

### PCIe Config Space

```bash
calypso pcie config-space 0                  # Dump config registers
calypso pcie config-space 0 --offset 0x100 --count 16
calypso pcie caps 0                          # List capabilities
calypso pcie link 0                          # Link speed/width
calypso pcie retrain 0                       # Retrain link
calypso pcie set-speed 0 --speed 4           # Target Gen4
calypso pcie device-control 0                # Show MPS/MRRS
calypso pcie device-control 0 --mps 256 --mrrs 512
calypso pcie aer 0                           # AER error status
calypso pcie aer 0 --clear                   # Clear AER errors
```

### EEPROM

```bash
calypso eeprom info 0                        # EEPROM presence/status
calypso eeprom read 0 --offset 0 --count 16  # Read DWORDs
calypso eeprom write 0 --offset 0 --value 0xDEADBEEF
calypso eeprom crc 0                         # Verify CRC
calypso eeprom crc 0 --update                # Recalculate + write CRC
```

### PHY Diagnostics

```bash
calypso phy speeds 0                         # Supported link speeds
calypso phy eq-status 0                      # Equalization status
calypso phy lane-eq 0 --port-number 112 --num-lanes 4
calypso phy serdes-diag 0 --port-number 112
calypso phy port-control 0 --port-number 112
calypso phy cmd-status 0 --port-number 112
calypso phy utp-test 0 --port-number 112 --pattern LFSR31 --rate 32GT
calypso phy margining 0
```

### MCU (Serial)

```bash
calypso mcu --port COM3 discover             # Discover on serial
calypso mcu --port COM3 health               # Thermal/power/fan
calypso mcu --port COM3 ports                # Port status
calypso mcu --port COM3 errors               # Error counters
calypso mcu --port COM3 errors --clear       # Clear counters
calypso mcu --port COM3 config               # Mode/clock/spread/FLIT
calypso mcu --port COM3 bist                 # Built-In Self Test
```

### NVMe Workloads (Linux only)

```bash
calypso workloads backends                   # Show available backends
calypso workloads validate --bdf 0000:01:00.0  # Validate target device

# Run SPDK workload
calypso workloads run --backend spdk --bdf 0000:01:00.0 \
    --workload randread --io-size 4096 --queue-depth 128 \
    --duration 30 --workers 4 --core-mask 0xFF

# Run pynvme workload
calypso workloads run --backend pynvme --bdf 0000:01:00.0 \
    --workload randread --duration 10

# Combined host + switch metrics
calypso workloads run --backend spdk --bdf 0000:01:00.0 \
    --duration 30 --with-switch-perf --device-index 0
```

Neither backend is required. The module probes for SPDK and pynvme at runtime and degrades gracefully. When no backend is available, `calypso workloads backends` reports an empty list and all other commands return helpful errors.

### Driver Management

```bash
calypso driver status                        # Check driver/service status
calypso driver check                         # Check prerequisites
calypso driver build                         # Build PlxSvc + PlxApi (Linux only)
calypso driver install                       # Install and start driver/service
calypso driver uninstall                     # Stop and remove driver/service
```

On **Linux**, `install` loads the PlxSvc kernel module (requires sudo). On **Windows**, `install` registers and starts the PlxSvc kernel service (requires administrator). The Windows driver (`PlxSvc.sys`) is vendored in `vendor/plxsdk/Driver/`.

## REST API

Start the server:

```bash
calypso serve --host 0.0.0.0 --port 8000
```

API docs available at `http://localhost:8000/docs` (Swagger UI).

### Endpoints

| Group | Endpoints | Description |
|-------|----------|-------------|
| Devices | `POST /scan`, `GET /`, `POST /connect`, `POST /{id}/disconnect`, `GET /{id}`, `POST /{id}/reset` | Device lifecycle |
| Ports | `GET /{id}/ports`, `GET /{id}/ports/{n}` | Port status |
| Performance | `POST /{id}/perf/start`, `POST /{id}/perf/stop`, `GET /{id}/perf/snapshot`, `WS /{id}/perf/stream` | Perf monitoring + live WebSocket |
| Config | `GET /{id}/config` | Switch configuration |
| Topology | `GET /{id}/topology` | Fabric topology with connector mapping, downstream device enumeration |
| Errors | `GET /{id}/errors/overview`, `POST /{id}/errors/clear-aer`, `POST /{id}/errors/clear-mcu` | Combined AER + MCU + LTSSM error view |
| Compliance | `POST /{id}/compliance/start`, `GET /{id}/compliance/progress`, `GET /{id}/compliance/result`, `POST /{id}/compliance/cancel`, `GET /{id}/compliance/report` | PCIe compliance testing + HTML reports |
| Registers | `GET /{id}/config-space`, `GET /{id}/capabilities`, `GET /{id}/device-control`, `POST /{id}/device-control`, `GET /{id}/link`, `POST /{id}/link/retrain`, `POST /{id}/link/target-speed`, `GET /{id}/aer`, `POST /{id}/aer/clear` | PCIe config space |
| EEPROM | `GET /{id}/eeprom/info`, `GET /{id}/eeprom/read`, `POST /{id}/eeprom/write`, `GET /{id}/eeprom/crc`, `POST /{id}/eeprom/crc/update` | EEPROM access |
| PHY | `GET /{id}/phy/speeds`, `GET /{id}/phy/eq-status`, `GET /{id}/phy/lane-eq`, `GET /{id}/phy/serdes-diag`, `POST /{id}/phy/serdes-diag/clear`, `GET /{id}/phy/port-control`, `GET /{id}/phy/cmd-status`, `GET /{id}/phy/lane-margining`, `POST /{id}/phy/utp/load`, `GET /{id}/phy/utp/results`, `POST /{id}/phy/utp/prepare` | PHY layer |
| LTSSM | `GET /{id}/ltssm/snapshot`, `POST /{id}/ltssm/retrain`, `GET /{id}/ltssm/retrain/progress`, `GET /{id}/ltssm/retrain/result`, `POST /{id}/ltssm/clear-counters`, `POST /{id}/ltssm/ptrace/configure`, `POST /{id}/ltssm/ptrace/start`, `POST /{id}/ltssm/ptrace/stop`, `GET /{id}/ltssm/ptrace/status`, `GET /{id}/ltssm/ptrace/buffer` | LTSSM state trace + Ptrace capture |
| MCU | `GET /mcu/discover`, `POST /mcu/connect`, `GET /mcu/health`, `GET /mcu/ports`, `GET /mcu/errors`, `GET /mcu/config/*`, `POST /mcu/bist` | MCU serial |
| Workloads | `GET /workloads/backends`, `POST /workloads/start`, `POST /workloads/{id}/stop`, `GET /workloads/{id}`, `GET /workloads`, `GET /workloads/{id}/combined/{device_id}`, `WS /workloads/{id}/stream` | NVMe workload generation + live progress |

All device endpoints prefixed with `/api/devices`. Workloads endpoints prefixed with `/api`. MCU endpoints prefixed with `/api/mcu`.

## Web Dashboard

The NiceGUI dashboard runs alongside the API server on the same port. Navigate to `http://localhost:8000/` in a browser.

The dashboard uses a dark theme with consistent header, sidebar navigation, and Serial Cables branding across all pages. The discovery page auto-scans the PCIe bus on load (Windows and Linux) and displays any detected PLX devices immediately.

### Switch Pages (SDK)

| Page | Route | Features |
|------|-------|----------|
| Discovery | `/` | Auto-scan PCIe bus, scan for devices via UART/SDB, MCU serial connection |
| Dashboard | `/switch/{id}` | Device overview |
| Ports | `/switch/{id}/ports` | Port grid with link status |
| Performance | `/switch/{id}/perf` | Live WebSocket streaming, bandwidth + utilization charts |
| Configuration | `/switch/{id}/config` | Virtual switch and multi-host config |
| Topology | `/switch/{id}/topology` | Fabric topology with connector health, hardware reference, downstream device identification |
| Error Overview | `/switch/{id}/errors` | Combined AER, MCU, and LTSSM error view with per-port breakdown |
| Registers | `/switch/{id}/registers` | Config space browser, capabilities, AER, link control, device control |
| EEPROM | `/switch/{id}/eeprom` | Hex viewer, write with confirmation, CRC management |
| PHY Monitor | `/switch/{id}/phy` | Equalization, SerDes, UTP testing, lane margining |
| Eye Diagram | `/switch/{id}/eye` | Lane margining sweep visualization, eye width/height measurement |
| LTSSM Trace | `/switch/{id}/ltssm` | LTSSM state polling, retrain-and-watch with state transition chart, Ptrace capture |
| Compliance | `/switch/{id}/compliance` | PCIe compliance test runner with 6 suites, progress tracking, HTML reports |
| Workloads | `/switch/{id}/workloads` | NVMe workload config, live progress, results, combined host+switch view |

### MCU Pages (Serial)

| Page | Route | Features |
|------|-------|----------|
| Health | `/mcu/health` | Thermal, fan, voltage, power |
| Port Status | `/mcu/ports` | Station/port status via MCU |
| Error Counters | `/mcu/errors` | Per-port error counts with clear |
| Configuration | `/mcu/config` | Mode, clock, spread spectrum, FLIT |
| Diagnostics | `/mcu/diagnostics` | BIST and diagnostic tools |

## Transport Layers

Calypso supports three transport modes for communicating with Atlas3 devices:

- **PCIe** -- Direct PCIe bus access via PLX SDK. Primary transport for all switch operations. On Linux, requires the `PlxSvc` kernel module. On Windows, requires the Broadcom PlxSvc Windows service and `PlxApi.dll`.
- **UART** -- Serial port communication via the Atlas3 MCU over USB. Used for health, port status, error counters, configuration, and BIST. Requires the `serialcables-atlas3` Python package.
- **SDB** -- Serial Debug Bus over USB. Alternative debug interface using the PLX SDK's SDB mode.

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

## License

MIT
