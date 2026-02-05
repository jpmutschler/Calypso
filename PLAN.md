# Implementation Plan: Serialcables-Calypso (PCIe Gen6 Atlas3 Host Card Tooling)

## Requirements Restatement

Build a Python-wrapped C API, CLI, and browser-based UI for configuring and monitoring the Broadcom PCIe Gen6 Atlas3 switch on the Serial Cables Atlas3 Host Card. The system must:

1. **Wrap the Broadcom PLX SDK C API** in a clean Python layer using ctypes (building on the existing SDK Python bindings)
2. **Support 3 transport modes** for communicating with the Atlas3 switch:
   - **UART** via MCU (USB) - `PLX_API_MODE_SDB` with `SDB_UART_CABLE_USB`
   - **Serial SDB port** (USB) - `PLX_API_MODE_SDB` with `SDB_UART_CABLE_UART`
   - **PCIe bus** (if possible) - `PLX_API_MODE_PCI` via PLX kernel driver
3. **Expose only safe, non-proprietary data** - no Broadcom internal register maps, chip internals, or proprietary protocol details in the public API/UI
4. **Follow the serialcables-phoenix architecture** - same tech stack (FastAPI + NiceGUI + Click + Pydantic), same layer structure, same UI aesthetic
5. **Provide API, CLI, and Web UI** for switch configuration and endpoint monitoring

---

## Architecture Overview

```
┌─────────────────────────────────────────────────┐
│                  Web Dashboard                   │
│          (NiceGUI + ECharts, dark theme)         │
├─────────────────────────────────────────────────┤
│                   REST API                       │
│            (FastAPI + WebSockets)                │
├─────────────────────────────────────────────────┤
│                     CLI                          │
│                   (Click)                        │
├─────────────────────────────────────────────────┤
│              Core / Domain Layer                 │
│     (SwitchDevice, PortManager, PerfMonitor)     │
├─────────────────────────────────────────────────┤
│             Abstraction Layer                    │
│   (Safe API wrapping PLX SDK, hides internals)  │
├─────────────────────────────────────────────────┤
│           Python ctypes Bindings                 │
│    (Enhanced from SDK's PlxSdk.py foundation)    │
├─────────────────────────────────────────────────┤
│          Broadcom PLX SDK C Library              │
│         (PlxApi.so / PlxApi.dll)                 │
├─────────────────────────────────────────────────┤
│               Transport Layer                    │
│     ┌─────────┬──────────┬──────────┐           │
│     │  UART   │   SDB    │   PCIe   │           │
│     │(MCU/USB)│  (USB)   │  (Bus)   │           │
│     └─────────┴──────────┴──────────┘           │
├─────────────────────────────────────────────────┤
│           Atlas3 Host Card Hardware              │
└─────────────────────────────────────────────────┘
```

---

## IP Protection Strategy

The SDK is dual-licensed GPL/BSD and provides public API headers. Our approach:

- **EXPOSE**: Port properties (link speed, width, type), performance counters, device identity, EEPROM data, SPI flash status, NT port configuration, multi-host properties, DMA status
- **ABSTRACT**: Raw register offsets behind named operations (e.g., `get_link_speed()` instead of `read_register(0x68)`)
- **NEVER EXPOSE**: Internal register maps, chip-specific firmware details, proprietary command sequences, SDK source code
- **BOUNDARY**: The abstraction layer translates between SDK-internal concepts and user-facing domain concepts

---

## Project Structure

