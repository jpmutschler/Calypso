#!/usr/bin/env python3
"""PTrace Hardware Validation Script.

Automated test suite that exercises PTrace (Protocol Trace) functionality
against live Atlas3 hardware and captures all data needed to validate
register offsets, data formats, trigger logic, and timing.

Prerequisites:
    - Calypso server running: calypso serve --host 0.0.0.0 --port 8000
    - At least one Atlas3 device connected (auto-detected)
    - At least one downstream port with link up (auto-detected)

Usage:
    python scripts/ptrace_hw_validation.py [--base-url http://localhost:8000]
                                           [--device-id dev_xx_xx]
                                           [--port PORT_NUMBER]
                                           [--output-dir ./ptrace_validation]
                                           [--phases 1,2,3,4,5,6,7]

Output:
    Creates a timestamped directory under --output-dir containing:
    - results.json     : Machine-readable full test results
    - summary.txt      : Human-readable test summary
    - raw/             : Per-test raw API responses
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package required. Install with: pip install requests")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class TestResult:
    """Result of a single validation test."""

    test_id: str
    phase: int
    name: str
    status: str = "SKIP"  # PASS, FAIL, WARN, ERROR, SKIP
    expected: str = ""
    actual: str = ""
    data: dict = field(default_factory=dict)
    notes: str = ""
    duration_ms: float = 0.0


class PTraceValidator:
    """Drives PTrace hardware validation tests via the REST API."""

    def __init__(
        self,
        base_url: str,
        device_id: str | None,
        port_number: int | None,
        output_dir: Path,
        phases: set[int],
    ):
        self.base_url = base_url.rstrip("/")
        self.api = f"{self.base_url}/api"
        self.device_id = device_id
        self.port_number = port_number
        self.output_dir = output_dir
        self.phases = phases
        self.results: list[TestResult] = []
        self.raw_dir = output_dir / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)

        # Discovered state
        self.device_info: dict = {}
        self.ports_up: list[dict] = []
        self.multi_station_ports: list[int] = []  # ports from different stations
        self.ltssm_state: int = 0
        self.link_speed_code: int = 0

    # -- HTTP helpers --

    def _get(self, path: str, params: dict | None = None) -> dict | list:
        url = f"{self.api}{path}"
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict | None = None) -> dict:
        url = f"{self.api}{path}"
        resp = requests.post(url, json=body or {}, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _save_raw(self, test_id: str, data: Any) -> None:
        path = self.raw_dir / f"{test_id}.json"
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def _run_test(self, test_id: str, phase: int, name: str, fn) -> TestResult:
        """Execute a test function and capture its result."""
        result = TestResult(test_id=test_id, phase=phase, name=name)
        t0 = time.monotonic()
        try:
            fn(result)
        except requests.HTTPError as exc:
            result.status = "ERROR"
            result.notes = f"HTTP {exc.response.status_code}: {exc.response.text[:500]}"
        except Exception as exc:
            result.status = "ERROR"
            result.notes = f"{type(exc).__name__}: {exc}"
        result.duration_ms = round((time.monotonic() - t0) * 1000, 1)
        self.results.append(result)
        self._save_raw(test_id, result.data)
        status_char = {"PASS": "+", "FAIL": "!", "WARN": "~", "ERROR": "X", "SKIP": "-"}
        print(f"  [{status_char.get(result.status, '?')}] {test_id}: {name} ({result.status})")
        if result.notes:
            for line in result.notes.split("\n")[:3]:
                print(f"      {line}")
        return result

    # -- Helper: standard ptrace operations --

    def _ptrace_post(self, endpoint: str, body: dict) -> dict:
        return self._post(f"/devices/{self.device_id}/ptrace/{endpoint}", body)

    def _ptrace_get(self, endpoint: str, params: dict | None = None) -> dict:
        return self._get(f"/devices/{self.device_id}/ptrace/{endpoint}", params)

    def _status(self, port: int, direction: str = "ingress") -> dict:
        return self._ptrace_get("status", {"port_number": port, "direction": direction})

    def _buffer(self, port: int, direction: str = "ingress", max_rows: int = 32) -> dict:
        return self._ptrace_get(
            "buffer", {"port_number": port, "direction": direction, "max_rows": max_rows}
        )

    def _start(self, port: int, direction: str = "ingress") -> dict:
        return self._ptrace_post("start", {"port_number": port, "direction": direction})

    def _stop(self, port: int, direction: str = "ingress") -> dict:
        return self._ptrace_post("stop", {"port_number": port, "direction": direction})

    def _clear(self, port: int, direction: str = "ingress") -> dict:
        return self._ptrace_post("clear", {"port_number": port, "direction": direction})

    def _manual_trigger(self, port: int, direction: str = "ingress") -> dict:
        return self._ptrace_post("manual-trigger", {"port_number": port, "direction": direction})

    def _configure(self, port: int, direction: str = "ingress", **kwargs) -> dict:
        body = {
            "port_number": port,
            "direction": direction,
            "capture": {"port_number": port, "direction": direction},
            "trigger": {"trigger_src": 0},
            "post_trigger": {"cap_count": 100, "count_type": 0},
        }
        body.update(kwargs)
        return self._ptrace_post("configure", body)

    # -----------------------------------------------------------------------
    # Phase 0: Discovery & Setup
    # -----------------------------------------------------------------------

    def discover(self) -> bool:
        """Auto-detect device and port if not specified. Returns True if ready."""
        print("\n=== Phase 0: Discovery ===")

        # Check server is reachable
        try:
            requests.get(f"{self.base_url}/api/devices", timeout=5)
        except Exception:
            print(f"  ERROR: Cannot reach Calypso server at {self.base_url}")
            print("  Start with: calypso serve --host 0.0.0.0 --port 8000")
            return False

        # Auto-detect device
        if not self.device_id:
            devices = self._get("/devices")
            if not devices:
                print("  ERROR: No connected devices. Connect first via UI or API.")
                return False
            self.device_id = devices[0]
            print(f"  Auto-selected device: {self.device_id}")
        else:
            print(f"  Using specified device: {self.device_id}")

        # Get device info
        try:
            self.device_info = self._get(f"/devices/{self.device_id}")
            chip_id = self.device_info.get("chip_id", 0)
            print(f"  Chip ID: 0x{chip_id:04X}")
            print(f"  Chip Type: 0x{self.device_info.get('chip_type', 0):04X}")
            is_b0 = chip_id >= 0xA000
            print(f"  Silicon variant: {'B0' if is_b0 else 'A0'}")
        except Exception as exc:
            print(f"  WARNING: Could not get device info: {exc}")

        # Find ports with link up
        try:
            all_ports = self._get(f"/devices/{self.device_id}/ports")
            self.ports_up = [p for p in all_ports if p.get("is_link_up")]
            print(f"  Ports with link up: {len(self.ports_up)} / {len(all_ports)}")
            for p in self.ports_up[:5]:
                speed = p.get("link_speed", "?")
                width = p.get("link_width", "?")
                print(f"    Port {p['port_number']:3d}: {speed} x{width}")
            if len(self.ports_up) > 5:
                print(f"    ... and {len(self.ports_up) - 5} more")
        except Exception as exc:
            print(f"  WARNING: Could not enumerate ports: {exc}")

        # Select test port
        if self.port_number is not None:
            print(f"  Using specified port: {self.port_number}")
        elif self.ports_up:
            self.port_number = self.ports_up[0]["port_number"]
            print(f"  Auto-selected port: {self.port_number} (first link-up port)")
        else:
            # Fall back to port 0 even if no link (idle traffic test still useful)
            self.port_number = 0
            print("  WARNING: No link-up ports found. Using port 0 (may have limited data)")

        # Find ports from different stations for multi-station test
        seen_stations: set[int] = set()
        for p in self.ports_up:
            station = p["port_number"] // 16
            if station not in seen_stations:
                seen_stations.add(station)
                self.multi_station_ports.append(p["port_number"])
        print(f"  Stations with link-up ports: {sorted(seen_stations)}")

        # Get LTSSM state for condition testing
        try:
            snap = self._get(
                f"/devices/{self.device_id}/ltssm/snapshot",
                {"port_number": self.port_number},
            )
            self.ltssm_state = snap.get("ltssm_state", 0)
            self.link_speed_code = snap.get("link_speed", 0)
            print(f"  Port {self.port_number} LTSSM: {snap.get('ltssm_state_name', '?')} "
                  f"(0x{self.ltssm_state:03X})")
            print(f"  Port {self.port_number} Speed: {snap.get('link_speed_name', '?')} "
                  f"(code={self.link_speed_code})")
        except Exception as exc:
            print(f"  WARNING: Could not read LTSSM snapshot: {exc}")

        # Save discovery data
        discovery = {
            "device_id": self.device_id,
            "device_info": self.device_info,
            "ports_up": [p["port_number"] for p in self.ports_up],
            "test_port": self.port_number,
            "multi_station_ports": self.multi_station_ports,
            "ltssm_state": self.ltssm_state,
            "link_speed_code": self.link_speed_code,
        }
        self._save_raw("phase0_discovery", discovery)
        return True

    # -----------------------------------------------------------------------
    # Phase 1: Register Offset Smoke Test
    # -----------------------------------------------------------------------

    def phase1_smoke_test(self):
        print("\n=== Phase 1: Register Offset Smoke Test ===")
        port = self.port_number

        # 1.1 — Idle status read
        def test_1_1(r: TestResult):
            s = self._status(port, "ingress")
            r.data = {"status": s}
            r.expected = "capture_in_progress=false, ram_init_done=true"
            cap_active = s.get("capture_in_progress", True)
            ram_init = s.get("ram_init_done", False)
            r.actual = (f"capture_in_progress={cap_active}, ram_init_done={ram_init}, "
                        f"triggered={s.get('triggered')}, "
                        f"global_timer={s.get('global_timer', 0)}")
            if not cap_active and ram_init:
                r.status = "PASS"
            else:
                r.status = "WARN"
                r.notes = "Unexpected idle state — may need power cycle or PTrace disable first"

        self._run_test("1.1_idle_status", 1, "Read status at idle", test_1_1)

        # 1.2 — Start/Stop/Read cycle
        def test_1_2(r: TestResult):
            self._stop(port)
            self._clear(port)
            self._configure(port)
            self._start(port)
            time.sleep(1.5)
            self._stop(port)
            s = self._status(port)
            buf = self._buffer(port, max_rows=16)
            r.data = {"status": s, "buffer_sample": buf}
            rows_read = buf.get("total_rows_read", 0)
            r.expected = "buffer_count > 0, rows contain non-zero data"
            r.actual = f"rows_read={rows_read}"

            if rows_read == 0:
                r.status = "FAIL"
                r.notes = "No data captured — register offsets may be wrong"
                return

            # Check first few rows for non-zero data
            nonzero_rows = 0
            for row in buf.get("rows", [])[:16]:
                hex_str = row.get("hex_str", "")
                if hex_str and hex_str != "0" * len(hex_str):
                    nonzero_rows += 1

            r.actual += f", nonzero_rows={nonzero_rows}/16"
            r.data["first_5_rows"] = [row.get("hex_str", "")[:80] for row in buf.get("rows", [])[:5]]

            ts_start = s.get("start_ts", 0)
            ts_last = s.get("last_ts", 0)
            ts_global = s.get("global_timer", 0)
            r.data["timestamps"] = {
                "start_ts": ts_start,
                "last_ts": ts_last,
                "global_timer": ts_global,
                "trigger_ts": s.get("trigger_ts", 0),
            }
            r.actual += f", start_ts={ts_start}, last_ts={ts_last}, global_timer={ts_global}"

            if nonzero_rows > 0:
                r.status = "PASS"
            else:
                r.status = "WARN"
                r.notes = "All rows zero — port may be idle (no endpoint connected?)"

        self._run_test("1.2_start_stop_read", 1, "Start/Stop/Read cycle", test_1_2)

        # 1.3 — Manual trigger
        def test_1_3(r: TestResult):
            self._stop(port)
            self._clear(port)
            # Configure with manual trigger source (0)
            self._configure(port, trigger={"trigger_src": 0})
            self._start(port)
            time.sleep(0.5)
            self._manual_trigger(port)
            time.sleep(1.0)
            s = self._status(port)
            r.data = {"status": s}
            triggered = s.get("triggered", False)
            trigger_ts = s.get("trigger_ts", 0)
            trigger_row = s.get("trigger_row_addr", 0)
            r.expected = "triggered=true, trigger_ts > 0"
            r.actual = (f"triggered={triggered}, trigger_ts={trigger_ts}, "
                        f"trigger_row={trigger_row}")

            if triggered and trigger_ts > 0:
                r.status = "PASS"
            elif triggered:
                r.status = "WARN"
                r.notes = "Triggered but trigger_ts=0 — timestamp offset may be wrong"
            else:
                r.status = "FAIL"
                r.notes = "Manual trigger did not fire — MANUAL_TRIGGER register offset wrong?"
            self._stop(port)

        self._run_test("1.3_manual_trigger", 1, "Manual trigger test", test_1_3)

        # 1.4 — Egress direction
        def test_1_4(r: TestResult):
            self._stop(port, "egress")
            self._clear(port, "egress")
            self._configure(port, direction="egress")
            self._start(port, "egress")
            time.sleep(1.0)
            self._stop(port, "egress")
            s = self._status(port, "egress")
            buf = self._buffer(port, direction="egress", max_rows=8)
            r.data = {"status": s, "buffer_rows": buf.get("total_rows_read", 0)}
            rows = buf.get("total_rows_read", 0)
            r.expected = "Egress direction works independently"
            r.actual = f"rows_read={rows}, global_timer={s.get('global_timer', 0)}"
            if rows > 0:
                r.status = "PASS"
            else:
                r.status = "WARN"
                r.notes = "No egress data — may be normal if no downstream traffic"

        self._run_test("1.4_egress_direction", 1, "Egress direction test", test_1_4)

        # 1.5 — Multi-station test
        def test_1_5(r: TestResult):
            if len(self.multi_station_ports) < 2:
                r.status = "SKIP"
                r.notes = "Need link-up ports on 2+ stations to test"
                return

            station_results = {}
            for p in self.multi_station_ports[:3]:
                station = p // 16
                try:
                    self._stop(p)
                    self._clear(p)
                    self._configure(p)
                    self._start(p)
                    time.sleep(0.5)
                    self._stop(p)
                    s = self._status(p)
                    station_results[f"station_{station}_port_{p}"] = {
                        "global_timer": s.get("global_timer", 0),
                        "start_ts": s.get("start_ts", 0),
                    }
                except Exception as exc:
                    station_results[f"station_{station}_port_{p}"] = {"error": str(exc)}

            r.data = {"station_results": station_results}
            errors = [k for k, v in station_results.items() if "error" in v]
            r.expected = "All stations return valid data"
            r.actual = f"Tested {len(station_results)} ports across stations"
            if errors:
                r.status = "FAIL"
                r.notes = f"Failed on: {', '.join(errors)}"
            else:
                r.status = "PASS"

        self._run_test("1.5_multi_station", 1, "Multi-station address test", test_1_5)

    # -----------------------------------------------------------------------
    # Phase 2: Trigger Source Validation
    # -----------------------------------------------------------------------

    def phase2_trigger_sources(self):
        print("\n=== Phase 2: Trigger Source Validation ===")
        port = self.port_number

        # 2.1 — Cond0 trigger on current LTSSM state (should trigger immediately)
        def test_2_1(r: TestResult):
            ltssm = self.ltssm_state
            if ltssm == 0:
                r.status = "SKIP"
                r.notes = "LTSSM state unknown — cannot configure condition"
                return

            self._stop(port)
            self._clear(port)

            # Configure condition 0: match current LTSSM state
            self._ptrace_post("condition-attributes", {
                "port_number": port,
                "direction": "ingress",
                "config": {
                    "condition_id": 0,
                    "ltssm_state": ltssm,
                    "ltssm_state_mask": 0x1FF,
                },
            })

            # Trigger on COND0 (source=1)
            self._configure(
                port,
                trigger={"trigger_src": 1, "cond0_enable": 0xFFFFFFFF},
            )
            self._start(port)
            time.sleep(2.0)
            s = self._status(port)
            r.data = {
                "status": s,
                "ltssm_state_used": f"0x{ltssm:03X}",
            }
            triggered = s.get("triggered", False)
            r.expected = "triggered=true (condition matches current LTSSM state)"
            r.actual = f"triggered={triggered}, trigger_ts={s.get('trigger_ts', 0)}"
            if triggered:
                r.status = "PASS"
            else:
                r.status = "FAIL"
                r.notes = ("Cond0 did not trigger on current LTSSM state — "
                           "condition attribute registers or cond enable may be wrong")
            self._stop(port)

        self._run_test("2.1_cond0_ltssm_match", 2, "Cond0 LTSSM match trigger", test_2_1)

        # 2.2 — Cond0 with impossible LTSSM state (should NOT trigger)
        def test_2_2(r: TestResult):
            self._stop(port)
            self._clear(port)

            # LTSSM state 0x1FF with full mask — should never match
            self._ptrace_post("condition-attributes", {
                "port_number": port,
                "direction": "ingress",
                "config": {
                    "condition_id": 0,
                    "ltssm_state": 0x1FF,
                    "ltssm_state_mask": 0x1FF,
                },
            })

            self._configure(
                port,
                trigger={"trigger_src": 1, "cond0_enable": 0xFFFFFFFF},
            )
            self._start(port)
            time.sleep(3.0)
            s = self._status(port)
            r.data = {"status": s}
            triggered = s.get("triggered", False)
            cap_active = s.get("capture_in_progress", False)
            r.expected = "triggered=false, capture_in_progress=true"
            r.actual = f"triggered={triggered}, capture_in_progress={cap_active}"
            if not triggered and cap_active:
                r.status = "PASS"
            elif triggered:
                r.status = "FAIL"
                r.notes = "Triggered on impossible state — condition matching may not work"
            else:
                r.status = "WARN"
                r.notes = "Capture stopped but not triggered — unexpected state"
            self._stop(port)

        self._run_test("2.2_cond0_no_match", 2, "Cond0 impossible state (no trigger)", test_2_2)

        # 2.3 — Cond1 trigger
        def test_2_3(r: TestResult):
            ltssm = self.ltssm_state
            if ltssm == 0:
                r.status = "SKIP"
                r.notes = "LTSSM state unknown"
                return

            self._stop(port)
            self._clear(port)

            # Configure condition 1
            self._ptrace_post("condition-attributes", {
                "port_number": port,
                "direction": "ingress",
                "config": {
                    "condition_id": 1,
                    "ltssm_state": ltssm,
                    "ltssm_state_mask": 0x1FF,
                },
            })

            # Trigger on COND1 (source=2)
            self._configure(
                port,
                trigger={"trigger_src": 2, "cond1_enable": 0xFFFFFFFF},
            )
            self._start(port)
            time.sleep(2.0)
            s = self._status(port)
            r.data = {"status": s}
            triggered = s.get("triggered", False)
            r.expected = "triggered=true"
            r.actual = f"triggered={triggered}"
            r.status = "PASS" if triggered else "FAIL"
            if not triggered:
                r.notes = "Cond1 registers may be at wrong offset"
            self._stop(port)

        self._run_test("2.3_cond1_trigger", 2, "Cond1 trigger test", test_2_3)

        # 2.4 — COND0 OR COND1 (source=4)
        def test_2_4(r: TestResult):
            ltssm = self.ltssm_state
            if ltssm == 0:
                r.status = "SKIP"
                r.notes = "LTSSM state unknown"
                return

            self._stop(port)
            self._clear(port)

            # Cond0 matches (current LTSSM), Cond1 doesn't (0x1FF)
            self._ptrace_post("condition-attributes", {
                "port_number": port, "direction": "ingress",
                "config": {"condition_id": 0, "ltssm_state": ltssm, "ltssm_state_mask": 0x1FF},
            })
            self._ptrace_post("condition-attributes", {
                "port_number": port, "direction": "ingress",
                "config": {"condition_id": 1, "ltssm_state": 0x1FF, "ltssm_state_mask": 0x1FF},
            })

            self._configure(
                port,
                trigger={
                    "trigger_src": 4,  # COND0 OR COND1
                    "cond0_enable": 0xFFFFFFFF,
                    "cond1_enable": 0xFFFFFFFF,
                },
            )
            self._start(port)
            time.sleep(2.0)
            s = self._status(port)
            r.data = {"status": s}
            triggered = s.get("triggered", False)
            r.expected = "triggered=true (Cond0 matches via OR)"
            r.actual = f"triggered={triggered}"
            r.status = "PASS" if triggered else "FAIL"
            self._stop(port)

        self._run_test("2.4_cond0_or_cond1", 2, "COND0 OR COND1 trigger", test_2_4)

        # 2.5 — COND0 AND COND1 (source=3) — only one matches, should NOT trigger
        def test_2_5(r: TestResult):
            ltssm = self.ltssm_state
            if ltssm == 0:
                r.status = "SKIP"
                r.notes = "LTSSM state unknown"
                return

            self._stop(port)
            self._clear(port)

            # Cond0 matches, Cond1 doesn't
            self._ptrace_post("condition-attributes", {
                "port_number": port, "direction": "ingress",
                "config": {"condition_id": 0, "ltssm_state": ltssm, "ltssm_state_mask": 0x1FF},
            })
            self._ptrace_post("condition-attributes", {
                "port_number": port, "direction": "ingress",
                "config": {"condition_id": 1, "ltssm_state": 0x1FF, "ltssm_state_mask": 0x1FF},
            })

            self._configure(
                port,
                trigger={
                    "trigger_src": 3,  # COND0 AND COND1
                    "cond0_enable": 0xFFFFFFFF,
                    "cond1_enable": 0xFFFFFFFF,
                },
            )
            self._start(port)
            time.sleep(3.0)
            s = self._status(port)
            r.data = {"status": s}
            triggered = s.get("triggered", False)
            r.expected = "triggered=false (only Cond0 matches, AND requires both)"
            r.actual = f"triggered={triggered}"
            if not triggered:
                r.status = "PASS"
            else:
                r.status = "FAIL"
                r.notes = "AND trigger fired with only one condition — logic may be wrong"
            self._stop(port)

        self._run_test("2.5_cond0_and_cond1_partial", 2,
                        "COND0 AND COND1 (partial match, should not trigger)", test_2_5)

        # 2.6 — Enumerate all trigger source IDs
        def test_2_6(r: TestResult):
            # Quick probe of trigger source IDs — just configure + check for errors
            source_results = {}
            sources_to_test = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 0x3D]
            source_names = {
                0: "MANUAL", 1: "COND0", 2: "COND1", 3: "COND0_AND_COND1",
                4: "COND0_OR_COND1", 5: "COND0_XOR_COND1", 6: "COND0_THEN_COND1",
                7: "EVENT_COUNTER", 8: "TRIGGERIN_OR", 9: "COND0_THEN_DELAY",
                0x3D: "PORT_ERROR",
            }
            for src in sources_to_test:
                try:
                    self._stop(port)
                    self._clear(port)
                    self._configure(port, trigger={"trigger_src": src})
                    source_results[src] = {
                        "name": source_names.get(src, f"UNKNOWN_{src}"),
                        "accepted": True,
                    }
                except requests.HTTPError as exc:
                    source_results[src] = {
                        "name": source_names.get(src, f"UNKNOWN_{src}"),
                        "accepted": False,
                        "error": str(exc),
                    }
            r.data = {"source_results": source_results}
            accepted = sum(1 for v in source_results.values() if v["accepted"])
            r.expected = "All trigger source IDs accepted by hardware"
            r.actual = f"{accepted}/{len(sources_to_test)} accepted"
            r.status = "PASS" if accepted == len(sources_to_test) else "WARN"
            self._stop(port)

        self._run_test("2.6_trigger_source_enum", 2, "Enumerate trigger source IDs", test_2_6)

    # -----------------------------------------------------------------------
    # Phase 3: Flit Mode / Filter Control
    # -----------------------------------------------------------------------

    def phase3_flit_and_filters(self):
        print("\n=== Phase 3: Flit Mode / Filter Control ===")
        port = self.port_number

        # 3.1 — Filter Control write/readback
        def test_3_1(r: TestResult):
            self._stop(port)
            self._clear(port)

            cfg = {
                "dllp_type_enb": True,
                "os_type_enb": False,
                "cxl_io_filter_enb": True,
                "cxl_cache_filter_enb": False,
                "cxl_mem_filter_enb": False,
                "filter_256b_enb": True,
                "filter_src_sel": 2,  # FILTER0_OR_1
                "filter_match_sel0": 1,  # MATCH_DW1
                "filter_match_sel1": 3,  # MATCH_DW1_8
                "dllp_type_inv": True,
                "os_type_inv": False,
            }

            try:
                resp = self._ptrace_post("filter-control", {
                    "port_number": port, "direction": "ingress", "config": cfg,
                })
                r.data["write_response"] = resp
            except requests.HTTPError as exc:
                if exc.response.status_code == 501:
                    r.status = "SKIP"
                    r.notes = "Filter Control not available (B0 silicon)"
                    return
                raise

            # Readback is part of status — we can't directly read FilterControl
            # through the status API, so just verify the write didn't error
            r.data["config_written"] = cfg
            r.expected = "Write succeeds without error"
            r.actual = f"Write returned: {resp}"
            r.status = "PASS"
            r.notes = ("Write succeeded — readback verification requires raw register "
                       "access to offsets 0x030/0x034")

        self._run_test("3.1_filter_control_write", 3, "Filter Control write", test_3_1)

        # 3.2 — 512-bit filter write with known pattern
        def test_3_2(r: TestResult):
            self._stop(port)
            self._clear(port)

            # Write a recognizable pattern: match = repeating AABBCCDD, mask = all FF
            match_pattern = "AABBCCDD" * 16  # 128 hex chars = 512 bits
            mask_pattern = "FFFFFFFF" * 16

            resp0 = self._ptrace_post("filter", {
                "filter_idx": 0,
                "match_hex": match_pattern,
                "mask_hex": mask_pattern,
                "port_number": port,
                "direction": "ingress",
            })

            # Also write filter 1 with a different pattern
            match1 = "11223344" * 16
            resp1 = self._ptrace_post("filter", {
                "filter_idx": 1,
                "match_hex": match1,
                "mask_hex": mask_pattern,
                "port_number": port,
                "direction": "ingress",
            })

            r.data = {
                "filter0_write": resp0,
                "filter1_write": resp1,
                "filter0_match": match_pattern,
                "filter0_mask": mask_pattern,
                "filter1_match": match1,
                "note": (
                    "CRITICAL: Verify interleaved layout by reading raw registers at "
                    "offsets 0x200-0x27F (filter 0) and 0x280-0x2FF (filter 1). "
                    "Expected interleaved: 0x200=match[0], 0x204=mask[0], "
                    "0x208=match[1], 0x20C=mask[1], etc. "
                    "If contiguous: 0x200-0x23F=all match, 0x240-0x27F=all mask."
                ),
            }
            r.expected = "Filter writes succeed"
            r.actual = f"Filter 0: {resp0}, Filter 1: {resp1}"
            r.status = "PASS"
            r.notes = ("Writes succeeded. MANUAL STEP NEEDED: Use PCIe Registers page to "
                       "read offsets 0x200-0x27F to verify interleaved vs contiguous layout.")

        self._run_test("3.2_filter_data_write", 3, "512-bit filter data write", test_3_2)

        # 3.3 — Condition data 512-bit blocks
        def test_3_3(r: TestResult):
            self._stop(port)

            match_c0 = "DEADBEEF" * 16
            mask_c0 = "FFFFFFFF" * 16

            try:
                resp = self._ptrace_post("condition-data", {
                    "port_number": port, "direction": "ingress",
                    "config": {"condition_id": 0, "match_hex": match_c0, "mask_hex": mask_c0},
                })
                r.data = {
                    "cond0_write": resp,
                    "cond0_match": match_c0,
                    "note": (
                        "Verify by reading offsets 0x300-0x37F (cond 0). "
                        "Same interleaved layout question as filters."
                    ),
                }
                r.expected = "Condition data write succeeds"
                r.actual = f"Response: {resp}"
                r.status = "PASS"
            except requests.HTTPError as exc:
                if exc.response.status_code == 501:
                    r.status = "SKIP"
                    r.notes = "Condition data not available (B0 silicon)"
                    return
                raise

        self._run_test("3.3_condition_data_write", 3, "512-bit condition data write", test_3_3)

        # 3.4 — Filter with capture: does filter actually work?
        def test_3_4(r: TestResult):
            self._stop(port)
            self._clear(port)

            # Write a filter that should match nothing (all zeros match, all ones mask)
            self._ptrace_post("filter", {
                "filter_idx": 0,
                "match_hex": "0" * 128,
                "mask_hex": "F" * 128,  # mask everything — only exact zero match
                "port_number": port,
                "direction": "ingress",
            })

            # Enable filtering in capture config
            self._configure(
                port,
                capture={
                    "port_number": port, "direction": "ingress",
                    "filter_en": True,
                },
                trigger={"trigger_src": 0},
            )
            self._start(port)
            time.sleep(1.0)
            self._manual_trigger(port)
            time.sleep(1.0)
            self._status(port)  # ensure capture settles
            buf_filtered = self._buffer(port, max_rows=16)
            self._stop(port)

            # Now disable filtering and repeat
            self._clear(port)
            self._configure(
                port,
                capture={
                    "port_number": port, "direction": "ingress",
                    "filter_en": False,
                },
                trigger={"trigger_src": 0},
            )
            self._start(port)
            time.sleep(1.0)
            self._manual_trigger(port)
            time.sleep(1.0)
            self._status(port)  # ensure capture settles
            buf_unfiltered = self._buffer(port, max_rows=16)
            self._stop(port)

            filtered_rows = buf_filtered.get("total_rows_read", 0)
            unfiltered_rows = buf_unfiltered.get("total_rows_read", 0)

            # Count non-zero rows
            nz_filtered = sum(
                1 for row in buf_filtered.get("rows", [])
                if row.get("hex_str", "").replace("0", "")
            )
            nz_unfiltered = sum(
                1 for row in buf_unfiltered.get("rows", [])
                if row.get("hex_str", "").replace("0", "")
            )

            r.data = {
                "filtered": {"rows": filtered_rows, "nonzero": nz_filtered},
                "unfiltered": {"rows": unfiltered_rows, "nonzero": nz_unfiltered},
            }
            r.expected = "Filtered capture has fewer non-zero rows than unfiltered"
            r.actual = f"Filtered: {nz_filtered} nonzero, Unfiltered: {nz_unfiltered} nonzero"

            if nz_unfiltered > nz_filtered:
                r.status = "PASS"
                r.notes = "Filter visibly reduced captured data"
            elif nz_unfiltered == 0 and nz_filtered == 0:
                r.status = "WARN"
                r.notes = "Both captures empty — no traffic on port?"
            else:
                r.status = "WARN"
                r.notes = "Filter did not visibly reduce data — may need different filter pattern"

        self._run_test("3.4_filter_effect", 3, "Filter effect on capture", test_3_4)

    # -----------------------------------------------------------------------
    # Phase 4: Event Counters
    # -----------------------------------------------------------------------

    def phase4_event_counters(self):
        print("\n=== Phase 4: Event Counters ===")
        port = self.port_number

        # 4.1 — Event counter trigger with various source IDs
        def test_4_1(r: TestResult):
            # Try a range of event source IDs with low threshold
            # to see which ones fire quickly
            results = {}
            for evt_src in range(16):
                try:
                    self._stop(port)
                    self._clear(port)
                    self._ptrace_post("event-counter", {
                        "port_number": port, "direction": "ingress",
                        "counter_id": 0,
                        "event_source": evt_src,
                        "threshold": 1,
                    })
                    self._configure(
                        port,
                        trigger={"trigger_src": 7},  # EVENT_COUNTER_THRESHOLD
                    )
                    self._start(port)
                    time.sleep(2.0)
                    s = self._status(port)
                    triggered = s.get("triggered", False)
                    results[evt_src] = {"triggered": triggered}
                except Exception as exc:
                    results[evt_src] = {"error": str(exc)}
                finally:
                    try:
                        self._stop(port)
                    except Exception:
                        pass

            r.data = {"event_source_results": results}
            triggered_sources = [k for k, v in results.items() if v.get("triggered")]
            r.expected = "At least some event sources trigger"
            r.actual = f"Triggered: {triggered_sources}"
            if triggered_sources:
                r.status = "PASS"
                r.notes = (f"Event sources that triggered (threshold=1, 2s wait): "
                           f"{triggered_sources}")
            else:
                r.status = "WARN"
                r.notes = "No event sources triggered — may need longer wait or active traffic"

        self._run_test("4.1_event_counter_sources", 4,
                        "Event counter source ID sweep (0-15)", test_4_1)

    # -----------------------------------------------------------------------
    # Phase 5: Error Triggers
    # -----------------------------------------------------------------------

    def phase5_error_triggers(self):
        print("\n=== Phase 5: Error Triggers ===")
        port = self.port_number

        # 5.1 — Error trigger enable/status read
        def test_5_1(r: TestResult):
            self._stop(port)
            self._clear(port)

            # Enable all error triggers
            err_mask = 0x0FFFFFFF
            self._ptrace_post("error-trigger", {
                "port_number": port, "direction": "ingress",
                "error_mask": err_mask,
            })

            # Read status to get current port_err_status
            s = self._status(port)
            err_status = s.get("port_err_status", 0)

            r.data = {
                "error_mask_written": f"0x{err_mask:08X}",
                "port_err_status": f"0x{err_status:08X}",
                "status": s,
            }
            r.expected = "Error trigger mask writes without error"
            r.actual = f"port_err_status=0x{err_status:08X}"

            if err_status != 0:
                r.status = "WARN"
                r.notes = (f"Non-zero error status at idle (0x{err_status:08X}) — "
                           "may indicate existing errors or wrong register offset")
                # Decode which bits are set
                set_bits = []
                for bit in range(28):
                    if err_status & (1 << bit):
                        set_bits.append(bit)
                r.data["error_bits_set"] = set_bits
            else:
                r.status = "PASS"

        self._run_test("5.1_error_trigger_setup", 5, "Error trigger enable + status read", test_5_1)

    # -----------------------------------------------------------------------
    # Phase 6: Timestamp Characterization
    # -----------------------------------------------------------------------

    def phase6_timestamps(self):
        print("\n=== Phase 6: Timestamp Characterization ===")
        port = self.port_number

        # 6.1 — Global timer clock frequency estimation
        def test_6_1(r: TestResult):
            # Take two status reads spaced by known wall-clock time
            self._stop(port)
            self._clear(port)
            self._configure(port)
            self._start(port)
            time.sleep(0.5)

            s1 = self._status(port)
            t1 = time.monotonic()
            time.sleep(5.0)
            s2 = self._status(port)
            t2 = time.monotonic()
            self._stop(port)

            gt1 = s1.get("global_timer", 0)
            gt2 = s2.get("global_timer", 0)
            wall_delta = t2 - t1
            timer_delta = gt2 - gt1

            r.data = {
                "global_timer_1": gt1,
                "global_timer_2": gt2,
                "wall_seconds": round(wall_delta, 3),
                "timer_delta": timer_delta,
            }

            if timer_delta > 0:
                freq_hz = timer_delta / wall_delta
                freq_mhz = freq_hz / 1e6
                r.data["estimated_freq_hz"] = round(freq_hz)
                r.data["estimated_freq_mhz"] = round(freq_mhz, 2)
                r.expected = "Global timer increments over time"
                r.actual = (f"delta={timer_delta} ticks in {wall_delta:.1f}s "
                            f"=> ~{freq_mhz:.2f} MHz")
                r.status = "PASS"
            elif gt1 == 0 and gt2 == 0:
                r.expected = "Global timer increments"
                r.actual = "global_timer=0 in both reads"
                r.status = "FAIL"
                r.notes = ("Global timer always zero — register offset may be wrong, "
                           "or timer only runs during active capture window")
            else:
                r.expected = "Global timer increments"
                r.actual = f"gt1={gt1}, gt2={gt2}, delta={timer_delta}"
                r.status = "WARN"
                r.notes = "Timer did not increment — may be stopped or wrong offset"

        self._run_test("6.1_clock_frequency", 6, "Global timer clock frequency", test_6_1)

        # 6.2 — Timestamp semantics (start, trigger, last relationships)
        def test_6_2(r: TestResult):
            self._stop(port)
            self._clear(port)
            self._configure(port, trigger={"trigger_src": 0})
            self._start(port)
            time.sleep(1.0)
            self._manual_trigger(port)
            time.sleep(1.0)
            s = self._status(port)
            self._stop(port)

            start_ts = s.get("start_ts", 0)
            trigger_ts = s.get("trigger_ts", 0)
            last_ts = s.get("last_ts", 0)
            global_timer = s.get("global_timer", 0)

            r.data = {
                "start_ts": start_ts,
                "trigger_ts": trigger_ts,
                "last_ts": last_ts,
                "global_timer": global_timer,
                "trigger_minus_start": trigger_ts - start_ts if trigger_ts and start_ts else None,
                "last_minus_trigger": last_ts - trigger_ts if last_ts and trigger_ts else None,
            }
            r.expected = "start_ts < trigger_ts <= last_ts, global_timer >= last_ts"
            r.actual = (f"start={start_ts}, trigger={trigger_ts}, "
                        f"last={last_ts}, global={global_timer}")

            ordering_ok = True
            issues = []
            if start_ts == 0:
                issues.append("start_ts=0")
            if trigger_ts == 0:
                issues.append("trigger_ts=0")
            if start_ts and trigger_ts and trigger_ts < start_ts:
                issues.append("trigger_ts < start_ts!")
                ordering_ok = False
            if trigger_ts and last_ts and last_ts < trigger_ts:
                issues.append("last_ts < trigger_ts!")
                ordering_ok = False

            if ordering_ok and not issues:
                r.status = "PASS"
            elif ordering_ok:
                r.status = "WARN"
                r.notes = f"Ordering OK but: {', '.join(issues)}"
            else:
                r.status = "FAIL"
                r.notes = f"Timestamp ordering violation: {', '.join(issues)}"

        self._run_test("6.2_timestamp_semantics", 6, "Timestamp ordering semantics", test_6_2)

        # 6.3 — ReArm time units
        def test_6_3(r: TestResult):
            # Configure with rearm, trigger twice, measure gap
            self._stop(port)
            self._clear(port)

            rearm_value = 1000
            self._configure(
                port,
                trigger={
                    "trigger_src": 0,
                    "rearm_enable": True,
                    "rearm_time": rearm_value,
                },
            )
            self._start(port)
            time.sleep(0.5)

            # First trigger
            self._manual_trigger(port)
            time.sleep(0.1)
            s1 = self._status(port)

            # Wait for rearm
            time.sleep(2.0)

            # Clear and re-trigger
            self._clear(port)
            self._start(port)
            time.sleep(0.5)
            self._manual_trigger(port)
            time.sleep(0.5)
            s2 = self._status(port)
            self._stop(port)

            r.data = {
                "rearm_value": rearm_value,
                "first_trigger": s1,
                "second_trigger": s2,
            }
            r.expected = "Both triggers succeed; gap between them reflects rearm time"
            t1_trig = s1.get("triggered", False)
            t2_trig = s2.get("triggered", False)
            r.actual = f"first_triggered={t1_trig}, second_triggered={t2_trig}"

            if t1_trig and t2_trig:
                r.status = "PASS"
                gap_ts = s2.get("trigger_ts", 0) - s1.get("trigger_ts", 0)
                r.data["trigger_gap_ticks"] = gap_ts
                r.notes = f"Trigger gap: {gap_ts} ticks (rearm_value={rearm_value})"
            elif t1_trig:
                r.status = "WARN"
                r.notes = "First trigger OK but second did not fire — rearm may not have completed"
            else:
                r.status = "FAIL"
                r.notes = "First trigger did not fire"

        self._run_test("6.3_rearm_time_units", 6, "ReArm time unit estimation", test_6_3)

    # -----------------------------------------------------------------------
    # Phase 7: Buffer Format Validation
    # -----------------------------------------------------------------------

    def phase7_buffer_format(self):
        print("\n=== Phase 7: Buffer Format Validation ===")
        port = self.port_number

        # 7.1 — Trace buffer row format (19 DWORDs, 600 vs 608 bits)
        def test_7_1(r: TestResult):
            self._stop(port)
            self._clear(port)
            self._configure(port, trigger={"trigger_src": 0})
            self._start(port)
            time.sleep(1.0)
            self._manual_trigger(port)
            time.sleep(1.0)
            buf = self._buffer(port, max_rows=64)
            self._stop(port)

            rows = buf.get("rows", [])
            r.data["total_rows"] = len(rows)

            if not rows:
                r.status = "WARN"
                r.notes = "No buffer data to analyze"
                return

            # Analyze DWORD 18 (the 19th, 0-indexed) of each row
            dw18_values = []
            dw18_top_byte = []
            for row in rows:
                dwords = row.get("dwords", [])
                if len(dwords) >= 19:
                    val = dwords[18]
                    dw18_values.append(val)
                    top_byte = (val >> 24) & 0xFF
                    dw18_top_byte.append(top_byte)

            # Check if top byte is always the same (reserved/flags)
            unique_top = set(dw18_top_byte)
            all_zero_top = all(b == 0 for b in dw18_top_byte)

            r.data["dw18_sample"] = [f"0x{v:08X}" for v in dw18_values[:10]]
            r.data["dw18_top_byte_unique"] = sorted([f"0x{b:02X}" for b in unique_top])
            r.data["dw18_top_byte_all_zero"] = all_zero_top
            r.data["dw18_count"] = len(dw18_values)

            r.expected = "Top 8 bits of DWORD 18 reveal reserved/flag pattern"
            r.actual = (f"{len(unique_top)} unique top-byte values, "
                        f"all_zero={all_zero_top}")

            if all_zero_top:
                r.status = "PASS"
                r.notes = "Top 8 bits of DWORD 18 are always 0 — confirms 600-bit data + 8 reserved"
            elif len(unique_top) <= 4:
                r.status = "WARN"
                r.notes = (f"Top byte has {len(unique_top)} unique values — "
                           f"may be flags: {r.data['dw18_top_byte_unique']}")
            else:
                r.status = "WARN"
                r.notes = "Top byte varies widely — may be data, not reserved"

        self._run_test("7.1_buffer_row_format", 7, "Trace buffer row format analysis", test_7_1)

        # 7.2 — Buffer wrap behavior
        def test_7_2(r: TestResult):
            self._stop(port)
            self._clear(port)
            # Very small post-trigger count so buffer wraps quickly
            self._configure(
                port,
                trigger={"trigger_src": 0},
                post_trigger={"cap_count": 5, "count_type": 0},
            )
            self._start(port)
            time.sleep(2.0)
            self._manual_trigger(port)
            time.sleep(2.0)
            s = self._status(port)
            buf = self._buffer(port, max_rows=32)
            self._stop(port)

            wrapped = s.get("tbuf_wrapped", False)
            triggered = s.get("triggered", False)
            trigger_row = s.get("trigger_row_addr", 0)

            r.data = {
                "status": s,
                "buffer_rows_read": buf.get("total_rows_read", 0),
                "wrapped": wrapped,
                "trigger_row": trigger_row,
            }
            r.expected = "Buffer wraps with small post-trigger count"
            r.actual = f"wrapped={wrapped}, triggered={triggered}, trigger_row={trigger_row}"

            if triggered:
                r.status = "PASS"
                if wrapped:
                    r.notes = "Buffer wrapped as expected"
                else:
                    r.notes = "Buffer did not wrap — post_trigger may be too large or capture too short"
            else:
                r.status = "FAIL"
                r.notes = "Trigger did not fire"

        self._run_test("7.2_buffer_wrap", 7, "Buffer wrap behavior", test_7_2)

        # 7.3 — Large buffer read (auto-increment stress test)
        def test_7_3(r: TestResult):
            self._stop(port)
            self._clear(port)
            self._configure(port, trigger={"trigger_src": 0})
            self._start(port)
            time.sleep(2.0)
            self._manual_trigger(port)
            time.sleep(1.0)

            # Read 256 rows — tests auto-increment across many rows
            t0 = time.monotonic()
            buf = self._buffer(port, max_rows=256)
            read_time = time.monotonic() - t0
            self._stop(port)

            rows = buf.get("rows", [])
            total = buf.get("total_rows_read", 0)

            # Check for misalignment: look for rows that are all-same-value
            # (which would indicate the auto-increment skipped)
            suspicious = 0
            for row in rows:
                dwords = row.get("dwords", [])
                if len(dwords) >= 19 and len(set(dwords)) == 1:
                    suspicious += 1

            r.data = {
                "rows_requested": 256,
                "rows_returned": total,
                "read_time_sec": round(read_time, 2),
                "suspicious_uniform_rows": suspicious,
                "rows_per_sec": round(total / read_time, 1) if read_time > 0 else 0,
            }
            r.expected = "256 rows read without misalignment"
            r.actual = (f"Read {total} rows in {read_time:.2f}s, "
                        f"{suspicious} suspicious uniform rows")

            if suspicious <= 2:
                r.status = "PASS"
            else:
                r.status = "WARN"
                r.notes = (f"{suspicious} rows with all-identical DWORDs — "
                           "may indicate auto-increment misalignment")

        self._run_test("7.3_large_buffer_read", 7, "Large buffer read (auto-increment)", test_7_3)

    # -----------------------------------------------------------------------
    # Run all phases
    # -----------------------------------------------------------------------

    def run(self) -> int:
        """Run all requested phases. Returns exit code (0=all pass, 1=failures)."""
        if not self.discover():
            return 2

        phase_map = {
            1: self.phase1_smoke_test,
            2: self.phase2_trigger_sources,
            3: self.phase3_flit_and_filters,
            4: self.phase4_event_counters,
            5: self.phase5_error_triggers,
            6: self.phase6_timestamps,
            7: self.phase7_buffer_format,
        }

        for phase_num in sorted(self.phases):
            fn = phase_map.get(phase_num)
            if fn:
                try:
                    fn()
                except Exception as exc:
                    print(f"\n  PHASE {phase_num} ABORTED: {exc}")

        # Always clean up: stop capture
        try:
            self._stop(self.port_number, "ingress")
        except Exception:
            pass
        try:
            self._stop(self.port_number, "egress")
        except Exception:
            pass

        # Write results
        self._write_results()
        return self._print_summary()

    def _write_results(self):
        """Write machine-readable results JSON."""
        output = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "device_id": self.device_id,
            "device_info": self.device_info,
            "test_port": self.port_number,
            "ltssm_state": f"0x{self.ltssm_state:03X}",
            "results": [asdict(r) for r in self.results],
        }
        results_path = self.output_dir / "results.json"
        with open(results_path, "w") as f:
            json.dump(output, f, indent=2, default=str)
        print(f"\n  Results written to: {results_path}")

    def _print_summary(self) -> int:
        """Print human-readable summary. Returns exit code."""
        counts = {"PASS": 0, "FAIL": 0, "WARN": 0, "ERROR": 0, "SKIP": 0}
        for r in self.results:
            counts[r.status] = counts.get(r.status, 0) + 1

        lines = []
        lines.append("")
        lines.append("=" * 70)
        lines.append("PTrace Hardware Validation Summary")
        lines.append("=" * 70)
        lines.append(f"Device:    {self.device_id}")
        lines.append(f"Chip ID:   0x{self.device_info.get('chip_id', 0):04X}")
        lines.append(f"Test port: {self.port_number}")
        lines.append(f"LTSSM:     0x{self.ltssm_state:03X}")
        lines.append(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
        lines.append("")
        lines.append(f"  PASS:  {counts['PASS']:3d}")
        lines.append(f"  FAIL:  {counts['FAIL']:3d}")
        lines.append(f"  WARN:  {counts['WARN']:3d}")
        lines.append(f"  ERROR: {counts['ERROR']:3d}")
        lines.append(f"  SKIP:  {counts['SKIP']:3d}")
        lines.append(f"  TOTAL: {sum(counts.values()):3d}")
        lines.append("")

        # List failures and warnings
        for status_type in ("FAIL", "ERROR", "WARN"):
            items = [r for r in self.results if r.status == status_type]
            if items:
                lines.append(f"--- {status_type} ---")
                for r in items:
                    lines.append(f"  {r.test_id}: {r.name}")
                    if r.notes:
                        for line in r.notes.split("\n"):
                            lines.append(f"    {line}")
                lines.append("")

        # Manual follow-up actions
        lines.append("--- MANUAL FOLLOW-UP ACTIONS ---")
        lines.append("  1. Use PCIe Registers page to read raw offsets 0x200-0x27F")
        lines.append("     to verify interleaved (match/mask pairs) vs contiguous filter layout")
        lines.append("  2. Similarly read 0x300-0x37F for condition data block layout")
        lines.append("  3. Check if global_timer value in results.json is nonzero and")
        lines.append("     incrementing — if not, timer offset may need adjustment")
        lines.append("  4. Record the estimated clock frequency from test 6.1 for")
        lines.append("     converting all timestamps to real time")
        lines.append("=" * 70)

        summary = "\n".join(lines)
        print(summary)

        # Write summary file
        summary_path = self.output_dir / "summary.txt"
        with open(summary_path, "w") as f:
            f.write(summary)
        print(f"\n  Summary written to: {summary_path}")
        print(f"  Raw responses in:   {self.raw_dir}")

        return 1 if counts["FAIL"] > 0 or counts["ERROR"] > 0 else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="PTrace Hardware Validation Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Run all phases against auto-detected device\n"
            "  python scripts/ptrace_hw_validation.py\n\n"
            "  # Specific device and port, phases 1-3 only\n"
            "  python scripts/ptrace_hw_validation.py "
            "--device-id dev_03_00 --port 16 --phases 1,2,3\n\n"
            "  # Custom server URL\n"
            "  python scripts/ptrace_hw_validation.py "
            "--base-url http://192.168.1.100:8000\n"
        ),
    )
    parser.add_argument(
        "--base-url", default="http://localhost:8000",
        help="Calypso server base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--device-id", default=None,
        help="Device ID (e.g., dev_03_00). Auto-detected if not specified.",
    )
    parser.add_argument(
        "--port", type=int, default=None,
        help="Port number to test. Auto-selects first link-up port if not specified.",
    )
    parser.add_argument(
        "--output-dir", default="./ptrace_validation",
        help="Output directory (default: ./ptrace_validation)",
    )
    parser.add_argument(
        "--phases", default="1,2,3,4,5,6,7",
        help="Comma-separated phase numbers to run (default: 1,2,3,4,5,6,7)",
    )
    args = parser.parse_args()

    phases = {int(p.strip()) for p in args.phases.split(",") if p.strip()}

    # Create timestamped output directory
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir) / ts
    output_dir.mkdir(parents=True, exist_ok=True)

    print("PTrace Hardware Validation")
    print(f"Output: {output_dir}")
    print(f"Phases: {sorted(phases)}")

    validator = PTraceValidator(
        base_url=args.base_url,
        device_id=args.device_id,
        port_number=args.port,
        output_dir=output_dir,
        phases=phases,
    )

    sys.exit(validator.run())


if __name__ == "__main__":
    main()
