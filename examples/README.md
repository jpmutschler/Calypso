# Calypso Example Scripts

Standalone automation scripts for PCIe Gen6 Atlas3 switch validation. Each script
is self-contained with argparse CLI and can be used as-is or as a reference for
building custom automation.

## Prerequisites

```bash
pip install -e ".[dev]"
```

## Quick Start

```bash
# 1. Discover hardware
python examples/discover_and_inventory.py

# 2. Check port status on device 0
python examples/port_status_snapshot.py 0

# 3. Run a recipe
python examples/recipe_runner.py --list
python examples/recipe_runner.py port_sweep 0
```

## Scripts by Category

### Discovery

| Script | Description |
|--------|-------------|
| `discover_and_inventory.py` | Scan for Atlas3 switches, print device table, export JSON |
| `topology_dump.py` | Build fabric topology tree with connector mapping |

### Link Health

| Script | Description |
|--------|-------------|
| `port_status_snapshot.py` | Port status table (speed/width/MPS), CSV export |
| `gen6_flit_health_check.py` | Gen6 Flit mode readiness, EQ status, error log check |

### Performance & Monitoring

| Script | Description |
|--------|-------------|
| `bandwidth_monitor.py` | Live per-port bandwidth table with CSV time-series |
| `aer_error_poll.py` | AER error polling with delta mode and human-readable fields |
| `overnight_soak.py` | Long-running soak: AER + bandwidth + link state, rotating CSV |

### Stress Testing

| Script | Description |
|--------|-------------|
| `link_retrain_stress.py` | Repeated link retrain with speed/width validation |
| `speed_downshift_sweep.py` | Test every speed tier Gen6→Gen1 with AER + bandwidth |
| `flit_error_injection_test.py` | Gen6 Flit error injection with counter/log validation |

### Signal Integrity

| Script | Description |
|--------|-------------|
| `pam4_eye_sweep.py` | PAM4 3-eye lane margining with ASCII eye diagram |

### Debug

| Script | Description |
|--------|-------------|
| `ptrace_capture.py` | Protocol trace capture with trigger modes, JSON export |

### Configuration & Recipes

| Script | Description |
|--------|-------------|
| `eeprom_backup_restore.py` | EEPROM backup/restore with CRC validation |
| `recipe_runner.py` | Run any Calypso recipe from CLI, reference implementation |

## Common Patterns

All scripts follow the same structure:

```python
from calypso.transport.pcie import PcieTransport
from calypso.core.switch import SwitchDevice

transport = PcieTransport()
device = SwitchDevice(transport)
device.open(device_index=0)
try:
    # Use device...
    pass
finally:
    device.close()
```

## Gen6/Flit-Specific Scripts

Three scripts target PCIe 6.0.1 Gen6 64 GT/s Flit mode:

- **`gen6_flit_health_check.py`** — Validate Flit mode readiness and check error logs
- **`pam4_eye_sweep.py`** — PAM4 3-eye lane margining measurement
- **`flit_error_injection_test.py`** — Controlled error injection with recovery validation