```
serialcables-calypso/
├── pyproject.toml
├── requirements.txt
├── README.md
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
└── src/calypso/
    ├── __init__.py
    ├── exceptions.py                # Exception hierarchy
    │
    ├── bindings/                    # Layer 1: Raw ctypes bindings
    │   ├── __init__.py
    │   ├── types.py                 # C struct definitions (PLX_DEVICE_KEY, etc.)
    │   ├── constants.py             # Enums & constants from SDK
    │   ├── library.py               # Shared lib loader (PlxApi.so/.dll)
    │   └── functions.py             # Function prototypes & wrappers
    │
    ├── sdk/                         # Layer 2: Safe SDK abstraction
    │   ├── __init__.py
    │   ├── device.py                # Device open/close/find lifecycle
    │   ├── registers.py             # Safe register access (named ops)
    │   ├── performance.py           # Perf counter management
    │   ├── eeprom.py                # EEPROM read/write
    │   ├── spi_flash.py             # SPI flash operations
    │   ├── dma.py                   # DMA channel management
    │   ├── interrupts.py            # Interrupt/notification handling
    │   ├── nt_port.py               # Non-Transparent port (LUT)
    │   └── multi_host.py            # Multi-host switch functions
    │
    ├── transport/                   # Layer 3: Transport abstraction
    │   ├── __init__.py
    │   ├── base.py                  # Abstract transport + configs
    │   ├── uart.py                  # UART via MCU (USB)
    │   ├── sdb.py                   # SDB serial port (USB)
    │   └── pcie.py                  # PCIe bus (kernel driver)
    │
    ├── core/                        # Layer 4: Domain logic
    │   ├── __init__.py
    │   ├── switch.py                # SwitchDevice (main interface)
    │   ├── port_manager.py          # Port enumeration & status
    │   ├── perf_monitor.py          # Real-time perf monitoring
    │   ├── topology.py              # Switch topology discovery
    │   └── discovery.py             # Device scanning
    │
    ├── models/                      # Pydantic models
    │   ├── __init__.py
    │   ├── device_info.py           # DeviceInfo, ChipInfo
    │   ├── port.py                  # PortStatus, PortProperties
    │   ├── performance.py           # PerfCounters, PerfStats
    │   ├── configuration.py         # SwitchConfig, PortConfig
    │   └── topology.py              # TopologyMap, SwitchNode
    │
    ├── api/                         # REST API
    │   ├── __init__.py
    │   ├── app.py                   # FastAPI app factory
    │   └── routes/
    │       ├── __init__.py
    │       ├── devices.py           # Device discovery/connect
    │       ├── ports.py             # Port status/config
    │       ├── performance.py       # Perf monitoring endpoints
    │       ├── configuration.py     # Switch configuration
    │       └── topology.py          # Topology queries
    │
    ├── cli/                         # CLI
    │   ├── __init__.py
    │   └── main.py                  # Click commands
    │
    ├── ui/                          # Web Dashboard
    │   ├── __init__.py
    │   ├── main.py                  # UI setup & page registration
    │   ├── layout.py                # Shared layout (header, sidebar)
    │   ├── theme.py                 # Dark theme (match phoenix)
    │   ├── state.py                 # UI session state
    │   ├── components/
    │   │   ├── __init__.py
    │   │   ├── port_grid.py         # Port status grid (up to 144)
    │   │   ├── perf_chart.py        # Real-time perf charts
    │   │   ├── topology_view.py     # Switch topology visualization
    │   │   ├── device_card.py       # Device info card
    │   │   ├── status_indicator.py  # Link/health badges
    │   │   └── sidebar.py           # Navigation
    │   └── pages/
    │       ├── __init__.py
    │       ├── discovery.py         # "/" - Scan & connect
    │       ├── dashboard.py         # "/switch/{id}" - Overview
    │       ├── ports.py             # "/switch/{id}/ports" - Port details
    │       ├── performance.py       # "/switch/{id}/perf" - Counters
    │       ├── configuration.py     # "/switch/{id}/config" - Settings
    │       └── topology.py          # "/switch/{id}/topology" - Map
    │
    └── utils/
        ├── __init__.py
        └── logging.py               # structlog setup
```

---

## Implementation Phases

### Phase 1: Foundation - ctypes Bindings & Library Loading

**Goal**: Clean Python bindings for the PLX SDK C library

**Tasks**:
1. Set up project scaffold (`pyproject.toml`, package structure, dependencies)
2. Build or locate the PLX SDK shared library (`PlxApi.so` for Linux, investigate Windows `.dll`)
3. Implement `bindings/types.py` - all C struct definitions matching SDK headers:
   - `PLX_DEVICE_KEY`, `PLX_DEVICE_OBJECT`, `PLX_PORT_PROP`
   - `PLX_PERF_PROP`, `PLX_PERF_STATS`, `PLX_PCI_BAR_PROP`
   - `PLX_DMA_PROP`, `PLX_DMA_PARAMS`, `PLX_PHYSICAL_MEM`
   - `PLX_INTERRUPT`, `PLX_NOTIFY_OBJECT`, `PLX_MULTI_HOST_PROP`
   - `PLX_MODE_PROP`, `PEX_SPI_OBJ`, `PEX_CHIP_FEAT`
   - `PLX_VERSION`, `PLX_DRIVER_PROP`
4. Implement `bindings/constants.py` - enums and constants:
   - `PLX_STATUS`, `PLX_API_MODE`, `PLX_CHIP_FAMILY`
   - `PLX_PORT_TYPE`, `PLX_PERF_CMD`, `PLX_DMA_COMMAND`
   - `SDB_UART_CABLE`, `SDB_BAUD_RATE`, `PLX_ACCESS_TYPE`
   - `PLX_EEPROM_STATUS`, `PLX_FLAG_*`, link speed/width enums
