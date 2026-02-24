#!/usr/bin/env python3
"""Packet Exerciser Hardware Validation Script.

Automated test suite that exercises the PCIe Packet Exerciser and Datapath
BIST functionality against live Atlas3 hardware. Validates TLP generation,
completion handling, and PTrace integration.

Prerequisites:
    - Calypso server running: calypso serve --host 0.0.0.0 --port 8000
    - At least one Atlas3 device connected (auto-detected)
    - At least one downstream port with link up (auto-detected)

Usage:
    python scripts/pktexer_hw_validation.py [--base-url http://localhost:8000]
                                            [--device-id dev_xx_xx]
                                            [--port PORT_NUMBER]
                                            [--output-dir ./pktexer_validation]
                                            [--phases 1,2,3,4,5]

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
from dataclasses import asdict, dataclass, field
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


class PktExerValidator:
    """Drives Packet Exerciser hardware validation tests via the REST API."""

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
        self.device_info: dict = {}

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
        print(
            f"  [{status_char.get(result.status, '?')}] "
            f"{test_id}: {name} ({result.status})"
        )
        if result.notes:
            for line in result.notes.split("\n")[:3]:
                print(f"      {line}")
        return result

    # -- Exerciser API helpers --

    def _exer_post(self, endpoint: str, body: dict) -> dict:
        return self._post(
            f"/devices/{self.device_id}/exerciser/{endpoint}", body
        )

    def _exer_get(self, endpoint: str, params: dict | None = None) -> dict:
        return self._get(
            f"/devices/{self.device_id}/exerciser/{endpoint}", params
        )

    def _send_tlps(self, tlps: list[dict], **kwargs) -> dict:
        body = {
            "port_number": self.port_number,
            "tlps": tlps,
            "infinite_loop": kwargs.get("infinite_loop", False),
            "max_outstanding_np": kwargs.get("max_outstanding_np", 8),
        }
        return self._exer_post("send", body)

    def _stop(self) -> dict:
        return self._post(
            f"/devices/{self.device_id}/exerciser/stop?port_number={self.port_number}",
            None,
        )

    def _status(self) -> dict:
        return self._exer_get("status", {"port_number": self.port_number})

    # -----------------------------------------------------------------------
    # Phase 0: Discovery & Setup
    # -----------------------------------------------------------------------

    def discover(self) -> bool:
        print("\n=== Phase 0: Discovery ===")

        try:
            requests.get(f"{self.base_url}/api/devices", timeout=5)
        except Exception:
            print(f"  ERROR: Cannot reach Calypso server at {self.base_url}")
            print("  Start with: calypso serve --host 0.0.0.0 --port 8000")
            return False

        if not self.device_id:
            devices = self._get("/devices")
            if not devices:
                print("  ERROR: No connected devices.")
                return False
            self.device_id = devices[0]
            print(f"  Auto-selected device: {self.device_id}")
        else:
            print(f"  Using specified device: {self.device_id}")

        try:
            self.device_info = self._get(f"/devices/{self.device_id}/info")
            chip_id = self.device_info.get("chip_id", 0)
            print(f"  Chip: {self.device_info.get('chip_name', 'unknown')}")
            print(f"  Chip ID: 0x{chip_id:04X}")
        except Exception as exc:
            print(f"  WARNING: Could not get device info: {exc}")

        if self.port_number is None:
            ports = self._get(f"/devices/{self.device_id}/ports")
            active = [p for p in ports if p.get("is_link_up")]
            if not active:
                print("  ERROR: No link-up ports found.")
                return False
            self.port_number = active[0]["port_number"]
            print(f"  Auto-selected port: {self.port_number}")
        else:
            print(f"  Using specified port: {self.port_number}")

        print("  Discovery complete.")
        return True

    # -----------------------------------------------------------------------
    # Phase 1: Exerciser Smoke Test
    # -----------------------------------------------------------------------

    def phase1_smoke_test(self):
        print("\n=== Phase 1: Exerciser Smoke Test ===")

        # 1.1 — Read initial status
        def test_1_1(r: TestResult):
            status = self._status()
            r.data = {"status": status}
            r.expected = "Status API returns valid response"
            r.actual = f"enabled={status.get('enabled')}, threads={len(status.get('threads', []))}"
            r.status = "PASS" if "enabled" in status else "FAIL"

        self._run_test("1.1_initial_status", 1, "Read initial exerciser status", test_1_1)

        # 1.2 — Send a simple MR32 TLP
        def test_1_2(r: TestResult):
            resp = self._send_tlps([{"tlp_type": "mr32", "address": 0, "length_dw": 1}])
            r.data = {"send_response": resp}
            time.sleep(0.1)
            status = self._status()
            r.data["post_status"] = status
            self._stop()
            r.expected = "Send accepted, exerciser status readable"
            r.actual = f"send={resp}, enabled={status.get('enabled')}"
            r.status = "PASS" if resp.get("status") == "started" else "FAIL"

        self._run_test("1.2_send_mr32", 1, "Send MR32 TLP", test_1_2)

        # 1.3 — Stop exerciser
        def test_1_3(r: TestResult):
            resp = self._stop()
            status = self._status()
            r.data = {"stop_response": resp, "post_status": status}
            r.expected = "Exerciser stopped"
            r.actual = f"stop={resp}, enabled={status.get('enabled')}"
            r.status = "PASS" if not status.get("enabled", True) else "WARN"

        self._run_test("1.3_stop", 1, "Stop exerciser", test_1_3)

    # -----------------------------------------------------------------------
    # Phase 2: All TLP Types
    # -----------------------------------------------------------------------

    def phase2_all_tlp_types(self):
        print("\n=== Phase 2: All TLP Types ===")

        tlp_types = [
            ("mr32", {}),
            ("mw32", {"data": "DEADBEEF"}),
            ("mr64", {"address": 0x100000000}),
            ("mw64", {"address": 0x100000000, "data": "CAFEBABE"}),
            ("cfrd0", {"target_id": 0x0100, "address": 0x40}),
            ("cfwr0", {"target_id": 0x0100, "address": 0x04, "data": "12345678"}),
            ("cfrd1", {"target_id": 0x0200}),
            ("cfwr1", {"target_id": 0x0200, "address": 0x08, "data": "AABBCCDD"}),
            ("PMNak", {}),
            ("PME", {}),
            ("PMEOff", {}),
            ("PMEAck", {}),
            ("ERRCor", {}),
            ("ERRNF", {}),
            ("ERRF", {}),
        ]

        for idx, (tlp_type, extra) in enumerate(tlp_types, 1):
            def make_test(tt, ex):
                def test_fn(r: TestResult):
                    tlp_cfg = {"tlp_type": tt, "length_dw": 1, **ex}
                    try:
                        resp = self._send_tlps([tlp_cfg])
                        r.data = {"tlp_type": tt, "config": tlp_cfg, "response": resp}
                        time.sleep(0.05)
                        status = self._status()
                        r.data["post_status"] = status
                        self._stop()
                        r.expected = f"Send {tt} accepted"
                        r.actual = f"resp={resp.get('status')}"
                        r.status = "PASS" if resp.get("status") == "started" else "FAIL"
                    except requests.HTTPError as exc:
                        r.data = {"tlp_type": tt, "error": str(exc)}
                        r.expected = f"Send {tt} accepted"
                        r.actual = f"HTTP error: {exc.response.status_code}"
                        r.status = "FAIL"
                return test_fn

            self._run_test(
                f"2.{idx}_send_{tlp_type}",
                2,
                f"Send {tlp_type}",
                make_test(tlp_type, extra),
            )

    # -----------------------------------------------------------------------
    # Phase 3: Completion Handling
    # -----------------------------------------------------------------------

    def phase3_completion(self):
        print("\n=== Phase 3: Completion Handling ===")

        # 3.1 — MR32 should generate a completion
        def test_3_1(r: TestResult):
            self._stop()
            self._send_tlps([{"tlp_type": "mr32", "address": 0, "length_dw": 1}])
            time.sleep(0.5)
            status = self._status()
            self._stop()

            cpl_recv = status.get("completion_received", False)
            cpl_status = status.get("completion_status", -1)
            cpl_data = status.get("completion_data", 0)

            r.data = {
                "completion_received": cpl_recv,
                "completion_status": cpl_status,
                "completion_data": f"0x{cpl_data:08X}",
                "full_status": status,
            }
            r.expected = "Completion received after MR32"
            r.actual = (
                f"received={cpl_recv}, status={cpl_status}, "
                f"data=0x{cpl_data:08X}"
            )
            if cpl_recv:
                r.status = "PASS"
            else:
                r.status = "WARN"
                r.notes = (
                    "No completion received — may need a valid target address, "
                    "or the switch may not route completions back to the exerciser port"
                )

        self._run_test("3.1_mr32_completion", 3, "MR32 completion", test_3_1)

    # -----------------------------------------------------------------------
    # Phase 4: DP BIST
    # -----------------------------------------------------------------------

    def phase4_dp_bist(self):
        print("\n=== Phase 4: DP BIST ===")

        # 4.1 — Start and read BIST status
        def test_4_1(r: TestResult):
            start_resp = self._post(
                f"/devices/{self.device_id}/exerciser/dp-bist/start",
                {"loop_count": 10, "inner_loop_count": 5, "delay_count": 0, "infinite": False},
            )
            time.sleep(1.0)
            status = self._exer_get("dp-bist/status", {"port_number": self.port_number})
            r.data = {"start_response": start_resp, "status": status}
            r.expected = "BIST starts and reports tx_done/rx_done"
            r.actual = (
                f"tx_done={status.get('tx_done')}, "
                f"rx_done={status.get('rx_done')}, "
                f"passed={status.get('passed')}"
            )
            if status.get("tx_done"):
                r.status = "PASS" if status.get("passed") else "FAIL"
            else:
                r.status = "WARN"
                r.notes = "BIST tx_done not set — may need more time or different port configuration"

        self._run_test("4.1_dp_bist", 4, "DP BIST run", test_4_1)

        # 4.2 — Stop BIST
        def test_4_2(r: TestResult):
            resp = self._post(
                f"/devices/{self.device_id}/exerciser/dp-bist/stop",
                None,
            )
            r.data = {"stop_response": resp}
            r.expected = "BIST stop accepted"
            r.actual = f"resp={resp}"
            r.status = "PASS" if resp.get("status") == "stopped" else "FAIL"

        self._run_test("4.2_dp_bist_stop", 4, "DP BIST stop", test_4_2)

    # -----------------------------------------------------------------------
    # Phase 5: PTrace + Exerciser Integration
    # -----------------------------------------------------------------------

    def phase5_ptrace_integration(self):
        print("\n=== Phase 5: PTrace + Exerciser Integration ===")

        # 5.1 — Capture and send MR32
        def test_5_1(r: TestResult):
            body = {
                "port_number": self.port_number,
                "ptrace_direction": "egress",
                "exerciser": {
                    "port_number": self.port_number,
                    "tlps": [{"tlp_type": "mr32", "address": 0, "length_dw": 1}],
                    "infinite_loop": False,
                    "max_outstanding_np": 8,
                },
                "read_buffer": True,
                "post_trigger_wait_ms": 200,
            }
            resp = self._exer_post("capture-and-send", body)
            r.data = {
                "exerciser_status": resp.get("exerciser_status"),
                "ptrace_triggered": resp.get("ptrace_status", {}).get("triggered"),
                "buffer_rows": resp.get("ptrace_buffer", {}).get("total_rows_read", 0),
            }
            r.expected = "PTrace captures exerciser TLPs"
            rows = resp.get("ptrace_buffer", {}).get("total_rows_read", 0)
            r.actual = f"buffer_rows={rows}, triggered={resp.get('ptrace_status', {}).get('triggered')}"
            r.status = "PASS" if rows > 0 else "WARN"
            if rows == 0:
                r.notes = "No trace data captured — exerciser TLPs may not be visible at this trace point"

        self._run_test(
            "5.1_capture_and_send_mr32", 5,
            "PTrace capture + exerciser MR32", test_5_1,
        )

        # 5.2 — Capture MW32 and verify non-empty buffer
        def test_5_2(r: TestResult):
            body = {
                "port_number": self.port_number,
                "ptrace_direction": "egress",
                "exerciser": {
                    "port_number": self.port_number,
                    "tlps": [
                        {"tlp_type": "mw32", "address": 0x1000, "length_dw": 1, "data": "DEADBEEF"},
                    ],
                    "infinite_loop": False,
                    "max_outstanding_np": 8,
                },
                "read_buffer": True,
                "post_trigger_wait_ms": 500,
            }
            resp = self._exer_post("capture-and-send", body)

            buffer = resp.get("ptrace_buffer", {})
            rows = buffer.get("rows", [])
            non_empty = sum(
                1 for row in rows
                if row.get("hex_str", "0" * 152) != "0" * 152
            )

            r.data = {
                "total_rows": len(rows),
                "non_empty_rows": non_empty,
                "ptrace_triggered": resp.get("ptrace_status", {}).get("triggered"),
            }
            r.expected = "PTrace captures MW32 traffic"
            r.actual = f"total_rows={len(rows)}, non_empty={non_empty}"
            r.status = "PASS" if non_empty > 0 else "WARN"

        self._run_test(
            "5.2_capture_and_send_mw32", 5,
            "PTrace capture + exerciser MW32", test_5_2,
        )

        # 5.3 — Capture ERR_COR message
        def test_5_3(r: TestResult):
            body = {
                "port_number": self.port_number,
                "ptrace_direction": "egress",
                "exerciser": {
                    "port_number": self.port_number,
                    "tlps": [{"tlp_type": "ERRCor"}],
                    "infinite_loop": False,
                    "max_outstanding_np": 8,
                },
                "read_buffer": True,
                "post_trigger_wait_ms": 200,
            }
            resp = self._exer_post("capture-and-send", body)
            r.data = {
                "ptrace_triggered": resp.get("ptrace_status", {}).get("triggered"),
                "buffer_rows": resp.get("ptrace_buffer", {}).get("total_rows_read", 0),
            }
            r.expected = "ERR_COR message captured by PTrace"
            r.actual = f"rows={resp.get('ptrace_buffer', {}).get('total_rows_read', 0)}"
            r.status = "PASS" if resp.get("ptrace_buffer", {}).get("total_rows_read", 0) > 0 else "WARN"

        self._run_test(
            "5.3_capture_err_cor", 5,
            "PTrace capture + ERR_COR message", test_5_3,
        )

    # -----------------------------------------------------------------------
    # Run all phases
    # -----------------------------------------------------------------------

    def run(self) -> int:
        if not self.discover():
            return 2

        phase_map = {
            1: self.phase1_smoke_test,
            2: self.phase2_all_tlp_types,
            3: self.phase3_completion,
            4: self.phase4_dp_bist,
            5: self.phase5_ptrace_integration,
        }

        for phase_num in sorted(self.phases):
            fn = phase_map.get(phase_num)
            if fn:
                try:
                    fn()
                except Exception as exc:
                    print(f"\n  PHASE {phase_num} ABORTED: {exc}")

        # Cleanup
        try:
            self._stop()
        except Exception:
            pass

        self._write_results()
        return self._print_summary()

    def _write_results(self):
        output = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "device_id": self.device_id,
            "device_info": self.device_info,
            "test_port": self.port_number,
            "results": [asdict(r) for r in self.results],
        }
        results_path = self.output_dir / "results.json"
        with open(results_path, "w") as f:
            json.dump(output, f, indent=2, default=str)
        print(f"\n  Results written to: {results_path}")

    def _print_summary(self) -> int:
        counts = {"PASS": 0, "FAIL": 0, "WARN": 0, "ERROR": 0, "SKIP": 0}
        for r in self.results:
            counts[r.status] = counts.get(r.status, 0) + 1

        lines = [
            "",
            "=" * 70,
            "Packet Exerciser Hardware Validation Summary",
            "=" * 70,
            f"Device:    {self.device_id}",
            f"Chip ID:   0x{self.device_info.get('chip_id', 0):04X}",
            f"Test port: {self.port_number}",
            f"Timestamp: {datetime.now(timezone.utc).isoformat()}",
            "",
            f"  PASS:  {counts['PASS']:3d}",
            f"  FAIL:  {counts['FAIL']:3d}",
            f"  WARN:  {counts['WARN']:3d}",
            f"  ERROR: {counts['ERROR']:3d}",
            f"  SKIP:  {counts['SKIP']:3d}",
            f"  TOTAL: {sum(counts.values()):3d}",
            "",
        ]

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

        lines.extend([
            "--- NOTES ---",
            "  1. MR32 completions may not be received if the target address is invalid",
            "     or the switch does not route completions back to the exerciser port.",
            "  2. DP BIST requires specific port configuration to work correctly.",
            "  3. PTrace integration tests use egress direction to capture exerciser TLPs.",
            "  4. If buffer rows are all empty, the exerciser TLPs may not be visible",
            "     at the default trace point (Accum/Distrib).",
            "=" * 70,
        ])

        summary = "\n".join(lines)
        print(summary)

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
        description="Packet Exerciser Hardware Validation Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Run all phases against auto-detected device\n"
            "  python scripts/pktexer_hw_validation.py\n\n"
            "  # Specific device and port, phases 1-2 only\n"
            "  python scripts/pktexer_hw_validation.py "
            "--device-id dev_03_00 --port 16 --phases 1,2\n\n"
            "  # Custom server URL\n"
            "  python scripts/pktexer_hw_validation.py "
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
        "--output-dir", default="./pktexer_validation",
        help="Output directory (default: ./pktexer_validation)",
    )
    parser.add_argument(
        "--phases", default="1,2,3,4,5",
        help="Comma-separated phase numbers to run (default: 1,2,3,4,5)",
    )
    args = parser.parse_args()

    phases = {int(p.strip()) for p in args.phases.split(",") if p.strip()}

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir) / ts
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Packet Exerciser Hardware Validation")
    print(f"Output: {output_dir}")
    print(f"Phases: {sorted(phases)}")

    validator = PktExerValidator(
        base_url=args.base_url,
        device_id=args.device_id,
        port_number=args.port,
        output_dir=output_dir,
        phases=phases,
    )

    sys.exit(validator.run())


if __name__ == "__main__":
    main()
