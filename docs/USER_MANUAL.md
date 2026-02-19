# Calypso User's Manual

**Serial Cables Atlas3 PCIe Switch Manager**

Version 0.1.0

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [System Requirements](#2-system-requirements)
3. [Installation](#3-installation)
4. [Getting Started](#4-getting-started)
5. [Web Dashboard](#5-web-dashboard)
   - 5.1 [Device Discovery](#51-device-discovery)
   - 5.2 [Dashboard](#52-dashboard)
   - 5.3 [Ports](#53-ports)
   - 5.4 [Performance Monitor](#54-performance-monitor)
   - 5.5 [Configuration](#55-configuration)
   - 5.6 [Topology](#56-topology)
   - 5.7 [PCIe Registers](#57-pcie-registers)
   - 5.8 [EEPROM Viewer](#58-eeprom-viewer)
   - 5.9 [PHY Monitor](#59-phy-monitor)
   - 5.10 [Eye Diagram](#510-eye-diagram)
   - 5.11 [LTSSM Trace](#511-ltssm-trace)
   - 5.12 [Error Overview](#512-error-overview)
   - 5.13 [Compliance](#513-compliance)
   - 5.14 [Workloads](#514-workloads)
   - 5.15 [MCU Pages](#515-mcu-pages)
   - 5.16 [I2C/I3C Bus Explorer](#516-i2ci3c-bus-explorer)
   - 5.17 [NVMe Drives](#517-nvme-drives)
6. [Hardware Reference](#6-hardware-reference)
7. [Appendix A: REST API Reference](#appendix-a-rest-api-reference)
8. [Appendix B: CLI Reference](#appendix-b-cli-reference)
9. [Appendix C: Troubleshooting](#appendix-c-troubleshooting)

---

## 1. Introduction

Calypso is a comprehensive management tool for Broadcom Atlas3 PCIe Gen6 switches on the Serial Cables Atlas3 Host Card. It supports A0 silicon (PEX90144, PEX90080) and B0 silicon (PEX90024 through PEX90096). It provides a web-based dashboard, REST API, and command-line interface for:

- **Device discovery** across PCIe, UART, and SDB transports
- **Link diagnostics** -- port status, LTSSM state tracing, equalization monitoring
- **Performance monitoring** -- real-time bandwidth and utilization via WebSocket streaming
- **PHY-layer analysis** -- SerDes diagnostics, User Test Patterns, lane margining eye diagrams
- **Error management** -- combined AER, MCU, and LTSSM error views with per-port breakdown
- **Compliance testing** -- 6 automated test suites (link training, error audit, config audit, signal integrity, BER, port sweep) with real-time progress and HTML reports
- **Switch configuration** -- EEPROM management, device control (MPS/MRRS), link speed targeting
- **NVMe workload generation** -- SPDK and pynvme backends with combined host+switch metrics
- **MCU monitoring** -- thermal, fan, voltage, power, error counters, BIST via serial

The primary audience for this tool is PCIe validation engineers performing link bring-up, signal integrity testing, error analysis, and system-level validation on Atlas3 host card platforms.

---

## 2. System Requirements

### Hardware

- Serial Cables Atlas3 Host Card (Rev 1.1 or later)
  - **A0 silicon:**
    - **PCI6-AD-X16HI-BG6-144** (PEX90144) -- 144 lanes, 6 stations
    - **PCI6-AD-X16HI-BG6-80** (PEX90080) -- 80 lanes, 4 stations
  - **B0 silicon:**
    - **PEX90024** -- 24 lanes, 2 stations
    - **PEX90032** -- 32 lanes, 2 stations
    - **PEX90048** -- 48 lanes, 3 stations
    - **PEX90064** -- 64 lanes, 4 stations
    - **PEX90080-B0** -- 80 lanes, 5 stations
    - **PEX90096** -- 96 lanes, 6 stations
- Host system with available x16 PCIe slot
- USB connection to Atlas3 MCU (optional, for MCU features)

### Software

| Component | Requirement | Notes |
|-----------|-------------|-------|
| Python | 3.10 or later | |
| Broadcom PLX SDK | PlxApi shared library | See [PLX SDK Setup](#plx-sdk-setup) |
| Linux driver | `PlxSvc` kernel module | Build via `calypso driver build && calypso driver install` |
| Windows driver | PlxSvc kernel service | Install via `calypso driver install` (requires administrator) |
| MCU serial | `serialcables-atlas3` package | Optional, for UART/MCU features |
| SPDK | `spdk_nvme_perf` on PATH | Optional, for SPDK workload generation |
| pynvme | Python package | Optional, Linux only, for pynvme workload generation |

### PLX SDK Setup

Calypso searches for the PLX SDK shared library in the following order:

1. **Vendored SDK** -- `vendor/plxsdk/` in the project root (recommended)
2. **`PLX_SDK_DIR` environment variable** -- explicit path to the SDK root
3. **Legacy SDK directory** -- `Broadcom_PCIe_SDK_Linux_v23_2_44_0_Alpha_*/PlxSdk` in the project root
4. **System paths** (Linux only) -- `/usr/local/lib`, `/usr/lib`, `/opt/plx/lib`
5. **System PATH / LD_LIBRARY_PATH** -- fallback name-based load

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PLX_SDK_DIR` | Path to Broadcom PLX SDK root directory | Auto-detected |
| `CALYPSO_STORAGE_SECRET` | Secret key for browser session storage | Random 32-byte hex per launch |

---

## 3. Installation

### Standard Installation

```bash
pip install -e .
```

### With Development Dependencies

```bash
pip install -e ".[dev]"
```

### With NVMe Workload Generation (Linux only)

```bash
pip install -e ".[workloads]"
```

For the SPDK backend, install `spdk_nvme_perf` as a system package and ensure it is on your PATH.

### Linux Driver Setup

```bash
calypso driver check      # Verify build prerequisites
calypso driver build       # Build PlxSvc kernel module and PlxApi library
calypso driver install     # Load kernel module (requires sudo)
calypso driver status      # Verify driver is loaded
```

### Windows Driver Setup

The Windows driver (`PlxSvc.sys`) is vendored in `vendor/plxsdk/Driver/`. No build step is needed.

```bash
calypso driver check      # Verify prerequisites (admin, driver files, DLL)
calypso driver install     # Install and start PlxSvc service (requires administrator)
calypso driver status      # Verify service is running
```

To remove the driver:

```bash
calypso driver uninstall   # Stop and remove PlxSvc service (requires administrator)
```

---

## 4. Getting Started

### One-Click Launch

The fastest way to get running is the included launcher script, which automates venv creation, package installation, driver setup, and server launch:

**Windows:**
- Double-click `launch.bat`
- To install the PLX driver automatically, right-click the script and select "Run as administrator"

**Linux:**
```bash
chmod +x launch.sh
./launch.sh
```
- Run with `sudo` if the PLX driver needs to be built and loaded
- The script will prompt whether to install NVMe workload generation support (pynvme, Linux only)

### Manual Setup

Launch the web dashboard and API server:

```bash
calypso serve --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` in a browser. The discovery page loads automatically and scans the PCIe bus for Atlas3 devices.

### Quick CLI Verification

```bash
# Scan for devices
calypso scan

# Show device details (device index 0)
calypso info 0

# List port statuses
calypso ports 0

# Check AER error status
calypso pcie aer 0
```

### Connecting via MCU (Serial)

```bash
# Discover MCU devices on serial
calypso mcu --port COM3 discover

# Check health telemetry
calypso mcu --port COM3 health

# View error counters
calypso mcu --port COM3 errors
```

---

## 5. Web Dashboard

The Calypso web dashboard provides a dark-themed interface with a persistent sidebar for navigation. All pages follow a consistent layout with a header bar displaying the page title and connection status.

The sidebar organizes pages into two sections:

- **SWITCH (SDK)** -- Pages that communicate with the switch via the PLX SDK over PCIe. Requires a connected device.
- **MCU** -- Pages that communicate with the Atlas3 MCU over a serial connection. Requires an MCU serial port.

<!-- Screenshot: Full dashboard layout showing sidebar, header, and content area -->

---

### 5.1 Device Discovery

**Route:** `/`

The discovery page is the entry point for connecting to Atlas3 devices. It supports three transport modes.

#### PCIe Bus Scan

On page load, Calypso automatically scans the PCIe bus for Broadcom PLX devices. Detected devices appear in a list showing:

- Chip name (human-readable, e.g., "PEX90144", "PEX90064") and device ID
- BDF (Bus:Device.Function) location
- PLX port number and family
- Revision

Click **Connect** on any device to open it for management. The sidebar populates with switch pages after connection.

#### UART (MCU/USB) Connection

1. Select **UART (MCU/USB)** from the transport dropdown
2. Enter the serial port (e.g., `COM3` on Windows, `/dev/ttyUSB0` on Linux)
3. Select baud rate (19200 or 115200)
4. Click **Scan** to discover devices

#### MCU Serial Connection

The MCU Connection card at the bottom of the discovery page manages the serial link to the Atlas3 MCU:

1. Enter the serial port path
2. Click **Connect**
3. The connection status indicator turns green on success
4. MCU pages become available in the sidebar

The MCU port is persisted in the browser session -- it survives page refreshes.

<!-- Screenshot: Discovery page with PCIe devices listed and MCU connection card -->

---

### 5.2 Dashboard

**Route:** `/switch/{device_id}`

The dashboard provides a high-level overview of the connected switch device. It displays device identification, port summary, and performance overview cards.

<!-- Screenshot: Dashboard overview -->

---

### 5.3 Ports

**Route:** `/switch/{device_id}/ports`

Displays all switch ports in a visual grid layout. Each port tile shows:

- **Port number** (e.g., P0, P32, P112)
- **Link status** -- green dot for UP, red for DOWN
- **Link speed and width** (e.g., `x4 Gen4`) when link is up
- **"No Link"** when link is down

Port tile borders indicate role:
- Blue border = Upstream port
- Green border = Downstream port
- Gray border = Other role

<!-- Screenshot: Port grid showing mix of UP and DOWN ports -->

---

### 5.4 Performance Monitor

**Route:** `/switch/{device_id}/perf`

Real-time bandwidth and utilization monitoring with WebSocket-based live streaming.

#### Controls

| Button | Action |
|--------|--------|
| **Start Monitor** | Begin performance counter collection |
| **Stop Monitor** | Stop collection |
| **Stream** | Open WebSocket for live updates (~1s interval) |
| **Stop Stream** | Close WebSocket connection |
| **Snapshot** | Take a single reading |
| **Clear Chart** | Reset chart data |

#### Displays

1. **Summary Stats** -- Total ingress/egress bandwidth (MB/s), average utilization, active port count, collection interval

2. **Bandwidth Chart** -- Rolling time-series line chart (60-point window) showing ingress (cyan) and egress (green) MB/s per port

3. **Link Utilization Chart** -- Bar chart showing ingress/egress utilization percentage (0-100%) per port

4. **Port Statistics Table** -- Per-port breakdown:

| Column | Description |
|--------|-------------|
| Port | Port number |
| In MB/s | Ingress bandwidth |
| In Util% | Ingress utilization percentage |
| In Total | Total ingress TLP count |
| In Avg/TLP | Average bytes per ingress TLP |
| Out MB/s | Egress bandwidth |
| Out Util% | Egress utilization percentage |
| Out Total | Total egress TLP count |
| Out Avg/TLP | Average bytes per egress TLP |

<!-- Screenshot: Performance page with live bandwidth chart and utilization bars -->

---

### 5.5 Configuration

**Route:** `/switch/{device_id}/config`

Switch configuration page for multi-host, virtual switch, and NT settings.

<!-- Screenshot: Configuration page -->

---

### 5.6 Topology

**Route:** `/switch/{device_id}/topology`

The topology page provides a comprehensive view of the switch fabric with hardware mapping, connector health, and downstream device identification.

#### Hardware Reference (Expandable)

A collapsible reference section shows static board layout information:

- **Physical Connectors** table -- connector name, type, station assignment, lane range, width, CON ID
- **Station Layout** table -- station index, purpose, port range, connector assignment
- **Data Path Diagram** -- ASCII block diagram showing host-to-switch-to-connector data paths

The reference automatically updates when live data reveals the board variant (e.g., PEX90144, PEX90080, or any B0 variant).

#### Fabric Summary

After clicking **Load Topology**, the fabric summary displays:

- Chip ID (hex), board name, family, station count, total ports
- Ports UP/DOWN counts with color coding
- Lists of upstream and downstream port numbers

#### Connector Health

Per-connector health indicators show at-a-glance link status:

- Green border = all ports up
- Yellow border = some ports up
- Gray border = all ports down
- Each chip shows connector name, type, width, ports up/total, active link speed

#### Station Cards

One card per station with:

- Station header: ID, label, connector badge, port range, up/total count
- Port grid with sub-connector grouping (when a station spans multiple physical connectors)
- Each port tile shows role, link status, speed/width

#### Downstream Device Identification

For downstream ports (DSP) with active links, the topology mapper probes the secondary bus to identify connected endpoints. When a device is found, the port tile shows:

- **Device type badge** (cyan) -- e.g., "NVMe SSD", "Ethernet NIC", "VGA GPU"
- **Vendor:Device ID** -- e.g., `144d:a80a`

Supported device class identifications:

| Class | Subclass | Type |
|-------|----------|------|
| 0x01 | 0x08 | NVMe SSD |
| 0x01 | 0x06 | SATA Controller |
| 0x01 | 0x04 | RAID Controller |
| 0x02 | 0x00 | Ethernet NIC |
| 0x03 | 0x00 | VGA GPU |
| 0x03 | 0x02 | 3D GPU |
| 0x06 | 0x04 | PCI Bridge |
| 0x0C | 0x03 | USB Controller |
| 0x12 | 0x00 | Processing Accelerator |

Unrecognized class/subclass combinations display as `Class 0xNN:NN`.

<!-- Screenshot: Topology page showing station cards with connected NVMe devices on DSP ports -->

---

### 5.7 PCIe Registers

**Route:** `/switch/{device_id}/registers`

A comprehensive PCIe configuration space browser with specialized views for capabilities, device control, link status, and AER.

#### Config Space Dump

Read raw configuration space registers:

1. Set **Offset** (DWORD-aligned hex) and **Count** (number of DWORDs)
2. Click **Read**
3. View formatted hex dump (4 DWORDs per row with offset column)

#### Capabilities

After reading config space, the discovered PCI and PCIe Extended capabilities appear in a table:

| Column | Description |
|--------|-------------|
| ID | Capability ID (hex) |
| Name | Human-readable capability name |
| Offset | Config space offset (hex) |
| Version | Capability version (extended caps only) |

Standard capabilities: Power Management, MSI, MSI-X, PCI Express, etc.
Extended capabilities: AER, SR-IOV, ACS, LTR, L1 PM, Lane Margining, Physical Layer 16/32/64 GT/s, etc.

#### Device Control

View and modify Max Payload Size (MPS) and Max Read Request Size (MRRS):

1. Click **Refresh** to read current values
2. Select new MPS or MRRS from dropdown (128, 256, 512, 1024, 2048, or 4096 bytes)
3. Click **Apply** to write

Additional fields displayed: Relaxed Ordering, No Snoop, Extended Tag, error reporting enables.

#### Link Status

View current link state and modify link training parameters:

| Field | Description |
|-------|-------------|
| Current Speed | Negotiated link speed (e.g., Gen4) |
| Current Width | Negotiated link width (e.g., x16) |
| Target Speed | Target speed for next training (Gen1-Gen6) |
| ASPM Control | Active State Power Management setting |
| Link Training | Whether link training is in progress |
| DLL Link Active | Data Link Layer link active status |

Controls:
- **Set Target Speed** -- select Gen1 through Gen6 from dropdown
- **Retrain Link** -- initiate link retraining

#### AER Status

Advanced Error Reporting provides detailed error status:

**Uncorrectable Errors** (fatal/non-fatal):
- Data Link Protocol, Surprise Down, Poisoned TLP, Flow Control Protocol
- Completion Timeout, Completer Abort, Unexpected Completion, Receiver Overflow
- Malformed TLP, ECRC Error, Unsupported Request, ACS Violation

**Correctable Errors:**
- Receiver Error, Bad TLP, Bad DLLP
- Replay Num Rollover, Replay Timer Timeout, Advisory Non-Fatal

Active errors are highlighted with `!!` in red (uncorrectable) or yellow (correctable). Inactive errors show `--` in gray.

The **Header Log** (4 DWORDs) is displayed for diagnostic analysis of the first error.

Click **Clear Errors** to write-1-to-clear both status registers.

<!-- Screenshot: Registers page showing AER status with active errors highlighted -->

---

### 5.8 EEPROM Viewer

**Route:** `/switch/{device_id}/eeprom`

Read, write, and manage the switch EEPROM contents.

#### EEPROM Status

Click **Probe** to read EEPROM presence and validity:
- **Present** -- whether EEPROM is detected
- **Status** -- valid, invalid, or unknown
- **CRC** -- current CRC value (hex)
- **CRC Status** -- valid (green), invalid (red), or unknown (yellow)

#### Read

1. Set **Offset** (DWORD index) and **Count** (number of DWORDs)
2. Click **Read**
3. View formatted hex dump with address column

#### Write

> **Warning:** EEPROM writes are persistent and may affect device behavior after reset.

1. Enter **Offset** (DWORD index) and **Value** (hex, e.g., `0xDEADBEEF`)
2. Click **Write**
3. Confirm in the confirmation dialog

#### CRC Management

- **Verify** -- read and validate the current CRC
- **Recalculate & Write** -- compute correct CRC and write it to EEPROM

<!-- Screenshot: EEPROM viewer with hex dump and CRC status -->

---

### 5.9 PHY Monitor

**Route:** `/switch/{device_id}/phy`

Comprehensive PHY-layer monitoring and diagnostics.

#### Global Controls

- **Port Number** -- target physical port (range depends on chip variant, e.g., 0-143 for PEX90144)
- **Num Lanes** (1-16) -- number of lanes to query
- **Refresh All** -- reload all sections

#### Supported Link Speeds

Displays Gen1 through Gen6 support with checkmark (green) or cancel (gray) icons per generation.

#### Equalization Status

Two-column display for 16 GT/s and 32 GT/s equalization:

| Field | Description |
|-------|-------------|
| Complete | EQ procedure completed |
| Phase 1/2/3 Success | Individual phase completion |
| Link EQ Request | EQ re-requested |
| Modified TS Received | (32 GT/s only) Modified training sequences |
| RX Lane Margin Capable | (32 GT/s only) Lane margining support |
| No EQ Needed | (32 GT/s only) EQ bypass available |

#### Lane Equalization Settings (16 GT/s)

Per-lane table showing downstream and upstream TX preset and RX hint values.

#### SerDes Diagnostics

Per-lane diagnostic status:

| Column | Description |
|--------|-------------|
| Lane | Lane index |
| Status | SYNC, NO SYNC, PASS, or FAIL |
| Error Count | Accumulated bit errors |
| Expected | Expected pattern (hex) |
| Actual | Received pattern (hex) |

**Clear Errors** button resets counters for a selected lane.

#### Port Control and PHY Cmd/Status

Raw register views for vendor-specific port control (0x3208) and PHY command/status (0x321C) registers.

#### User Test Pattern (UTP)

Run PRBS and fixed-pattern tests across lanes:

1. Select **Pattern**: PRBS-7, PRBS-15, PRBS-31, Alternating, Walking Ones, All Zeros, All Ones
2. Select **Rate**: Gen1 (2.5 GT/s) through Gen6 (64 GT/s)
3. Set **Port Select**
4. Click **Prepare Test**, then **Read Results**

Results table shows per-lane sync status, error count, and pass/fail. Summary shows total passed/failed lanes.

#### Lane Margining

Check for Lane Margining at Receiver extended capability. If present, displays the capability offset. Navigate to the [Eye Diagram](#510-eye-diagram) page for full sweep visualization.

<!-- Screenshot: PHY Monitor showing equalization status and SerDes diagnostics -->

---

### 5.10 Eye Diagram

**Route:** `/switch/{device_id}/eye`

PCIe Lane Margining eye diagram visualization with automated sweep and analysis. Supports both NRZ (Gen1-5, single eye) and PAM4 (Gen6, 3 stacked eyes) modulation.

#### Workflow

1. Set **Port Number** and **Lane**
2. Click **Check Capabilities** to verify margining support and read step limits:
   - Timing Steps / Max Timing Offset (UI)
   - Voltage Steps / Max Voltage Offset (mV)
   - Sample Count (number of samples per measurement point)
   - Independent up/down voltage, left/right timing capability flags
   - **Modulation auto-detection:** The page queries the current link speed and displays "NRZ (Single Eye)" for Gen1-5 or "PAM4 (3 Eyes)" for Gen6
   - **Unsupported margining detection:** If the device reports 0 margining steps, Calypso displays a clear error message instead of attempting a sweep
3. Click **Start Sweep** to begin automated margining
4. Monitor progress bar (updates every 500ms)
5. View the completed eye diagram(s)

#### NRZ Mode (Gen1-5)

A 2D heatmap visualization showing the margining results:

- **X-axis:** Timing Offset (UI)
- **Y-axis:** Voltage Offset (mV)
- **Color gradient:** Green (center/passing) through yellow/orange to red (edge/failing), representing normalized error distance from the eye center
- **Dashed diamond boundary:** Asymmetric eye boundary showing per-direction margins (left/right timing, up/down voltage)
- **No Data detection:** If a receiver doesn't respond (all timeouts), a "No Data" message is displayed instead of a misleading empty chart

The heatmap normalizes timing and voltage error data independently so both axes contribute equally to the visualization. When an axis has no error gradient, step-distance is used as a proxy. The result is an elliptical/irregular eye shape that reflects the actual measured data -- wider when timing margin is larger, asymmetric when left and right margins differ.

#### PAM4 Mode (Gen6)

PCIe Gen6 uses PAM4 signaling with 4 voltage levels, creating 3 vertically stacked eyes. The sweep runs 3 independent margining passes using PCIe Receivers A, B, and C:

- **Upper Eye (Receiver A)** -- cyan accent
- **Middle Eye (Receiver B)** -- blue accent
- **Lower Eye (Receiver C)** -- purple accent

Each eye is displayed as its own heatmap with independent width/height measurements and asymmetric boundary overlays. Non-responsive receivers (e.g., devices that don't support PAM4 margining on a particular eye) show "No Data" instead of a misleading chart. The progress label shows the current eye being swept (e.g., "PAM4 - Upper Eye (1/3) - Step 24/144 (17%)"). Before starting the PAM4 sweep, Calypso probes each receiver to skip non-responsive ones automatically.

**PAM4 Aggregate Summary** (below the 3 charts):

| Metric | Description |
|--------|-------------|
| Worst Eye Width | Minimum width across all 3 eyes |
| Worst Eye Height | Minimum height across all 3 eyes |
| Balance Status | Balanced (3 heights within 20% of average) or Imbalanced |
| Total Sweep Time | Combined duration for all 3 eyes |

#### Sweep Results (per eye)

| Metric | Description |
|--------|-------------|
| Eye Width | Steps and UI measurement |
| Eye Height | Steps and mV measurement |
| Lane / Receiver | Target lane and receiver number (Broadcast for NRZ, A/B/C for PAM4) |
| Sweep Time | Duration in milliseconds |
| Pass/Total | Number of passing vs. total measurement points |

Click **Reset Lane** to clear margining state before re-running.

<!-- Screenshot: Eye diagram with pass/fail scatter plot and eye boundary -->

---

### 5.11 LTSSM Trace

**Route:** `/switch/{device_id}/ltssm`

Link Training and Status State Machine monitoring with retrain observation and Ptrace capture.

#### LTSSM State Snapshot

Read the current LTSSM state for any port:

1. Set **Port Number** (range depends on chip variant) and **Port Select** (0-15)
2. Click **Read Snapshot**

Displayed metrics:

| Field | Description |
|-------|-------------|
| LTSSM State | Current state name and hex code |
| Link Speed | Negotiated speed |
| Recovery Count | Number of recovery entries since last clear |
| Link Down Count | Number of link-down events |
| Lane Reversal | Whether lane reversal is active |
| Rx Eval Count | Receiver evaluation count |

LTSSM states are decoded from 12-bit hardware registers using PCIe 6.0.1 Section 4.2.6 sub-state naming. The upper nibble (bits [11:8]) identifies the top-level state, while the lower byte (bits [7:0]) identifies the sub-state within it. For example, `0x400` decodes as "Recovery.RcvrLock" and `0x305` as "L1.Idle".

States are color-coded by category:
- **Red:** Detect (Detect.Quiet, Detect.Active), Disabled, Hot Reset
- **Orange:** Polling (Polling.Active, Polling.Configuration, Polling.Compliance), Loopback (Entry, Active, Exit)
- **Yellow:** Configuration (Config.Linkwidth.Start, Config.Linkwidth.Accept, Config.Lanenum.Wait, Config.Lanenum.Accept, Config.Complete, Config.Idle)
- **Blue:** Recovery (Recovery.RcvrLock, Recovery.Speed, Recovery.RcvrCfg, Recovery.Idle, Recovery.Equalization)
- **Green:** L0 (normal operation)
- **Cyan:** L0s (L0s.Entry, L0s.Idle, L0s.FTS)
- **Purple:** L1 (L1.Entry, L1.Idle)
- **Muted:** L2 (L2.Idle, L2.TransmitWake)

Enable **Auto-refresh** (1-second interval) for continuous monitoring during link training.

#### Retrain and Watch

Observe the complete LTSSM state machine traversal during a link retrain:

1. Click **Retrain & Watch**
2. The port is briefly disabled (50ms pulse) to force retraining
3. LTSSM state is polled every 20ms
4. Each state transition is recorded with a timestamp
5. Monitoring continues until the link reaches L0 or the timeout expires

Results include:

- **State Transition Chart** -- step-line chart showing state code vs. time (ms), with state names on the Y-axis
- **Transition Log Table** -- timestamp, state code (hex), and state name for each transition
- **Summary** -- final state, final speed, transition count, duration, settled (reached L0) flag

This is invaluable for diagnosing link training failures, speed fallback, and recovery loops.

#### Ptrace Capture

Hardware-level protocol trace capture using the Atlas3 Ptrace engine:

1. Configure: Trace Point (0-15), Lane Select (0-15), optional LTSSM trigger state
2. Click **Configure**, then **Start**
3. Click **Read Status** to check capture progress
4. Click **Stop**, then **Read Buffer** to retrieve captured data

Ptrace entries are displayed in a table with index and raw data (hex).

<!-- Screenshot: LTSSM Trace showing retrain state transition chart -->

---

### 5.12 Error Overview

**Route:** `/switch/{device_id}/errors`

A consolidated error view that merges three independent error sources into a single page for rapid triage.

#### Error Sources

| Source | Scope | Description |
|--------|-------|-------------|
| PCIe AER | Device-level | Advanced Error Reporting uncorrectable and correctable errors |
| MCU Counters | Per-port | Bad TLP, Bad DLLP, Link Down, FLIT Error, Port RX, Rec Diag |
| LTSSM Counters | Per-port | Recovery count, Link Down count, Rx Evaluation count |

#### Summary Cards

Four stat cards at the top provide at-a-glance status:

| Card | Red | Yellow | Green | Gray |
|------|-----|--------|-------|------|
| AER Uncorrectable | > 0 errors | -- | 0 errors | -- |
| AER Correctable | -- | > 0 errors | 0 errors | -- |
| MCU Total Errors | > 0 errors | -- | 0 errors | MCU not connected |
| LTSSM Recoveries | -- | -- | 0 recoveries | -- |

#### AER Detail Panel

Two-column view:

- **Uncorrectable Errors** -- raw register value (hex) + red badges for each active error name
- **Correctable Errors** -- raw register value (hex) + yellow badges for each active error name

Click **Clear AER** to write-1-to-clear both AER status registers.

#### Per-Port Error Table

Combined table with columns from all sources:

| Column | Source |
|--------|--------|
| Port | Port number |
| MCU Bad TLP | MCU |
| MCU Bad DLLP | MCU |
| MCU Link Down | MCU |
| MCU Total | MCU |
| LTSSM Recovery | LTSSM |
| LTSSM Link Down | LTSSM |
| LTSSM Rx Eval | LTSSM |

Columns show `--` when the source is unavailable (e.g., MCU not connected).

Click **Clear MCU Counters** to reset all MCU error counters (appears only when MCU is connected).

#### Auto-Refresh

Toggle the **Auto-refresh (5s)** switch for periodic updates. The status label shows the last update time or any errors.

<!-- Screenshot: Error Overview page with summary cards and per-port table -->

---

### 5.13 Compliance

**Route:** `/switch/{device_id}/compliance`

Automated PCIe compliance testing with 6 test suites, real-time progress tracking, and downloadable HTML reports. Designed for PCIe validation engineers performing link qualification and signal integrity verification.

#### Test Suites

| Suite | ID | Tests/Port | Description |
|-------|-----|-----------|-------------|
| Link Training | T1 | 4 | Speed negotiation, LTSSM state validation, EQ phase verification, recovery count baseline |
| Error Audit | T2 | 3 | AER error audit, error reporting enables, error-free operation hold |
| Config Audit | T3 | 4 | Capability list integrity, MPS/MRRS validation, link capability consistency, supported speeds contiguity |
| Signal Integrity | T4 | ~20 | Lane margining eye measurement (per-lane, NRZ single-eye or PAM4 3-eye), spec minimum eye check, per-lane margin comparison, PAM4 eye balance check (Gen6) |
| BER Test | T5 | ~18 | PRBS31 per-lane BER at current speed, multi-speed BER across all supported Gen3+ speeds |
| Port Sweep | T6 | 3 (total) | All-port link status, all-port error sweep, all-port recovery count audit |

Test count scales with the number of ports and lanes selected. Port Sweep (T6) runs once per compliance run, not per-port.

#### Thresholds

Spec-aligned pass/fail thresholds derived from PCIe CEM 6.0 and PCIe Base Spec 6.0.1:

| Generation | Min Eye Width (UI) | Min Eye Height (mV) | Max BER | Signaling |
|------------|-------------------|---------------------|---------|-----------|
| Gen3 (8 GT/s) | 0.30 | 15 | 1e-12 | NRZ |
| Gen4 (16 GT/s) | 0.25 | 15 | 1e-12 | NRZ |
| Gen5 (32 GT/s) | 0.20 | 10 | 1e-6 | NRZ with FEC |
| Gen6 (64 GT/s) | 0.15 | 8 | 1e-6 | PAM4 |

Signal integrity tests also flag lanes whose measured eye is >30% below the per-port average (outlier detection). For Gen6 (PAM4), each lane produces 3 eye measurements (upper, middle, lower); the per-lane comparison uses the worst-case eye per lane. An additional T4.4 balance check warns if the 3 PAM4 eye heights deviate >20% from their average, indicating transmitter or channel linearity issues.

#### Configuration

**Test Suite Selection:** Checkboxes for all 6 suites (all enabled by default).

**Port Configuration:** Multi-port support with add/remove controls. Per-port inputs:

| Parameter | Range | Default |
|-----------|-------|---------|
| Port Number | Chip-dependent (e.g., 0-143) | 0 |
| Port Select | 0-15 | 0 |
| Lane Count | 1-16 | 16 |

**Timing Parameters:**

| Parameter | Range | Default | Purpose |
|-----------|-------|---------|---------|
| BER Duration | 1-300s | 10s | Duration of PRBS pattern test per speed |
| Idle Wait | 1-60s | 5s | Idle hold period for error-free operation tests |
| Speed Settle | 0.5-10s | 2s | Delay after speed change to allow link training |

#### Running a Compliance Test

1. Select test suites (or leave all enabled for a full compliance run)
2. Configure target port(s) -- port number, port select, and lane count
3. Adjust timing parameters if needed (defaults are suitable for most cases)
4. Click **Start Test Run**
5. Monitor progress: current suite/test name, completion percentage, elapsed time
6. On completion, review results summary and per-suite tables
7. Click **Download Report** for a self-contained HTML report

#### Progress Display

- Linear progress bar with percentage
- Current suite and test name
- Tests completed / total count
- Elapsed time in seconds
- Auto-updates every 1 second

#### Results

After completion, the page displays:

- **Summary:** Overall verdict (PASS/FAIL/WARN/ERROR), total pass/fail/warn/skip/error counts, run duration
- **Per-Suite Tables:** Each suite shows test ID, test name, verdict badge (color-coded), result message, and execution time
- **Verdicts:** PASS (green), FAIL (red), WARN (yellow), SKIP (gray), ERROR (red)

#### HTML Report

Click **Download Report** to generate a self-contained HTML file including:

- Device metadata (ID, chip, revision, timestamp)
- Executive summary with proportional pass/fail bar chart
- Per-suite result tables
- Signal integrity eye width/height bar charts (when T4 was run)
- BER results table with per-lane and per-speed data (when T5 was run)
- Dark-themed styling matching the Calypso dashboard

The report requires no external dependencies and can be shared as a standalone file.

#### Cancellation

Click **Cancel** to request cancellation of a running test. The engine completes the current test, marks remaining tests as SKIP, and returns partial results.

<!-- Screenshot: Compliance page with test suite selection, progress bar, and per-suite result tables -->

---

### 5.14 Workloads (Linux only)

**Route:** `/switch/{device_id}/workloads`

NVMe workload generation with optional combined host+switch performance correlation. Requires the SPDK or pynvme backend, both of which are Linux-only.

> Requires SPDK (`spdk_nvme_perf` on PATH) or pynvme. Backend availability is shown at the top of the page.

#### Configuration

| Parameter | Description | Options |
|-----------|-------------|---------|
| Backend | Workload engine | spdk, pynvme |
| Target BDF | NVMe device address | e.g., `0000:01:00.0` |
| Workload Type | I/O pattern | randread, randwrite, read, write, randrw, rw |
| IO Size | Block size in bytes | 512+ |
| Queue Depth | I/O queue depth | 1+ |
| Duration | Test duration in seconds | 1+ |
| Read % | Read/write mix percentage | 0-100 (for randrw/rw) |
| Workers | Number of I/O workers | 1+ |
| Core Mask | CPU core affinity mask | Hex (SPDK only) |

#### Live Progress

During workload execution:
- Progress bar with elapsed/total time
- Real-time IOPS and bandwidth via WebSocket stream
- Spinner with status indicator

#### Results

| Metric | Description |
|--------|-------------|
| IOPS Total/Read/Write | I/O operations per second |
| BW Total/Read/Write | Bandwidth in MB/s |
| Latency Avg/Max/p50/p99/p999 | Latency percentiles in microseconds |
| CPU Usage | CPU utilization percentage |

#### Combined Host+Switch View

After workload completion, view host workload metrics alongside switch performance counters to correlate NVMe I/O with switch-level bandwidth and utilization.

#### Workload History

A table of all workloads run during the session with ID, backend, BDF, state, IOPS, and bandwidth.

<!-- Screenshot: Workloads page with progress bar and combined view -->

---

### 5.15 MCU Pages

The MCU pages communicate with the Atlas3 microcontroller over a serial (USB) connection. Ensure the MCU is connected on the Discovery page before navigating to these pages.

#### Health (`/mcu/health`)

Real-time telemetry with 2-second auto-refresh:

| Metric | Unit |
|--------|------|
| Temperature | °C (green < 60°C, yellow < 80°C, red >= 80°C) |
| Fan Speed | RPM |
| Voltage Rails | 1V5, VDD, VDDA, VDDA12 (volts) |
| Power | Voltage (V), Current (A), Power (W) |

#### Port Status (`/mcu/ports`)

Per-port link status from the MCU perspective with 5-second auto-refresh. Four tables group ports by role:

- Upstream Ports
- External MCIO Ports
- Internal MCIO Ports
- Straddle Ports

Columns: Station, Connector, Port, Negotiated Speed, Negotiated Width, Max Speed, Max Width, Status, Type.

#### Error Counters (`/mcu/errors`)

Per-port error counters with 3-second auto-refresh:

| Counter | Description |
|---------|-------------|
| Port RX | Receive errors |
| Bad TLP | Malformed Transaction Layer Packets |
| Bad DLLP | Malformed Data Link Layer Packets |
| Rec Diag | Recovery diagnostics |
| Link Down | Link-down events |
| FLIT Error | Flow-control unit errors |

Summary shows total errors and number of ports with non-zero counters. Click **Clear Counters** to reset all.

#### Configuration (`/mcu/config`)

MCU operating parameters with 5-second auto-refresh:

| Section | Controls |
|---------|----------|
| Operation Mode | Select mode 1-4, Apply |
| Clock Output | Read-only: Straddle, Ext MCIO, Int MCIO enable status |
| Spread Spectrum | Off, Down 2500ppm, Down 5000ppm; Apply |
| FLIT Mode | Read-only: Station 2/5/7/8 enable status |
| SDB Target | USB or MCU; Apply |

#### Diagnostics (`/mcu/diagnostics`)

Advanced diagnostic operations:

- **Version Info** -- company, model, serial number, MCU version, build time, SBR version
- **Built-In Self Test (BIST)** -- run BIST and view per-device pass/fail results
- **Register Read** -- read MCU registers by address (hex) and count
- **Reset MCU** -- reset the microcontroller (disconnects active sessions)

<!-- Screenshot: MCU Health page showing temperature, fan, and power metrics -->

---

### 5.16 I2C/I3C Bus Explorer

**Route:** `/mcu/bus`

Low-level I2C and I3C bus access for probing devices on the Atlas3 backplane. Organized into two tabs.

#### I2C Tab

**Bus Selection:** Choose connector (0-5) and channel (a/b) for all I2C operations.

**Bus Scan:** Click **Scan Bus** to enumerate all responding I2C addresses on the selected connector/channel. Results appear in a table with decimal and hex addresses.

**I2C Read:** Read data from a specific device:

| Parameter | Description |
|-----------|-------------|
| Address | I2C slave address (hex, e.g., `0x50`) |
| Register | Starting register offset (hex) |
| Count | Number of bytes to read (1-256) |

Data is displayed as a hex dump with offset column and ASCII decode.

**I2C Write:** Write data to a device:

| Parameter | Description |
|-----------|-------------|
| Address | I2C slave address (hex) |
| Data | Comma-separated hex bytes (e.g., `0x00,0x01`) |

#### I3C Tab

**Bus Selection:** Same connector/channel selector as I2C.

**I3C ENTDAA Discovery:** Run the Enter Dynamic Address Assignment procedure to discover I3C devices. Results table shows:

| Column | Description |
|--------|-------------|
| Address | Assigned dynamic address |
| Provisional ID | 48-bit PID (hex) |
| BCR | Bus Characteristics Register |
| DCR | Device Characteristics Register |
| MCTP | Whether device supports MCTP |

**I3C Read/Write:** Same interface as I2C read/write, operating over I3C with a register address field.

<!-- Screenshot: I2C/I3C Bus Explorer showing bus scan results and hex dump -->

---

### 5.17 NVMe Drives

**Route:** `/mcu/nvme`

NVMe drive discovery and SMART health monitoring via NVMe-MI over MCTP through the MCU serial connection. This enables drive health monitoring without requiring PCIe enumeration.

#### Scan Controls

Configure connector and channel filters, then click **Scan** to discover NVMe drives on the backplane.

#### Drive Cards

Each discovered drive is displayed as a card with:

- **Temperature gauge** -- color-coded: green (< 50C), yellow (50-70C), red (> 70C)
- **Available Spare bar** -- percentage remaining, color-coded: green (> 30%), yellow (10-30%), red (< 10%)
- **Drive Life bar** -- percentage used indicator
- **Critical Warning flags** -- active flags shown as badges:

| Flag | Description |
|------|-------------|
| Spare Below Threshold | Available spare has dropped below threshold |
| Temperature Exceeded | Composite temperature exceeded critical limit |
| Reliability Degraded | NVM subsystem reliability degraded |
| Read-Only Mode | Media placed in read-only mode |
| Volatile Backup Failed | Volatile memory backup device has failed |

#### Per-Controller Detail

Expandable section per drive showing per-controller breakdown with temperature, spare percentage, percentage used, and warning status.

<!-- Screenshot: NVMe Drives page showing drive cards with temperature gauges and health bars -->

---

## 6. Hardware Reference

### Supported Chip Variants

Calypso supports two generations of Atlas3 silicon:

| Generation | Chip | ChipID | Lanes | Stations | Port Range |
|------------|------|--------|-------|----------|------------|
| A0 | PEX90144 | 0x0144 | 144 | 6 | 0-143 |
| A0 | PEX90080 | 0x0080 | 80 | 4 | 0-111 |
| B0 | PEX90024 | 0xA024 | 24 | 2 | 0-15, 24-31 |
| B0 | PEX90032 | 0xA032 | 32 | 2 | 0-31 |
| B0 | PEX90048 | 0xA048 | 48 | 3 | 0-47 |
| B0 | PEX90064 | 0xA064 | 64 | 4 | 0-31, 48-79 |
| B0 | PEX90080-B0 | 0xA080 | 80 | 5 | 0-79 |
| B0 | PEX90096 | 0xA096 | 96 | 6 | 0-95 |

Both generations share the same Atlas3 family identifiers (PLX_FAMILY_ATLAS_3 and PLX_FAMILY_ATLAS3_LLC). Device discovery uses family-based filtering and automatically detects the specific variant.

> **Note:** B0 silicon connector maps are pending from Broadcom and will be added in a future update. B0 station maps use generic labels. The topology page will display station layout but without physical connector assignments.

### PEX90144 Station Map (A0, 144 lanes)

| Station | Port Range | Connector | Purpose |
|---------|-----------|-----------|---------|
| STN0 | 0-15 | -- | Root Complex |
| STN1 | 16-31 | -- | Reserved |
| STN2 | 32-47 | Golden Finger | Host PCIe x16 upstream |
| STN5 | 80-95 | CN4 (Straddle) | PCIe straddle connector |
| STN7 | 112-127 | CN0/CN1 (Ext MCIO) | External MCIO |
| STN8 | 128-143 | CN2/CN3 (Int MCIO) | Internal MCIO |

### PEX90080 Station Map (A0, 80 lanes)

| Station | Port Range | Connector | Purpose |
|---------|-----------|-----------|---------|
| STN0 | 0-15 | CN2/CN3 (Int MCIO) | Internal MCIO |
| STN1 | 16-31 | Golden Finger | Host PCIe x16 upstream |
| STN2 | 32-47 | CN0/CN1 (Ext MCIO) | External MCIO |
| STN6 | 96-111 | CN4 (Straddle) | PCIe straddle connector |

### Connector Pinout

| Connector | PEX90144 Lanes (Station) | PEX90080 Lanes (Station) | Type |
|-----------|-------------------------|-------------------------|------|
| CN0 | 120-127 (STN7) | 40-47 (STN2) | Ext MCIO |
| CN1 | 112-119 (STN7) | 32-39 (STN2) | Ext MCIO |
| CN2 | 136-143 (STN8) | 8-15 (STN0) | Int MCIO |
| CN3 | 128-135 (STN8) | 0-7 (STN0) | Int MCIO |
| CN4 | 80-95 (STN5) | 96-111 (STN6) | Straddle |

### Data Path (PEX90144)

```
[Host CPU] <--x16--> [Golden Finger / STN2]
                             |
                    [Atlas3 PEX90144 Switch]
                      /      |       \
                STN0(RC)   STN1(Rsvd)  STN5(Straddle/CN4)
                                        x16
                      /               \
         STN7(Ext MCIO)            STN8(Int MCIO)
         CN1[112:119]x8            CN3[128:135]x8
         CN0[120:127]x8            CN2[136:143]x8
```

### Data Path (PEX90080)

```
[Host CPU] <--x16--> [Golden Finger / STN1]
                             |
                    [Atlas3 PEX90080 Switch]
                      /      |       \
                STN0(Int MCIO)  STN2(Ext MCIO)  STN6(Straddle)
                CN2[8:15]x8     CN0[40:47]x8     CN4[96:111]x16
                CN3[0:7]x8      CN1[32:39]x8
```

### B0 Silicon Station Maps

B0 variants have simplified station layouts with generic station labels. Physical connector assignments are pending from Broadcom.

#### PEX90024 (2 stations)

| Station | Port Range | Label |
|---------|-----------|-------|
| STN0 | 0-15 | Station 0 |
| STN1 | 24-31 | Station 1 (partial) |

#### PEX90032 (2 stations)

| Station | Port Range | Label |
|---------|-----------|-------|
| STN0 | 0-15 | Station 0 |
| STN1 | 16-31 | Station 1 |

#### PEX90048 (3 stations)

| Station | Port Range | Label |
|---------|-----------|-------|
| STN0 | 0-15 | Station 0 |
| STN1 | 16-31 | Station 1 |
| STN2 | 32-47 | Station 2 |

#### PEX90064 (4 stations)

| Station | Port Range | Label |
|---------|-----------|-------|
| STN0 | 0-15 | Station 0 |
| STN1 | 16-31 | Station 1 |
| STN3 | 48-63 | Station 3 |
| STN4 | 64-79 | Station 4 |

> **Note:** PEX90064 skips station 2. Port numbers 32-47 are not available on this variant.

#### PEX90080-B0 (5 stations)

| Station | Port Range | Label |
|---------|-----------|-------|
| STN0 | 0-15 | Station 0 |
| STN1 | 16-31 | Station 1 |
| STN2 | 32-47 | Station 2 |
| STN3 | 48-63 | Station 3 |
| STN4 | 64-79 | Station 4 |

#### PEX90096 (6 stations)

| Station | Port Range | Label |
|---------|-----------|-------|
| STN0 | 0-15 | Station 0 |
| STN1 | 16-31 | Station 1 |
| STN2 | 32-47 | Station 2 |
| STN3 | 48-63 | Station 3 |
| STN4 | 64-79 | Station 4 |
| STN5 | 80-95 | Station 5 |

---

## Appendix A: REST API Reference

The API server runs alongside the web dashboard. Interactive documentation is available at `http://localhost:8000/docs` (Swagger UI).

All device endpoints are prefixed with `/api/devices`. MCU endpoints are prefixed with `/api/mcu`. Workload endpoints are prefixed with `/api`.

### Device Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/devices/scan` | Scan for devices. Body: `{transport, port, baud_rate}` |
| `GET` | `/api/devices` | List connected device IDs |
| `POST` | `/api/devices/connect` | Connect to a device. Body: `{transport, device_index, port}` |
| `POST` | `/api/devices/{id}/disconnect` | Disconnect a device |
| `GET` | `/api/devices/{id}` | Get device info |
| `POST` | `/api/devices/{id}/reset` | Reset a device |

### Ports

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/devices/{id}/ports` | List all port statuses |
| `GET` | `/api/devices/{id}/ports/{port}` | Get single port status |

### Performance

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/devices/{id}/perf/start` | Start performance monitoring |
| `POST` | `/api/devices/{id}/perf/stop` | Stop performance monitoring |
| `GET` | `/api/devices/{id}/perf/snapshot` | Get single performance snapshot |
| `WS` | `/api/devices/{id}/perf/stream` | WebSocket stream of snapshots |

### Configuration

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/devices/{id}/config` | Get switch configuration |

### Topology

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/devices/{id}/topology` | Get fabric topology with connected device enumeration |

### PCIe Registers

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/devices/{id}/config-space` | Read config space. Params: `offset`, `count` |
| `GET` | `/api/devices/{id}/capabilities` | List PCI/PCIe capabilities |
| `GET` | `/api/devices/{id}/device-control` | Read device control (MPS/MRRS) |
| `POST` | `/api/devices/{id}/device-control` | Write device control. Body: `{mps, mrrs}` |
| `GET` | `/api/devices/{id}/link` | Read link capabilities and status |
| `POST` | `/api/devices/{id}/link/retrain` | Initiate link retrain |
| `POST` | `/api/devices/{id}/link/target-speed` | Set target speed. Body: `{speed: 1-6}` |
| `GET` | `/api/devices/{id}/aer` | Read AER status |
| `POST` | `/api/devices/{id}/aer/clear` | Clear AER error registers |

### EEPROM

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/devices/{id}/eeprom/info` | EEPROM presence and status |
| `GET` | `/api/devices/{id}/eeprom/read` | Read DWORDs. Params: `offset`, `count` |
| `POST` | `/api/devices/{id}/eeprom/write` | Write DWORD. Body: `{offset, value}` |
| `GET` | `/api/devices/{id}/eeprom/crc` | Read and verify CRC |
| `POST` | `/api/devices/{id}/eeprom/crc/update` | Recalculate and write CRC |

### PHY

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/devices/{id}/phy/speeds` | Supported link speed vector |
| `GET` | `/api/devices/{id}/phy/eq-status` | Equalization status (16/32 GT/s) |
| `GET` | `/api/devices/{id}/phy/lane-eq` | Lane EQ settings. Params: `port_number`, `num_lanes` |
| `GET` | `/api/devices/{id}/phy/serdes-diag` | SerDes diagnostics. Params: `port_number`, `num_lanes` |
| `POST` | `/api/devices/{id}/phy/serdes-diag/clear` | Clear SerDes errors. Params: `port_number`. Body: `{lane}` |
| `GET` | `/api/devices/{id}/phy/port-control` | Port control register. Params: `port_number` |
| `GET` | `/api/devices/{id}/phy/cmd-status` | PHY cmd/status register. Params: `port_number` |
| `GET` | `/api/devices/{id}/phy/lane-margining` | Check lane margining capability |
| `POST` | `/api/devices/{id}/phy/utp/prepare` | Prepare UTP test. Params: `port_number`. Body: `{preset, rate, port_select}` |
| `GET` | `/api/devices/{id}/phy/utp/results` | Read UTP results. Params: `port_number`, `num_lanes` |
| `POST` | `/api/devices/{id}/phy/utp/load` | Load UTP pattern. Params: `port_number`. Body: `{preset, pattern_hex}` |
| `GET` | `/api/devices/{id}/phy/margining/capabilities` | Margining capabilities. Params: `port_number`, `lane` |
| `POST` | `/api/devices/{id}/phy/margining/sweep` | Start margining sweep. Body: `{lane, port_number, receiver}` |
| `GET` | `/api/devices/{id}/phy/margining/progress` | Sweep progress. Params: `lane` |
| `GET` | `/api/devices/{id}/phy/margining/result` | Sweep result. Params: `lane` |
| `POST` | `/api/devices/{id}/phy/margining/reset` | Reset lane margining. Body: `{lane, port_number}` |
| `POST` | `/api/devices/{id}/phy/margining/sweep-pam4` | Start PAM4 3-eye sweep (Receivers A/B/C). Body: `{lane, port_number}` |
| `GET` | `/api/devices/{id}/phy/margining/progress-pam4` | Poll PAM4 sweep progress. Params: `lane` |
| `GET` | `/api/devices/{id}/phy/margining/result-pam4` | Get PAM4 3-eye sweep result. Params: `lane` |

### LTSSM

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/devices/{id}/ltssm/snapshot` | LTSSM state snapshot. Params: `port_number`, `port_select` |
| `POST` | `/api/devices/{id}/ltssm/clear-counters` | Clear recovery counters. Body: `{port_number, port_select}` |
| `POST` | `/api/devices/{id}/ltssm/retrain` | Start retrain-and-watch. Body: `{port_number, port_select, timeout_s}` |
| `GET` | `/api/devices/{id}/ltssm/retrain/progress` | Retrain progress. Params: `port_number`, `port_select` |
| `GET` | `/api/devices/{id}/ltssm/retrain/result` | Retrain result. Params: `port_number`, `port_select` |
| `POST` | `/api/devices/{id}/ltssm/ptrace/configure` | Configure Ptrace. Body: `{port_number, port_select, trace_point, lane_select, trigger_on_ltssm, ltssm_trigger_state}` |
| `POST` | `/api/devices/{id}/ltssm/ptrace/start` | Start Ptrace. Body: `{port_number}` |
| `POST` | `/api/devices/{id}/ltssm/ptrace/stop` | Stop Ptrace. Body: `{port_number}` |
| `GET` | `/api/devices/{id}/ltssm/ptrace/status` | Ptrace status. Params: `port_number` |
| `GET` | `/api/devices/{id}/ltssm/ptrace/buffer` | Read Ptrace buffer. Params: `port_number`, `max_entries` |

### Errors

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/devices/{id}/errors/overview` | Combined error overview. Params: `mcu_port` (optional) |
| `POST` | `/api/devices/{id}/errors/clear-aer` | Clear AER errors |
| `POST` | `/api/devices/{id}/errors/clear-mcu` | Clear MCU counters. Params: `mcu_port` |

### Compliance

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/devices/{id}/compliance/start` | Start compliance test run. Body: `{suites, ports, ber_duration_s, idle_wait_s, speed_settle_s}` |
| `GET` | `/api/devices/{id}/compliance/progress` | Poll test run progress (status, current suite/test, percent, elapsed) |
| `GET` | `/api/devices/{id}/compliance/result` | Get completed test run result (all suite results, verdicts, metrics) |
| `POST` | `/api/devices/{id}/compliance/cancel` | Request cancellation of running test |
| `GET` | `/api/devices/{id}/compliance/report` | Download HTML compliance report (attachment) |

### MCU

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/mcu/discover` | Discover MCU devices on serial ports |
| `POST` | `/api/mcu/connect` | Connect to MCU. Params: `port` |
| `POST` | `/api/mcu/disconnect` | Disconnect MCU. Params: `port` |
| `GET` | `/api/mcu/version` | MCU firmware version. Params: `port` |
| `GET` | `/api/mcu/info` | MCU device info. Params: `port` |
| `GET` | `/api/mcu/health` | Thermal/power/fan telemetry. Params: `port` |
| `GET` | `/api/mcu/ports` | Port status via MCU. Params: `port` |
| `GET` | `/api/mcu/errors` | Error counters. Params: `port` |
| `POST` | `/api/mcu/errors/clear` | Clear error counters. Params: `port` |
| `GET` | `/api/mcu/config/clock` | Clock output status. Params: `port` |
| `GET` | `/api/mcu/config/spread` | Spread spectrum status. Params: `port` |
| `GET` | `/api/mcu/config/flit` | FLIT mode status. Params: `port` |
| `POST` | `/api/mcu/config/mode` | Set operation mode. Params: `port`, `mode` (1-4) |
| `POST` | `/api/mcu/bist` | Run Built-In Self Test. Params: `port` |

### MCU I2C/I3C Bus

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/mcu/i2c/scan` | Scan I2C bus for devices. Body: `{port, connector, channel}` |
| `POST` | `/api/mcu/i2c/read` | Read from I2C device. Body: `{port, connector, channel, address, register, read_bytes}` |
| `POST` | `/api/mcu/i2c/write` | Write to I2C device. Body: `{port, connector, channel, address, data}` |
| `POST` | `/api/mcu/i3c/read` | Read from I3C device. Body: `{port, connector, channel, address, register, read_bytes}` |
| `POST` | `/api/mcu/i3c/write` | Write to I3C device. Body: `{port, connector, channel, address, register, data}` |
| `POST` | `/api/mcu/i3c/entdaa` | Run I3C ENTDAA discovery. Body: `{port, connector, channel}` |

### NVMe-MI (via MCU)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/mcu/nvme/discover` | Scan all connectors for NVMe drives. Params: `port` |
| `GET` | `/api/mcu/nvme/health` | Poll SMART health from a drive. Params: `port`, `connector`, `channel`, `address` |
| `GET` | `/api/mcu/nvme/drive` | Get combined identity and health info. Params: `port`, `connector`, `channel`, `address` |

### Workloads (Linux only)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/workloads/backends` | List available backends |
| `POST` | `/api/workloads/start` | Start workload. Body: `WorkloadConfig` |
| `POST` | `/api/workloads/{wid}/stop` | Stop workload |
| `GET` | `/api/workloads/{wid}` | Get workload status |
| `GET` | `/api/workloads` | List all workloads |
| `GET` | `/api/workloads/{wid}/combined/{id}` | Combined host+switch view |
| `WS` | `/api/workloads/{wid}/stream` | WebSocket workload progress stream |

---

## Appendix B: CLI Reference

### Global Options

```
calypso [--debug] [--json-output] <command>
```

| Option | Description |
|--------|-------------|
| `--debug` | Enable debug logging |
| `--json-output` | Output in JSON format |

### Common Transport Options

Most device commands accept these options:

| Option | Description | Default |
|--------|-------------|---------|
| `--transport` | Transport mode: `pcie`, `uart`, `sdb` | `pcie` |
| `--port` | Serial port for UART/SDB | `0` |
| `--baud` | Baud rate for UART/SDB | `115200` |

### Device Commands

```bash
# Scan for devices
calypso scan [--transport {pcie|uart|sdb}] [--port PORT] [--baud {19200|115200}]

# Device information
calypso info DEVICE_INDEX [--transport ...] [--port ...]

# Port statuses
calypso ports DEVICE_INDEX [--transport ...] [--port ...]

# Performance monitoring
calypso perf DEVICE_INDEX [--interval MS] [--count N] [--transport ...] [--port ...]
```

### PCIe Config Space

```bash
# Dump config registers
calypso pcie config-space DEVICE_INDEX [--offset OFFSET] [--count COUNT]

# List capabilities
calypso pcie caps DEVICE_INDEX

# Link speed and width
calypso pcie link DEVICE_INDEX

# Retrain link
calypso pcie retrain DEVICE_INDEX

# Set target link speed (Gen1=1, Gen2=2, ..., Gen6=6)
calypso pcie set-speed DEVICE_INDEX --speed {1|2|3|4|5|6}

# Device control (MPS/MRRS)
calypso pcie device-control DEVICE_INDEX [--mps {128|256|512|1024|2048|4096}]
                                         [--mrrs {128|256|512|1024|2048|4096}]

# AER error status
calypso pcie aer DEVICE_INDEX [--clear]
```

### EEPROM

```bash
# EEPROM presence and status
calypso eeprom info DEVICE_INDEX

# Read DWORDs
calypso eeprom read DEVICE_INDEX [--offset OFFSET] [--count COUNT]

# Write a DWORD
calypso eeprom write DEVICE_INDEX --offset OFFSET --value VALUE

# Verify or update CRC
calypso eeprom crc DEVICE_INDEX [--update]
```

### PHY Diagnostics

```bash
# Supported link speeds
calypso phy speeds DEVICE_INDEX

# Equalization status
calypso phy eq-status DEVICE_INDEX

# Lane equalization settings
calypso phy lane-eq DEVICE_INDEX --port-number PORT --num-lanes N

# SerDes diagnostics
calypso phy serdes-diag DEVICE_INDEX --port-number PORT [--num-lanes N] [--clear LANE]

# Port control register
calypso phy port-control DEVICE_INDEX --port-number PORT

# PHY command/status register
calypso phy cmd-status DEVICE_INDEX --port-number PORT

# User Test Pattern
calypso phy utp-test DEVICE_INDEX --port-number PORT \
    --pattern {prbs7|prbs15|prbs31|alternating|walking_ones|zeros|ones} \
    --rate {0|1|2|3|4|5} [--port-select N] [--num-lanes N]

# Lane margining capability check
calypso phy margining DEVICE_INDEX
```

### MCU (Serial)

```bash
# Discover devices
calypso mcu --port PORT discover

# Firmware version
calypso mcu --port PORT version

# Health telemetry
calypso mcu --port PORT health

# Port status
calypso mcu --port PORT ports

# Error counters
calypso mcu --port PORT errors [--clear]

# Built-In Self Test
calypso mcu --port PORT bist

# Set operation mode
calypso mcu --port PORT set_mode {1|2|3|4}

# Show configuration
calypso mcu --port PORT config
```

### I2C/I3C Bus (via MCU Serial)

```bash
# Scan I2C bus for responding devices
calypso mcu --port PORT i2c-scan --connector C --channel CH

# Read bytes from I2C device
calypso mcu --port PORT i2c-read --connector C --channel CH \
    --address 0xAA [--register 0x00] [--count 16]

# Write bytes to I2C device
calypso mcu --port PORT i2c-write --connector C --channel CH \
    --address 0xAA --data 0x00,0x01,...

# Run I3C ENTDAA discovery
calypso mcu --port PORT i3c-scan --connector C --channel CH

# Read from I3C target device
calypso mcu --port PORT i3c-read --connector C --channel CH \
    --address 0xAA [--register 0x0000] [--count 16]

# Write to I3C target device
calypso mcu --port PORT i3c-write --connector C --channel CH \
    --address 0xAA [--register 0x0000] --data 0x00,0x01,...
```

| Option | Description |
|--------|-------------|
| `--connector, -c` | Connector index (0-5) |
| `--channel, -ch` | I2C/I3C channel (`a` or `b`) |
| `--address, -a` | Target device address (hex or decimal) |
| `--register, -r` | Register offset (hex or decimal, default 0) |
| `--count, -n` | Number of bytes to read (default 16) |
| `--data, -d` | Comma-separated hex/decimal bytes to write |

### NVMe-MI (via MCU Serial)

```bash
# Scan all connectors for NVMe drives
calypso mcu --port PORT nvme discover

# Poll SMART health from a drive
calypso mcu --port PORT nvme health --connector C --channel CH [--address 0x6A]
```

### NVMe Workloads (Linux only)

```bash
# Show available backends
calypso workloads backends

# Validate NVMe device
calypso workloads validate --bdf BDF [--backend {spdk|pynvme}]

# Run workload
calypso workloads run --backend {spdk|pynvme} --bdf BDF \
    [--workload {randread|randwrite|read|write|randrw|rw}] \
    [--io-size SIZE] [--queue-depth QD] [--duration SECONDS] \
    [--read-pct PCT] [--workers N] [--core-mask MASK] \
    [--with-switch-perf] [--device-index IDX]
```

### Driver Management

```bash
calypso driver status      # Check driver/service status
calypso driver check       # Check prerequisites
calypso driver build       # Build PlxSvc module and PlxApi library (Linux only)
calypso driver install     # Install and start driver/service
calypso driver uninstall   # Stop and remove driver/service
```

On Linux, `install`/`uninstall` require sudo. On Windows, they require administrator privileges. The `build` command is Linux-only; the Windows driver is prebuilt and vendored.

### Web Server

```bash
calypso serve [--host HOST] [--port PORT] [--no-ui]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--host` | Bind address | `127.0.0.1` |
| `--port` | Bind port | `8000` |
| `--no-ui` | Disable web dashboard (API only) | Disabled |

---

## Appendix C: Troubleshooting

### Device Not Found

**Symptom:** `calypso scan` returns no devices.

**Checks:**
1. Verify the Atlas3 card is seated in the PCIe slot
2. Linux: ensure `PlxSvc` module is loaded (`calypso driver status`)
3. Windows: verify PlxSvc service is running (`calypso driver status`), install with `calypso driver install` if needed
4. Check `PLX_SDK_DIR` points to the correct SDK location

### PlxApi Library Not Found

**Symptom:** `ImportError` or `OSError` on startup.

**Checks:**
1. Place the SDK in `vendor/plxsdk/` or set `PLX_SDK_DIR`
2. Linux: verify `libPlxApi.so` exists and has correct permissions
3. Windows: verify `PlxApi.dll` is accessible and not blocked

### MCU Connection Failed

**Symptom:** MCU connect returns error or times out.

**Checks:**
1. Verify the USB cable is connected to the Atlas3 MCU port
2. Check the serial port name (`COM3` on Windows, `/dev/ttyUSB0` on Linux)
3. Ensure no other application has the serial port open
4. Try both baud rates (115200 and 19200)

### Link Training Failure

**Symptom:** Downstream port shows "DOWN" after device insertion.

**Diagnostic workflow:**
1. Navigate to **LTSSM Trace** and read a snapshot -- check if stuck in Detect, Polling, or Configuration
2. Use **Retrain & Watch** to observe the full training sequence
3. Check **PHY Monitor > Equalization Status** for EQ phase failures
4. Check **Error Overview** for AER uncorrectable errors (e.g., Data Link Protocol, Receiver Overflow)
5. Verify cable integrity and connector seating

### Performance Lower Than Expected

**Symptom:** Bandwidth below theoretical maximum.

**Diagnostic workflow:**
1. Check **Ports** page -- confirm negotiated speed and width match expectations
2. Check **PCIe Registers > Device Control** -- verify MPS and MRRS are maximized
3. Use **Performance Monitor** to identify bottleneck ports (high utilization, asymmetric traffic)
4. Check **PHY Monitor > SerDes Diagnostics** for bit errors on active lanes
5. Check **Error Overview** for correctable errors (Bad TLP, Bad DLLP) indicating signal integrity issues

### Recovery Loops

**Symptom:** Link repeatedly enters Recovery state.

**Diagnostic workflow:**
1. Check **LTSSM Trace** -- enable auto-refresh and observe state oscillation
2. Read **Recovery Count** -- rapidly incrementing count confirms recovery loops
3. Use **Eye Diagram** to measure timing and voltage margins on the affected lane
4. Check **Error Overview > LTSSM Recoveries** for the affected port
5. Consider reducing target link speed via **PCIe Registers > Link Status > Set Target Speed**

---

*Serial Cables -- Atlas3 PCIe Switch Manager*