5. Implement `bindings/library.py` - platform-aware shared library loader
6. Implement `bindings/functions.py` - all ~60 function prototypes with proper argtypes/restype
7. Implement `exceptions.py` - map PLX_STATUS codes to Python exceptions

**Risk**: The SDK is Linux-targeted. Windows support may require cross-compilation or a Windows-specific PLX driver/DLL. Initial development should target Linux, with Windows as a follow-on.

---

### Phase 2: Safe SDK Abstraction Layer

**Goal**: Pythonic, IP-safe wrappers over raw bindings

**Tasks**:
1. `sdk/device.py` - Device lifecycle:
   - `find_devices(api_mode, mode_props)` -> list of device keys
   - `open_device(key)` -> device handle (context manager)
   - `get_chip_info(device)` -> chip type, revision, family
   - `get_port_properties(device)` -> port props (speed, width, type)
   - `reset_device(device)`

2. `sdk/registers.py` - Named register operations (abstract offsets):
   - `read_pci_register(device, offset)` / `write_pci_register()`
   - `read_plx_register(device, offset)` / `write_plx_register()`
   - `read_mailbox(device, index)` / `write_mailbox()`
   - Note: Offsets passed by caller; we don't hardcode proprietary register maps

3. `sdk/performance.py` - Performance monitoring:
   - `init_perf_properties(device)` -> perf objects array
   - `start_monitoring(device)` / `stop_monitoring(device)`
   - `reset_counters(device, perf_props)`
   - `get_counters(device, perf_props)` -> counter values
   - `calc_statistics(perf_prop, elapsed_ms)` -> bandwidth/utilization stats

4. `sdk/eeprom.py` - EEPROM operations:
   - `probe(device)` -> present/not
   - `read(device, offset)` / `write(device, offset, value)`
   - `read_16(device, offset)` / `write_16(device, offset, value)`
   - `get_crc(device)` / `update_crc(device)`

5. `sdk/spi_flash.py` - SPI flash:
   - `get_properties(device, chip_select)` -> flash info
   - `read(device, spi, offset, size)` -> bytes
   - `write(device, spi, offset, data)`
   - `erase(device, spi, offset)`
   - `get_status(device, spi)`

6. `sdk/dma.py` - DMA operations:
   - `open_channel(device, channel, props)` / `close_channel()`
   - `get_properties()` / `set_properties()`
   - `transfer_block(device, channel, params, timeout)`
   - `transfer_user_buffer(device, channel, params, timeout)`
   - `control(device, channel, command)` / `status()`

7. `sdk/interrupts.py` - Interrupt management:
   - `enable(device, interrupt)` / `disable()`
   - `register_notification(device, interrupt)` -> event
   - `wait_notification(device, event, timeout)` -> triggered interrupt
   - `cancel_notification(device, event)`

8. `sdk/nt_port.py` - Non-Transparent port:
   - `probe_req_id(device, is_read)` -> request ID
   - `get_lut_properties(device, index)` -> req_id, flags, enabled
   - `add_lut_entry(device, req_id, flags)` -> index
   - `disable_lut_entry(device, index)`

9. `sdk/multi_host.py` - Multi-host switch:
   - `get_properties(device)` -> multi-host config
   - `migrate_ports(device, vs_source, vs_dest, port_mask, reset_src)`

---

### Phase 3: Transport Layer

**Goal**: Unified transport interface for UART, SDB, and PCIe access modes

**Tasks**:
1. `transport/base.py` - Abstract base:
   - `TransportConfig` dataclass (common fields)
   - `Transport` ABC with `connect()`, `disconnect()`, `is_connected`, `scan_devices()`
   - `TransportMode` enum (UART_MCU, SDB_USB, PCIE_BUS)

2. `transport/uart.py` - UART via MCU:
   - Uses `PLX_API_MODE_SDB` with `SDB_UART_CABLE_USB`
   - Configurable baud rate (115200 default)
   - COM port / ttyUSB auto-detection via pyserial
   - MCU-specific handshake if needed

3. `transport/sdb.py` - SDB serial port:
   - Uses `PLX_API_MODE_SDB` with `SDB_UART_CABLE_UART`
   - Direct SDB connection (no MCU intermediary)
   - Configurable baud rate

4. `transport/pcie.py` - PCIe bus:
   - Uses `PLX_API_MODE_PCI`
   - Requires PLX kernel driver loaded (`Plx_load` script)
   - Standard device enumeration via PCI BDF addressing

---

### Phase 4: Core Domain Layer

**Goal**: High-level domain objects for switch management

**Tasks**:
1. `core/switch.py` - `SwitchDevice` class:
   - Wraps device lifecycle (open/close)
   - Exposes chip info, port properties
   - Manages transport connection
   - Context manager support

2. `core/port_manager.py` - `PortManager`:
   - Enumerate all ports on the switch (up to 144)
   - Get per-port status (link speed, width, type, payload)
   - Filter by port type (upstream, downstream, NT, fabric)

3. `core/perf_monitor.py` - `PerfMonitor`:
   - Background monitoring loop (configurable interval)
   - Per-port bandwidth and utilization calculation
   - History buffer for trend display
   - Start/stop/reset controls

4. `core/topology.py` - `TopologyMapper`:
   - Discover switch fabric topology
   - Map virtual switches, stations, ports
   - Multi-host configuration detection

5. `core/discovery.py` - `DeviceScanner`:
   - Scan all transport modes for Atlas3 devices
   - Filter by chip family (PLX_FAMILY_ATLAS_3)
   - Return discovered device list with transport info

---

### Phase 5: Pydantic Models

**Goal**: Type-safe data models for API boundaries

**Tasks**:
1. `models/device_info.py`:
   - `DeviceInfo` (chip_id, revision, family, bus/slot/func)
   - `TransportInfo` (mode, port_name, baud_rate)
   - `DriverInfo` (version, name, is_service)
   - `VersionInfo` (api, firmware, hardware, software)

2. `models/port.py`:
   - `PortProperties` (type, number, link_width, max_width, link_speed, max_speed, payload)
   - `PortStatus` (is_up, link_speed_gbps, width, error_count)
   - `PortType` enum (UPSTREAM, DOWNSTREAM, NT_LINK, NT_VIRTUAL, FABRIC)

3. `models/performance.py`:
   - `PerfCounters` (ingress/egress posted/nonposted/completion header+data)
   - `PerfStats` (bandwidth_mbps, utilization_pct, link_rate_gbps)

4. `models/configuration.py`:
   - `SwitchConfig` (multi_host_enabled, virtual_switch_count)
   - `PortConfig` (port_number, enabled, nt_mode)

5. `models/topology.py`:
   - `TopologyNode` (device_id, port_list, connected_nodes)
   - `TopologyMap` (nodes, links, virtual_switches)

---

### Phase 6: REST API

**Goal**: FastAPI endpoints matching phoenix patterns

**Tasks**:
1. `api/app.py` - App factory, device registry, middleware
2. `api/routes/devices.py`:
   - `POST /api/devices/scan` - Scan for Atlas3 devices
   - `GET /api/devices` - List connected devices
   - `GET /api/devices/{id}` - Device details
   - `POST /api/devices/{id}/connect` - Connect via transport
   - `POST /api/devices/{id}/disconnect`
   - `POST /api/devices/{id}/reset`

3. `api/routes/ports.py`:
   - `GET /api/devices/{id}/ports` - All port statuses
   - `GET /api/devices/{id}/ports/{port}` - Single port detail

4. `api/routes/performance.py`:
   - `POST /api/devices/{id}/perf/start` - Start monitoring
   - `POST /api/devices/{id}/perf/stop`
   - `GET /api/devices/{id}/perf/counters` - Current values
   - `GET /api/devices/{id}/perf/stats` - Calculated statistics
   - `WebSocket /api/devices/{id}/perf/stream` - Real-time stream

5. `api/routes/configuration.py`:
   - `GET /api/devices/{id}/config` - Current switch config
   - `PUT /api/devices/{id}/config` - Update config

6. `api/routes/topology.py`:
   - `GET /api/devices/{id}/topology` - Switch topology map

---

### Phase 7: CLI

**Goal**: Click-based command-line interface

**Tasks**:
1. `cli/main.py` - Command group:
   ```
   calypso scan [--transport uart|sdb|pcie] [--port COM3]
   calypso info <device-id>
   calypso ports <device-id> [--port-num N]
   calypso perf <device-id> [--interval 1000] [--duration 60]
   calypso config <device-id>
   calypso config set <device-id> --key value
   calypso topology <device-id>
   calypso eeprom read <device-id> <offset>
   calypso eeprom write <device-id> <offset> <value>
   calypso flash read <device-id> <offset> <size>
   calypso serve [--host 0.0.0.0] [--port 8000] [--no-ui]
   ```

---

### Phase 8: Web Dashboard

**Goal**: NiceGUI-based browser UI matching phoenix aesthetic

**Tasks**:
1. `ui/main.py` - Page registration, NiceGUI setup
2. `ui/layout.py` - Dark theme header + sidebar layout
3. `ui/theme.py` - Color palette (match phoenix dark theme)
4. `ui/state.py` - Per-session state tracking

5. Pages:
   - `ui/pages/discovery.py` - "/" - Transport selection, device scanning, connect
   - `ui/pages/dashboard.py` - "/switch/{id}" - Overview with chip info, active ports summary, health
   - `ui/pages/ports.py` - "/switch/{id}/ports" - Port grid showing all ports, link status, speed/width
   - `ui/pages/performance.py` - "/switch/{id}/perf" - Real-time bandwidth/utilization charts per port
   - `ui/pages/configuration.py` - "/switch/{id}/config" - Multi-host, virtual switch, NT settings
   - `ui/pages/topology.py` - "/switch/{id}/topology" - Visual switch fabric map

6. Components:
   - `ui/components/port_grid.py` - Grid of port status tiles (up to 144 ports)
   - `ui/components/perf_chart.py` - ECharts real-time line/bar charts
   - `ui/components/topology_view.py` - Switch topology graph (ECharts or D3)
   - `ui/components/device_card.py` - Device info summary card
   - `ui/components/status_indicator.py` - Link up/down badges, speed indicators

---

## Dependencies

```
# Core
fastapi>=0.100
uvicorn[standard]>=0.23
pydantic>=2.0
click>=8.1
structlog>=23.1
nicegui>=2.0

# Hardware
pyserial>=3.5          # COM port detection for UART/SDB

# Development
pytest>=7.4
pytest-asyncio>=0.21
pytest-cov>=4.1
httpx>=0.24            # API testing
```

---

## Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| SDK is Linux-targeted; host may be Windows | HIGH | Build PlxApi as .dll on Windows OR develop on Linux VM. The SDK Makefiles support Windows builds via WDM driver model. Investigate cross-compilation. |
| PLX kernel driver required for PCIe bus mode | MEDIUM | UART and SDB modes work without kernel driver. PCIe mode is "if possible" - prioritize serial transports first. |
| SDK shared library may not exist pre-built | MEDIUM | May need to compile PlxApi from source. The SDK provides full source + Makefiles. |
| Atlas3 chip-specific behavior not fully documented | MEDIUM | Use SDK sample code (PlxCm, ApiTest) as reference. Test with actual hardware. |
| IP protection - avoiding Broadcom proprietary exposure | HIGH | Abstraction layer only exposes SDK public API results (port properties, perf counters, etc.). No register maps or firmware internals in our code. All offsets come from user or SDK calls, never hardcoded. |
| Existing SDK Python bindings are basic (no SDB support) | LOW | SDK bindings cover core structs. We extend with SDB/transport mode support using the C header definitions. |
| Performance monitoring with 144 ports | LOW | SDK handles port iteration internally. Use efficient polling interval (1-2 sec default). |

---

## Phase Execution Order

1. **Phase 1** (Foundation) - Must be first; everything depends on ctypes bindings
2. **Phase 2** (SDK Abstraction) - Depends on Phase 1
3. **Phase 3** (Transport) - Depends on Phase 2; enables hardware testing
4. **Phase 5** (Models) - Can be done in parallel with Phase 2-3
5. **Phase 4** (Core) - Depends on Phases 2, 3, 5
6. **Phase 7** (CLI) - Depends on Phase 4; useful for testing
7. **Phase 6** (API) - Depends on Phase 4
8. **Phase 8** (UI) - Depends on Phases 4, 6

Phases 5 (Models) and 1-2 can have some parallel work. Phases 6-8 (API, CLI, UI) can be developed somewhat in parallel once Core is stable.

---

## Complexity Assessment

- **Overall**: HIGH
- **Bindings Layer**: MEDIUM (mechanical ctypes work, but many structs/functions)
- **SDK Abstraction**: MEDIUM (wrapping known C API patterns)
- **Transport Layer**: HIGH (hardware-dependent, debugging without device is hard)
- **Core Domain**: MEDIUM (standard patterns from phoenix)
- **API/CLI**: LOW-MEDIUM (following established phoenix patterns)
- **Web UI**: MEDIUM (ECharts + NiceGUI for complex visualizations)

---

**WAITING FOR CONFIRMATION**: Proceed with this plan? (yes / no / modify)
