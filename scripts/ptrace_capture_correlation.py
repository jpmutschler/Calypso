#!/usr/bin/env python3
"""PTrace Capture Correlation Script.

Reverse-engineers the PTrace 600-bit trace buffer row format by sending known
TLPs via the Packet Exerciser, capturing with PTrace, and scanning each row
for the known header DWORDs to map the layout.

Prerequisites:
    - Calypso server running: calypso serve --host 0.0.0.0 --port 8000
    - At least one Atlas3 device connected (auto-detected)
    - At least one downstream port with link up (auto-detected)

Usage:
    python scripts/ptrace_capture_correlation.py [--base-url http://localhost:8000]
                                                 [--device-id dev_xx_xx]
                                                 [--port PORT_NUMBER]
                                                 [--output-dir ./ptrace_correlation]
                                                 [--wait-ms 500]
                                                 [--phases 1,2,3,4,5,6,7]
                                                 [--trace-point 0]
                                                 [--data-cap]

Output:
    Creates a timestamped directory under --output-dir containing:
    - results.json     : Machine-readable full correlation results
    - summary.txt      : Human-readable correlation report
    - raw/             : Per-test raw API responses
"""

from __future__ import annotations

import argparse
import json
import struct
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

# Try importing build_tlp_header from calypso; fall back to local implementation
try:
    from calypso.hardware.pktexer_regs import (
        TlpType,
        _MSG_CODE,
        _TLP_FMT_TYPE,
        build_tlp_header,
    )
except ImportError:
    # Minimal local fallback for standalone usage
    from enum import Enum

    class TlpType(str, Enum):
        MR32 = "mr32"
        MW32 = "mw32"
        MR64 = "mr64"
        MW64 = "mw64"
        CFRD0 = "cfrd0"
        CFWR0 = "cfwr0"
        CFRD1 = "cfrd1"
        CFWR1 = "cfwr1"
        PM_NAK = "PMNak"
        PME = "PME"
        PME_OFF = "PMEOff"
        PME_ACK = "PMEAck"
        ERR_COR = "ERRCor"
        ERR_NF = "ERRNF"
        ERR_FATAL = "ERRF"

    _TLP_FMT_TYPE = {
        TlpType.MR32: (0b00, 0b00000),
        TlpType.MW32: (0b10, 0b00000),
        TlpType.MR64: (0b01, 0b00000),
        TlpType.MW64: (0b11, 0b00000),
        TlpType.CFRD0: (0b00, 0b00100),
        TlpType.CFWR0: (0b10, 0b00100),
        TlpType.CFRD1: (0b00, 0b00101),
        TlpType.CFWR1: (0b10, 0b00101),
        TlpType.PM_NAK: (0b01, 0b10100),
        TlpType.PME: (0b01, 0b10000),
        TlpType.PME_OFF: (0b01, 0b10011),
        TlpType.PME_ACK: (0b01, 0b10101),
        TlpType.ERR_COR: (0b01, 0b10000),
        TlpType.ERR_NF: (0b01, 0b10000),
        TlpType.ERR_FATAL: (0b01, 0b10000),
    }

    _MSG_CODE = {
        TlpType.PM_NAK: 0x14,
        TlpType.PME: 0x18,
        TlpType.PME_OFF: 0x19,
        TlpType.PME_ACK: 0x1B,
        TlpType.ERR_COR: 0x30,
        TlpType.ERR_NF: 0x31,
        TlpType.ERR_FATAL: 0x33,
    }

    def build_tlp_header(
        tlp_type,
        *,
        address=0,
        length_dw=1,
        requester_id=0,
        tag=0,
        target_id=0,
        first_be=0xF,
        last_be=0xF,
        data=None,
        relaxed_ordering=False,
        poisoned=False,
    ):
        fmt, type_code = _TLP_FMT_TYPE[tlp_type]
        length_field = length_dw & 0x3FF
        ep_bit = 1 if poisoned else 0
        attr_lo = 1 if relaxed_ordering else 0
        dw0 = (
            ((fmt & 0x7) << 29)
            | ((type_code & 0x1F) << 24)
            | ((ep_bit & 0x1) << 14)
            | ((attr_lo & 0x3) << 12)
            | (length_field & 0x3FF)
        )
        if tlp_type in _MSG_CODE:
            msg_code = _MSG_CODE[tlp_type]
            dw1 = ((requester_id & 0xFFFF) << 16) | ((tag & 0xFF) << 8) | (msg_code & 0xFF)
            return [dw0, dw1, 0x00000000, 0x00000000]
        is_config = tlp_type in (TlpType.CFRD0, TlpType.CFWR0, TlpType.CFRD1, TlpType.CFWR1)
        if is_config:
            dw1 = (
                ((requester_id & 0xFFFF) << 16)
                | ((tag & 0xFF) << 8)
                | ((first_be & 0xF) << 4)
                | (last_be & 0xF)
            )
            target_bus = (target_id >> 8) & 0xFF
            target_devfn = target_id & 0xFF
            reg_num = (address >> 2) & 0x3F
            ext_reg = (address >> 8) & 0xF
            dw2 = (
                (target_bus << 24)
                | (target_devfn << 16)
                | ((ext_reg & 0xF) << 8)
                | ((reg_num & 0x3F) << 2)
            )
            is_write = tlp_type in (TlpType.CFWR0, TlpType.CFWR1)
            header = [dw0, dw1, dw2]
            if is_write and data is not None:
                header.append(data & 0xFFFFFFFF)
            return header
        dw1 = (
            ((requester_id & 0xFFFF) << 16)
            | ((tag & 0xFF) << 8)
            | ((first_be & 0xF) << 4)
            | (last_be & 0xF)
        )
        is_64bit = tlp_type in (TlpType.MR64, TlpType.MW64)
        if is_64bit:
            dw2 = (address >> 32) & 0xFFFFFFFF
            dw3 = address & 0xFFFFFFFC
            header = [dw0, dw1, dw2, dw3]
        else:
            dw2 = address & 0xFFFFFFFC
            header = [dw0, dw1, dw2]
        is_write = tlp_type in (TlpType.MW32, TlpType.MW64)
        if is_write and data is not None:
            header.append(data & 0xFFFFFFFF)
        return header


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TBUF_ROW_DWORDS = 19
TBUF_PAYLOAD_DWORDS = 16  # DW0-DW15 = 512-bit payload; DW16-DW18 = metadata
DW0_FMT_TYPE_LEN_MASK = 0xFF0003FF  # Fmt[31:29] | Type[28:24] | Length[9:0]


# ---------------------------------------------------------------------------
# Flit-mode helpers (from UG104 PEA documentation)
# ---------------------------------------------------------------------------

def _flit_type_byte(tlp_type) -> int:
    """Compute the Flit-mode type byte: {Fmt[7:5], Type[4:0]}.

    In Gen6 Flit mode, the TLP type is encoded as a single byte
    with Fmt in bits [7:5] and Type in bits [4:0].  Per UG104,
    this byte appears at byte offset 0 (lowest byte) of the first
    DWORD in the Flit buffer.
    """
    fmt, type_code = _TLP_FMT_TYPE[tlp_type]
    return ((fmt & 0x7) << 5) | (type_code & 0x1F)


def _build_flit_search_terms(expected_header: list[int], tlp_type) -> dict:
    """Build Flit-mode search terms from a standard PCIe TLP header.

    Returns a dict with:
      - "flit_type_byte": the combined Fmt+Type byte for Flit mode
      - "distinctive_bytes": set of non-trivial bytes from the header
      - "distinctive_words": list of (word_value, field_name) tuples
    """
    flit_byte = _flit_type_byte(tlp_type)

    # Collect distinctive (non-zero, non-0xFF) bytes from all header DWORDs
    distinctive_bytes = set()
    for dw in expected_header:
        for shift in (0, 8, 16, 24):
            byte_val = (dw >> shift) & 0xFF
            if byte_val not in (0x00, 0xFF):
                distinctive_bytes.add(byte_val)

    # Collect distinctive 16-bit words (e.g., requester IDs, addresses)
    distinctive_words = []
    for i, dw in enumerate(expected_header):
        hi_word = (dw >> 16) & 0xFFFF
        lo_word = dw & 0xFFFF
        if hi_word not in (0x0000, 0xFFFF):
            distinctive_words.append((hi_word, f"DW{i}[31:16]"))
        if lo_word not in (0x0000, 0xFFFF):
            distinctive_words.append((lo_word, f"DW{i}[15:0]"))

    return {
        "flit_type_byte": flit_byte,
        "distinctive_bytes": sorted(distinctive_bytes),
        "distinctive_words": distinctive_words,
    }


def _scan_row_flit_mode(
    row_dwords: list[int],
    flit_search: dict,
    row_index: int = 0,
) -> dict:
    """Scan a buffer row for Flit-mode encoded TLP fields.

    Searches the payload area (DW0-DW15) for:
    1. Flit type byte at any byte position within each DWORD
    2. Distinctive 16-bit words from the expected TLP header
    3. Distinctive bytes from the expected TLP header

    Returns a dict with match details for diagnostics.
    """
    flit_byte = flit_search["flit_type_byte"]
    distinctive_words = flit_search["distinctive_words"]

    # Only search payload area (DW0-DW15)
    payload = row_dwords[:TBUF_PAYLOAD_DWORDS]

    # 1. Search for flit type byte in each payload DWORD
    flit_byte_hits = []
    for dw_pos, dw_val in enumerate(payload):
        for byte_pos in range(4):
            actual_byte = (dw_val >> (byte_pos * 8)) & 0xFF
            if actual_byte == flit_byte and flit_byte != 0:
                flit_byte_hits.append({
                    "dw_pos": dw_pos,
                    "byte_pos": byte_pos,
                    "dw_value": f"0x{dw_val:08X}",
                })

    # 2. Search for distinctive 16-bit words
    word_hits = []
    for dw_pos, dw_val in enumerate(payload):
        hi_word = (dw_val >> 16) & 0xFFFF
        lo_word = dw_val & 0xFFFF
        for word_val, field_name in distinctive_words:
            if hi_word == word_val:
                word_hits.append({
                    "dw_pos": dw_pos,
                    "half": "hi",
                    "value": f"0x{word_val:04X}",
                    "field": field_name,
                    "dw_value": f"0x{dw_val:08X}",
                })
            if lo_word == word_val:
                word_hits.append({
                    "dw_pos": dw_pos,
                    "half": "lo",
                    "value": f"0x{word_val:04X}",
                    "field": field_name,
                    "dw_value": f"0x{dw_val:08X}",
                })

    return {
        "row_index": row_index,
        "flit_type_byte": f"0x{flit_byte:02X}",
        "flit_byte_hits": flit_byte_hits,
        "word_hits": word_hits,
        "total_hits": len(flit_byte_hits) + len(word_hits),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class TestResult:
    """Result of a single correlation test."""

    test_id: str
    phase: int
    name: str
    status: str = "SKIP"  # PASS, FAIL, WARN, ERROR, SKIP
    expected: str = ""
    actual: str = ""
    data: dict = field(default_factory=dict)
    notes: str = ""
    duration_ms: float = 0.0


@dataclass
class DwordMatch:
    """A single DWORD match found in a buffer row."""

    row_index: int
    buffer_dw_pos: int
    header_dw_index: int
    expected_value: int
    actual_value: int
    match_type: str  # "exact", "masked", "byte_swapped"


def _byte_swap(dw: int) -> int:
    """Swap byte order within a 32-bit DWORD."""
    b = struct.pack("<I", dw & 0xFFFFFFFF)
    return struct.unpack(">I", b)[0]


def _is_row_empty(row_dwords: list[int]) -> bool:
    """Check if a buffer row is all zeros."""
    return all(dw == 0 for dw in row_dwords)


def _build_filter_hex(match_byte: int, dw_position: int) -> tuple[str, str]:
    """Build 128-char match/mask hex strings for a PTrace 512-bit filter.

    Targets a single byte at the lowest byte position [7:0] of the specified
    DWORD in the 16-DWORD filter block.

    Args:
        match_byte: The byte value to match (e.g., 0x04 for CfgRd0 flit type).
        dw_position: Which DWORD (0-15) contains the target byte.

    Returns:
        (match_hex, mask_hex) — each is a 128-character hex string.

    Encoding:
        - Each DWORD is written as 8 little-endian hex chars.
        - Mask polarity: bit=1 → don't care, bit=0 → must match.
        - match: all zeros except dw_position = match_byte & 0xFF at byte 0.
        - mask: all 0xFFFFFFFF except dw_position = 0xFFFFFF00.
    """
    match_dwords = [0x00000000] * 16
    mask_dwords = [0xFFFFFFFF] * 16

    match_dwords[dw_position] = match_byte & 0xFF
    mask_dwords[dw_position] = 0xFFFFFF00

    def _dwords_to_hex(dwords: list[int]) -> str:
        parts = []
        for dw in dwords:
            # Little-endian: least significant byte first
            b = dw.to_bytes(4, byteorder="little")
            parts.append(b.hex())
        return "".join(parts)

    return _dwords_to_hex(match_dwords), _dwords_to_hex(mask_dwords)


def _scan_row_for_header(
    row_dwords: list[int],
    expected_header: list[int],
    row_index: int = 0,
) -> list[DwordMatch]:
    """Scan a buffer row for expected header DWORDs using 3 strategies.

    Returns all matches found across exact, masked, and byte-swapped strategies.
    """
    matches = []

    for buf_pos in range(len(row_dwords)):
        buf_dw = row_dwords[buf_pos]

        for hdr_idx, exp_dw in enumerate(expected_header):
            # Strategy 1: Exact match
            if buf_dw == exp_dw and exp_dw != 0:
                matches.append(DwordMatch(
                    row_index=row_index,
                    buffer_dw_pos=buf_pos,
                    header_dw_index=hdr_idx,
                    expected_value=exp_dw,
                    actual_value=buf_dw,
                    match_type="exact",
                ))

            # Strategy 2: Masked match (DW0 only — Fmt/Type/Length bits)
            if hdr_idx == 0:
                if (buf_dw & DW0_FMT_TYPE_LEN_MASK) == (exp_dw & DW0_FMT_TYPE_LEN_MASK):
                    if (exp_dw & DW0_FMT_TYPE_LEN_MASK) != 0:
                        # Only add if not already found as exact
                        if buf_dw != exp_dw:
                            matches.append(DwordMatch(
                                row_index=row_index,
                                buffer_dw_pos=buf_pos,
                                header_dw_index=hdr_idx,
                                expected_value=exp_dw,
                                actual_value=buf_dw,
                                match_type="masked",
                            ))

            # Strategy 3: Byte-swapped match
            swapped = _byte_swap(exp_dw)
            if buf_dw == swapped and swapped != 0 and swapped != exp_dw:
                matches.append(DwordMatch(
                    row_index=row_index,
                    buffer_dw_pos=buf_pos,
                    header_dw_index=hdr_idx,
                    expected_value=exp_dw,
                    actual_value=buf_dw,
                    match_type="byte_swapped",
                ))

    return matches


def _score_row(
    row_dwords: list[int],
    expected_header: list[int],
    row_index: int = 0,
) -> tuple[int, int, str, list[DwordMatch]]:
    """Score a row for best consecutive header DWORD match.

    Returns (score, start_buffer_pos, match_type, matches).
    Score is the number of consecutive header DWORDs found.
    """
    matches = _scan_row_for_header(row_dwords, expected_header, row_index)
    if not matches:
        return 0, -1, "", []

    # Group matches by match_type and check for consecutive sequences
    best_score = 0
    best_start = -1
    best_type = ""
    best_matches: list[DwordMatch] = []

    # Priority tiers: each includes all higher-priority match types.
    # The reported match_type reflects the weakest match in the sequence.
    tiers = {
        "exact": {"exact"},
        "masked": {"exact", "masked"},
        "byte_swapped": {"exact", "masked", "byte_swapped"},
    }

    for match_type, allowed_types in tiers.items():
        typed_matches = [m for m in matches if m.match_type in allowed_types]

        # For each possible starting buffer position, check consecutive header DWs
        for start_pos in range(TBUF_ROW_DWORDS):
            consecutive = 0
            consec_matches = []
            for hdr_idx in range(len(expected_header)):
                buf_pos = start_pos + hdr_idx
                if buf_pos >= TBUF_ROW_DWORDS:
                    break
                found = False
                for m in typed_matches:
                    if m.buffer_dw_pos == buf_pos and m.header_dw_index == hdr_idx:
                        consecutive += 1
                        consec_matches.append(m)
                        found = True
                        break
                if not found:
                    break
            if consecutive > best_score:
                best_score = consecutive
                best_start = start_pos
                best_type = match_type
                best_matches = list(consec_matches)

    return best_score, best_start, best_type, best_matches


# ---------------------------------------------------------------------------
# Correlator
# ---------------------------------------------------------------------------


class CaptureCorrelator:
    """Sends known TLPs, captures with PTrace, and correlates buffer layout."""

    def __init__(
        self,
        base_url: str,
        device_id: str | None,
        port_number: int | None,
        output_dir: Path,
        phases: set[int],
        wait_ms: int,
        trace_point: int = 0,
        data_cap: bool = False,
    ):
        self.base_url = base_url.rstrip("/")
        self.api = f"{self.base_url}/api"
        self.device_id = device_id
        self.port_number = port_number
        self.output_dir = output_dir
        self.phases = phases
        self.wait_ms = wait_ms
        self.trace_point = trace_point
        self.data_cap = data_cap
        self.results: list[TestResult] = []
        self.raw_dir = output_dir / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.device_info: dict = {}

        # Correlation data collected across all tests
        self.correlations: list[dict] = []
        # Per-capture DW17/DW18 value lists (one list per capture session)
        self.per_capture_dw17: list[list[int]] = []
        self.per_capture_dw18: list[list[int]] = []
        self.session = requests.Session()
        self._cached_consensus: dict = {}

    # -- HTTP helpers --

    def _get(self, path: str, params: dict | None = None) -> dict | list:
        url = f"{self.api}{path}"
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict | None = None) -> dict:
        url = f"{self.api}{path}"
        resp = self.session.post(url, json=body or {}, timeout=60)
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

    # -- Capture helpers --

    def _capture_and_send(
        self,
        tlp_configs: list[dict],
        trace_point: int | None = None,
        data_cap: bool | None = None,
    ) -> dict:
        """Send TLPs via capture-and-send endpoint, return full response.

        The capture-and-send endpoint uses server-side PTrace defaults (idle/nop
        filtering, manual trigger, trace_point=0).  To override capture settings,
        we first call the full-configure API then fall through to the composite
        endpoint which will re-configure — so instead we configure + start + send
        + trigger + read manually when custom settings are needed.
        """
        tp = trace_point if trace_point is not None else self.trace_point
        dc = data_cap if data_cap is not None else self.data_cap

        # If non-default capture settings requested, do manual orchestration
        if tp != 0 or dc:
            return self._capture_and_send_custom(tlp_configs, tp, dc)

        body = {
            "port_number": self.port_number,
            "ptrace_direction": "egress",
            "exerciser": {
                "port_number": self.port_number,
                "tlps": tlp_configs,
                "infinite_loop": False,
                "max_outstanding_np": 8,
            },
            "read_buffer": True,
            "post_trigger_wait_ms": self.wait_ms,
        }
        return self._post(
            f"/devices/{self.device_id}/exerciser/capture-and-send", body
        )

    def _capture_and_send_custom(
        self,
        tlp_configs: list[dict],
        trace_point: int,
        data_cap: bool,
    ) -> dict:
        """Manual orchestration: configure PTrace with custom settings, then
        start capture, send TLPs, trigger, and read buffer.
        """
        dev = self.device_id
        port = self.port_number

        # 1. Configure PTrace with custom capture settings
        cfg_body = {
            "port_number": port,
            "direction": "egress",
            "capture": {
                "direction": "egress",
                "port_number": port,
                "trace_point": trace_point,
                "idle_filt": True,
                "nop_filt": True,
                "data_cap": data_cap,
            },
            "trigger": {"trigger_src": 0},  # manual trigger
            "post_trigger": {},
        }
        self._post(f"/devices/{dev}/ptrace/configure", cfg_body)

        try:
            # 2. Start capture
            self._post(
                f"/devices/{dev}/ptrace/start",
                {"port_number": port, "direction": "egress"},
            )

            # 3. Send TLPs
            send_body = {
                "port_number": port,
                "tlps": tlp_configs,
                "infinite_loop": False,
                "max_outstanding_np": 8,
            }
            self._post(f"/devices/{dev}/exerciser/send", send_body)

            # 4. Wait then manual trigger and stop
            time.sleep(self.wait_ms / 1000.0)
            self._post(
                f"/devices/{dev}/ptrace/manual-trigger",
                {"port_number": port, "direction": "egress"},
            )
            # Brief settle time after trigger before reading buffer
            time.sleep(0.01)
            self._post(
                f"/devices/{dev}/ptrace/stop",
                {"port_number": port, "direction": "egress"},
            )

            # 5. Read results
            exer_status = self._get(
                f"/devices/{dev}/exerciser/status",
                {"port_number": port},
            )
            ptrace_status = self._get(
                f"/devices/{dev}/ptrace/status",
                {"port_number": port, "direction": "egress"},
            )
            ptrace_buffer = self._get(
                f"/devices/{dev}/ptrace/buffer",
                {"port_number": port, "direction": "egress", "max_rows": 256},
            )

            return {
                "exerciser_status": exer_status,
                "ptrace_status": ptrace_status,
                "ptrace_buffer": ptrace_buffer,
            }
        finally:
            # Always attempt to stop exerciser to prevent hardware leak
            try:
                self._post(
                    f"/devices/{dev}/exerciser/stop", {"port_number": port}
                )
            except Exception:
                pass

    def _capture_with_filter(
        self,
        tlp_configs: list[dict],
        filter_match_hex: str,
        filter_mask_hex: str,
        trace_point: int = 0,
        data_cap: bool = False,
    ) -> dict:
        """Capture with PTrace filter enabled.

        Configures PTrace with filter_en=True, writes filter match/mask data
        to filter index 0, then runs the capture-send-trigger-read sequence.

        Args:
            tlp_configs: TLP configurations to send via exerciser.
            filter_match_hex: 128-char hex string for filter match block.
            filter_mask_hex: 128-char hex string for filter mask block.
            trace_point: PTrace trace point (0=DLLP/TLP, 1=Unscrambler).
            data_cap: Enable data capture mode.

        Returns:
            Dict with ptrace_status, ptrace_buffer, and exerciser_status.
        """
        dev = self.device_id
        port = self.port_number

        # 1. Configure PTrace with filter enabled
        cfg_body: dict[str, Any] = {
            "port_number": port,
            "direction": "egress",
            "capture": {
                "direction": "egress",
                "port_number": port,
                "trace_point": trace_point,
                "idle_filt": True,
                "nop_filt": True,
                "data_cap": data_cap,
                "filter_en": True,
            },
            "trigger": {"trigger_src": 0},  # manual trigger
            "post_trigger": {},
            "filter_control": {
                "filter_match_sel0": 1,  # MATCH_DW1 per UG104
            },
        }
        try:
            self._post(f"/devices/{dev}/ptrace/configure", cfg_body)
        except requests.HTTPError as exc:
            if exc.response.status_code == 501:
                # B0 doesn't support filter_control — retry without it
                print("      (filter_control not supported, retrying without it)")
                del cfg_body["filter_control"]
                self._post(f"/devices/{dev}/ptrace/configure", cfg_body)
            else:
                raise

        try:
            # 2. Write filter match/mask data
            filter_body = {
                "filter_idx": 0,
                "match_hex": filter_match_hex,
                "mask_hex": filter_mask_hex,
            }
            self._post(
                f"/devices/{dev}/ptrace/filter"
                f"?port_number={port}&direction=egress",
                filter_body,
            )

            # 3. Start capture
            self._post(
                f"/devices/{dev}/ptrace/start",
                {"port_number": port, "direction": "egress"},
            )

            # 4. Send TLPs
            send_body = {
                "port_number": port,
                "tlps": tlp_configs,
                "infinite_loop": False,
                "max_outstanding_np": 8,
            }
            self._post(f"/devices/{dev}/exerciser/send", send_body)

            # 5. Wait then trigger and stop
            time.sleep(self.wait_ms / 1000.0)
            self._post(
                f"/devices/{dev}/ptrace/manual-trigger",
                {"port_number": port, "direction": "egress"},
            )
            time.sleep(0.01)
            self._post(
                f"/devices/{dev}/ptrace/stop",
                {"port_number": port, "direction": "egress"},
            )

            # 6. Read results
            ptrace_status = self._get(
                f"/devices/{dev}/ptrace/status",
                {"port_number": port, "direction": "egress"},
            )
            ptrace_buffer = self._get(
                f"/devices/{dev}/ptrace/buffer",
                {"port_number": port, "direction": "egress", "max_rows": 256},
            )

            return {
                "ptrace_status": ptrace_status,
                "ptrace_buffer": ptrace_buffer,
            }
        finally:
            # Always stop exerciser to prevent hardware leak
            try:
                self._post(
                    f"/devices/{dev}/exerciser/stop", {"port_number": port}
                )
            except Exception:
                pass

    def _extract_rows(self, resp: dict) -> list[tuple[int, list[int]]]:
        """Extract non-empty (row_index, dwords) pairs from capture response."""
        buffer = resp.get("ptrace_buffer") or {}
        rows = buffer.get("rows", [])
        result = []
        for row in rows:
            dwords = row.get("dwords", [])
            if len(dwords) >= TBUF_ROW_DWORDS and not _is_row_empty(dwords):
                result.append((row.get("row_index", 0), dwords))
        return result

    def _collect_dw17_dw18(self, rows: list[tuple[int, list[int]]]) -> None:
        """Collect DW17 and DW18 values from non-empty rows (per capture)."""
        capture_dw17 = []
        capture_dw18 = []
        for _idx, dwords in rows:
            if len(dwords) >= TBUF_ROW_DWORDS:
                capture_dw17.append(dwords[17])
                capture_dw18.append(dwords[18])
        self.per_capture_dw17.append(capture_dw17)
        self.per_capture_dw18.append(capture_dw18)

    def _dump_sample_rows(
        self,
        rows: list[tuple[int, list[int]]],
        max_rows: int = 10,
    ) -> list[dict]:
        """Dump sample non-empty buffer rows as hex for human inspection.

        Returns list of dicts with row_index and per-DW hex values.
        """
        samples = []
        for row_idx, dwords in rows[:max_rows]:
            # Separate payload (DW0-DW15) from metadata (DW16-DW18)
            payload = dwords[:TBUF_PAYLOAD_DWORDS]
            metadata = dwords[TBUF_PAYLOAD_DWORDS:]
            # Find non-zero DW positions in payload
            nonzero_payload = [
                (i, f"0x{dw:08X}") for i, dw in enumerate(payload) if dw != 0
            ]
            samples.append({
                "row_index": row_idx,
                "dwords_hex": [f"0x{dw:08X}" for dw in dwords],
                "payload_hex": [f"0x{dw:08X}" for dw in payload],
                "metadata_hex": [f"0x{dw:08X}" for dw in metadata],
                "nonzero_payload_dws": nonzero_payload,
            })
        return samples

    def _correlate_test(
        self,
        test_id: str,
        tlp_type_str: str,
        expected_header: list[int],
        rows: list[tuple[int, list[int]]],
        tlp_type=None,
    ) -> dict:
        """Correlate expected header DWORDs against captured buffer rows.

        Performs both standard PCIe header matching and Flit-mode analysis.
        Returns a correlation record dict.
        """
        best_row_idx = -1
        best_score = 0
        best_start = -1
        best_type = ""
        best_matches: list[DwordMatch] = []
        all_row_scores = []

        for row_idx, dwords in rows:
            score, start, mtype, matches = _score_row(dwords, expected_header, row_idx)
            all_row_scores.append({
                "row_index": row_idx,
                "score": score,
                "start_pos": start,
                "match_type": mtype,
            })
            if score > best_score:
                best_score = score
                best_row_idx = row_idx
                best_start = start
                best_type = mtype
                best_matches = matches

        # Also record all individual DWORD matches across all rows
        all_matches = []
        for row_idx, dwords in rows:
            row_matches = _scan_row_for_header(dwords, expected_header, row_idx)
            all_matches.extend(row_matches)

        # --- Flit-mode analysis ---
        flit_analysis = {}
        if tlp_type is not None:
            flit_search = _build_flit_search_terms(expected_header, tlp_type)
            flit_analysis["search_terms"] = {
                "flit_type_byte": f"0x{flit_search['flit_type_byte']:02X}",
                "distinctive_bytes": [f"0x{b:02X}" for b in flit_search["distinctive_bytes"]],
                "distinctive_words": [
                    {"value": f"0x{w:04X}", "field": f}
                    for w, f in flit_search["distinctive_words"]
                ],
            }
            # Scan rows for Flit-mode matches (limit to first 50 rows for perf)
            flit_hits_by_row = []
            total_flit_hits = 0
            best_flit_row = None
            best_flit_hit_count = 0
            for row_idx, dwords in rows[:50]:
                result = _scan_row_flit_mode(dwords, flit_search, row_idx)
                if result["total_hits"] > 0:
                    flit_hits_by_row.append(result)
                    total_flit_hits += result["total_hits"]
                    if result["total_hits"] > best_flit_hit_count:
                        best_flit_hit_count = result["total_hits"]
                        best_flit_row = result

            flit_analysis["total_flit_hits"] = total_flit_hits
            flit_analysis["rows_with_hits"] = len(flit_hits_by_row)
            flit_analysis["best_row"] = best_flit_row
            # Include up to 5 rows with hits for inspection
            flit_analysis["sample_hit_rows"] = flit_hits_by_row[:5]

        # --- Raw buffer sample ---
        sample_rows = self._dump_sample_rows(rows, max_rows=10)

        correlation = {
            "test_id": test_id,
            "tlp_type": tlp_type_str,
            "expected_header_dws": [f"0x{dw:08X}" for dw in expected_header],
            "num_expected_dws": len(expected_header),
            "total_non_empty_rows": len(rows),
            "best_match": {
                "row_index": best_row_idx,
                "score": best_score,
                "header_dws_matched": best_score,
                "total_header_dws": len(expected_header),
                "buffer_start_pos": best_start,
                "match_type": best_type,
                "matches": [
                    {
                        "buffer_dw": m.buffer_dw_pos,
                        "header_dw": m.header_dw_index,
                        "expected": f"0x{m.expected_value:08X}",
                        "actual": f"0x{m.actual_value:08X}",
                        "type": m.match_type,
                    }
                    for m in best_matches
                ],
            },
            "flit_analysis": flit_analysis,
            "sample_rows": sample_rows,
            "all_row_scores": all_row_scores,
            "all_individual_matches": [
                {
                    "row": m.row_index,
                    "buf_dw": m.buffer_dw_pos,
                    "hdr_dw": m.header_dw_index,
                    "expected": f"0x{m.expected_value:08X}",
                    "actual": f"0x{m.actual_value:08X}",
                    "type": m.match_type,
                }
                for m in all_matches
            ],
        }
        self.correlations.append(correlation)
        return correlation

    # -----------------------------------------------------------------------
    # Phase 0: Discovery
    # -----------------------------------------------------------------------

    def discover(self) -> bool:
        print("\n=== Phase 0: Discovery ===")

        try:
            self.session.get(f"{self.base_url}/api/devices", timeout=5)
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

        print(f"  Post-trigger wait: {self.wait_ms}ms")
        print(f"  Trace point: {self.trace_point}")
        print(f"  Data capture: {self.data_cap}")
        print("  Discovery complete.")
        return True

    # -----------------------------------------------------------------------
    # Phase 1: 32-bit Memory TLPs
    # -----------------------------------------------------------------------

    def phase1_mem32(self):
        print("\n=== Phase 1: 32-bit Memory TLPs ===")

        # 1.1 — MR32 with distinctive address/requester/tag
        def test_1_1(r: TestResult):
            expected = build_tlp_header(
                TlpType.MR32,
                address=0xAAAA0000,
                requester_id=0x1111,
                tag=0xAA,
                length_dw=1,
            )
            r.data["expected_header"] = [f"0x{dw:08X}" for dw in expected]

            tlp_cfg = {
                "tlp_type": "mr32",
                "address": 0xAAAA0000,
                "requester_id": 0x1111,
                "tag": 0xAA,
                "length_dw": 1,
            }
            resp = self._capture_and_send([tlp_cfg])
            rows = self._extract_rows(resp)
            self._collect_dw17_dw18(rows)

            r.data["total_rows"] = len(rows)
            r.data["ptrace_triggered"] = (
                resp.get("ptrace_status") or {}
            ).get("triggered")

            corr = self._correlate_test("1.1", "MR32", expected, rows, TlpType.MR32)
            r.data["correlation"] = corr

            r.expected = f"Find {len(expected)} header DWs in buffer"
            score = corr["best_match"]["score"]
            flit_hits = corr.get("flit_analysis", {}).get("total_flit_hits", 0)
            r.actual = (
                f"score={score}/{len(expected)}, "
                f"buf_pos={corr['best_match']['buffer_start_pos']}, "
                f"type={corr['best_match']['match_type']}, "
                f"flit_hits={flit_hits}, "
                f"rows={len(rows)}"
            )
            r.status = "PASS" if score >= 2 else ("WARN" if score >= 1 else "FAIL")
            if len(rows) == 0:
                r.status = "WARN"
                r.notes = "No non-empty rows captured"

        self._run_test("1.1_mr32", 1, "MR32 addr=0xAAAA0000 reqid=0x1111", test_1_1)

        # 1.2 — MW32 with distinctive address and data
        def test_1_2(r: TestResult):
            expected = build_tlp_header(
                TlpType.MW32,
                address=0xBBBB0000,
                requester_id=0x2222,
                tag=0xBB,
                length_dw=1,
                data=0xDEADBEEF,
            )
            r.data["expected_header"] = [f"0x{dw:08X}" for dw in expected]

            tlp_cfg = {
                "tlp_type": "mw32",
                "address": 0xBBBB0000,
                "requester_id": 0x2222,
                "tag": 0xBB,
                "length_dw": 1,
                "data": "DEADBEEF",
            }
            resp = self._capture_and_send([tlp_cfg])
            rows = self._extract_rows(resp)
            self._collect_dw17_dw18(rows)

            r.data["total_rows"] = len(rows)
            corr = self._correlate_test("1.2", "MW32", expected, rows, TlpType.MW32)
            r.data["correlation"] = corr

            r.expected = f"Find {len(expected)} header DWs (incl data=0xDEADBEEF)"
            score = corr["best_match"]["score"]
            flit_hits = corr.get("flit_analysis", {}).get("total_flit_hits", 0)
            r.actual = (
                f"score={score}/{len(expected)}, "
                f"flit_hits={flit_hits}, "
                f"buf_pos={corr['best_match']['buffer_start_pos']}"
            )
            r.status = "PASS" if score >= 2 else ("WARN" if score >= 1 else "FAIL")
            if len(rows) == 0:
                r.status = "WARN"
                r.notes = "No non-empty rows captured"

        self._run_test("1.2_mw32", 1, "MW32 addr=0xBBBB0000 data=0xDEADBEEF", test_1_2)

    # -----------------------------------------------------------------------
    # Phase 2: 64-bit Memory TLPs
    # -----------------------------------------------------------------------

    def phase2_mem64(self):
        print("\n=== Phase 2: 64-bit Memory TLPs ===")

        # 2.1 — MR64
        def test_2_1(r: TestResult):
            expected = build_tlp_header(
                TlpType.MR64,
                address=0xCCCCC0000,
                requester_id=0x3333,
                tag=0xCC,
                length_dw=1,
            )
            r.data["expected_header"] = [f"0x{dw:08X}" for dw in expected]

            tlp_cfg = {
                "tlp_type": "mr64",
                "address": 0xCCCCC0000,
                "requester_id": 0x3333,
                "tag": 0xCC,
                "length_dw": 1,
            }
            resp = self._capture_and_send([tlp_cfg])
            rows = self._extract_rows(resp)
            self._collect_dw17_dw18(rows)

            r.data["total_rows"] = len(rows)
            corr = self._correlate_test("2.1", "MR64", expected, rows, TlpType.MR64)
            r.data["correlation"] = corr

            score = corr["best_match"]["score"]
            flit_hits = corr.get("flit_analysis", {}).get("total_flit_hits", 0)
            r.expected = f"Find {len(expected)} header DWs in buffer"
            r.actual = (
                f"score={score}/{len(expected)}, "
                f"flit_hits={flit_hits}, "
                f"buf_pos={corr['best_match']['buffer_start_pos']}"
            )
            r.status = "PASS" if score >= 2 else ("WARN" if score >= 1 else "FAIL")
            if len(rows) == 0:
                r.status = "WARN"
                r.notes = "No non-empty rows captured"

        self._run_test("2.1_mr64", 2, "MR64 addr=0xCCCCC0000 reqid=0x3333", test_2_1)

        # 2.2 — MW64
        def test_2_2(r: TestResult):
            expected = build_tlp_header(
                TlpType.MW64,
                address=0xDDDDD0000,
                requester_id=0x4444,
                tag=0xDD,
                length_dw=1,
                data=0xCAFEBABE,
            )
            r.data["expected_header"] = [f"0x{dw:08X}" for dw in expected]

            tlp_cfg = {
                "tlp_type": "mw64",
                "address": 0xDDDDD0000,
                "requester_id": 0x4444,
                "tag": 0xDD,
                "length_dw": 1,
                "data": "CAFEBABE",
            }
            resp = self._capture_and_send([tlp_cfg])
            rows = self._extract_rows(resp)
            self._collect_dw17_dw18(rows)

            r.data["total_rows"] = len(rows)
            corr = self._correlate_test("2.2", "MW64", expected, rows, TlpType.MW64)
            r.data["correlation"] = corr

            score = corr["best_match"]["score"]
            flit_hits = corr.get("flit_analysis", {}).get("total_flit_hits", 0)
            r.expected = f"Find {len(expected)} header DWs (incl data=0xCAFEBABE)"
            r.actual = (
                f"score={score}/{len(expected)}, "
                f"flit_hits={flit_hits}, "
                f"buf_pos={corr['best_match']['buffer_start_pos']}"
            )
            r.status = "PASS" if score >= 2 else ("WARN" if score >= 1 else "FAIL")
            if len(rows) == 0:
                r.status = "WARN"
                r.notes = "No non-empty rows captured"

        self._run_test("2.2_mw64", 2, "MW64 addr=0xDDDDD0000 data=0xCAFEBABE", test_2_2)

    # -----------------------------------------------------------------------
    # Phase 3: Config TLPs
    # -----------------------------------------------------------------------

    def phase3_config(self):
        print("\n=== Phase 3: Config TLPs ===")

        # 3.1 — CfgRd0
        def test_3_1(r: TestResult):
            expected = build_tlp_header(
                TlpType.CFRD0,
                target_id=0x0500,
                requester_id=0x5555,
                tag=0x55,
                address=0,
                length_dw=1,
            )
            r.data["expected_header"] = [f"0x{dw:08X}" for dw in expected]

            tlp_cfg = {
                "tlp_type": "cfrd0",
                "target_id": 0x0500,
                "requester_id": 0x5555,
                "tag": 0x55,
                "length_dw": 1,
            }
            resp = self._capture_and_send([tlp_cfg])
            rows = self._extract_rows(resp)
            self._collect_dw17_dw18(rows)

            r.data["total_rows"] = len(rows)
            corr = self._correlate_test("3.1", "CfgRd0", expected, rows, TlpType.CFRD0)
            r.data["correlation"] = corr

            score = corr["best_match"]["score"]
            flit_hits = corr.get("flit_analysis", {}).get("total_flit_hits", 0)
            r.expected = f"Find {len(expected)} header DWs"
            r.actual = (
                f"score={score}/{len(expected)}, "
                f"flit_hits={flit_hits}, "
                f"buf_pos={corr['best_match']['buffer_start_pos']}"
            )
            r.status = "PASS" if score >= 2 else ("WARN" if score >= 1 else "FAIL")
            if len(rows) == 0:
                r.status = "WARN"
                r.notes = "No non-empty rows captured"

        self._run_test("3.1_cfgrd0", 3, "CfgRd0 target=0x0500 reqid=0x5555", test_3_1)

        # 3.2 — CfgWr0
        def test_3_2(r: TestResult):
            expected = build_tlp_header(
                TlpType.CFWR0,
                target_id=0x0600,
                requester_id=0x6666,
                tag=0x66,
                address=0x04,
                length_dw=1,
                data=0x12345678,
            )
            r.data["expected_header"] = [f"0x{dw:08X}" for dw in expected]

            tlp_cfg = {
                "tlp_type": "cfwr0",
                "target_id": 0x0600,
                "requester_id": 0x6666,
                "tag": 0x66,
                "address": 0x04,
                "length_dw": 1,
                "data": "12345678",
            }
            resp = self._capture_and_send([tlp_cfg])
            rows = self._extract_rows(resp)
            self._collect_dw17_dw18(rows)

            r.data["total_rows"] = len(rows)
            corr = self._correlate_test("3.2", "CfgWr0", expected, rows, TlpType.CFWR0)
            r.data["correlation"] = corr

            score = corr["best_match"]["score"]
            flit_hits = corr.get("flit_analysis", {}).get("total_flit_hits", 0)
            r.expected = f"Find {len(expected)} header DWs (incl data=0x12345678)"
            r.actual = (
                f"score={score}/{len(expected)}, "
                f"flit_hits={flit_hits}, "
                f"buf_pos={corr['best_match']['buffer_start_pos']}"
            )
            r.status = "PASS" if score >= 2 else ("WARN" if score >= 1 else "FAIL")
            if len(rows) == 0:
                r.status = "WARN"
                r.notes = "No non-empty rows captured"

        self._run_test("3.2_cfgwr0", 3, "CfgWr0 target=0x0600 data=0x12345678", test_3_2)

    # -----------------------------------------------------------------------
    # Phase 4: Message TLPs
    # -----------------------------------------------------------------------

    def phase4_messages(self):
        print("\n=== Phase 4: Message TLPs ===")

        # 4.1 — ERR_COR
        def test_4_1(r: TestResult):
            expected = build_tlp_header(
                TlpType.ERR_COR,
                requester_id=0x7777,
                tag=0x77,
            )
            r.data["expected_header"] = [f"0x{dw:08X}" for dw in expected]

            tlp_cfg = {
                "tlp_type": "ERRCor",
                "requester_id": 0x7777,
                "tag": 0x77,
            }
            resp = self._capture_and_send([tlp_cfg])
            rows = self._extract_rows(resp)
            self._collect_dw17_dw18(rows)

            r.data["total_rows"] = len(rows)
            corr = self._correlate_test(
                "4.1", "ERR_COR", expected, rows, TlpType.ERR_COR
            )
            r.data["correlation"] = corr

            score = corr["best_match"]["score"]
            flit_hits = corr.get("flit_analysis", {}).get("total_flit_hits", 0)
            r.expected = f"Find {len(expected)} header DWs (msgcode=0x30)"
            r.actual = (
                f"score={score}/{len(expected)}, "
                f"flit_hits={flit_hits}, "
                f"buf_pos={corr['best_match']['buffer_start_pos']}"
            )
            r.status = "PASS" if score >= 2 else ("WARN" if score >= 1 else "FAIL")
            if len(rows) == 0:
                r.status = "WARN"
                r.notes = "No non-empty rows captured"

        self._run_test("4.1_err_cor", 4, "ERR_COR reqid=0x7777 msgcode=0x30", test_4_1)

        # 4.2 — PME_ACK
        def test_4_2(r: TestResult):
            expected = build_tlp_header(
                TlpType.PME_ACK,
                requester_id=0x8888,
                tag=0x88,
            )
            r.data["expected_header"] = [f"0x{dw:08X}" for dw in expected]

            tlp_cfg = {
                "tlp_type": "PMEAck",
                "requester_id": 0x8888,
                "tag": 0x88,
            }
            resp = self._capture_and_send([tlp_cfg])
            rows = self._extract_rows(resp)
            self._collect_dw17_dw18(rows)

            r.data["total_rows"] = len(rows)
            corr = self._correlate_test(
                "4.2", "PME_ACK", expected, rows, TlpType.PME_ACK
            )
            r.data["correlation"] = corr

            score = corr["best_match"]["score"]
            flit_hits = corr.get("flit_analysis", {}).get("total_flit_hits", 0)
            r.expected = f"Find {len(expected)} header DWs (msgcode=0x1B)"
            r.actual = (
                f"score={score}/{len(expected)}, "
                f"flit_hits={flit_hits}, "
                f"buf_pos={corr['best_match']['buffer_start_pos']}"
            )
            r.status = "PASS" if score >= 2 else ("WARN" if score >= 1 else "FAIL")
            if len(rows) == 0:
                r.status = "WARN"
                r.notes = "No non-empty rows captured"

        self._run_test("4.2_pme_ack", 4, "PME_ACK reqid=0x8888 msgcode=0x1B", test_4_2)

        # 4.3 — ERR_FATAL
        def test_4_3(r: TestResult):
            expected = build_tlp_header(
                TlpType.ERR_FATAL,
                requester_id=0x9999,
                tag=0x99,
            )
            r.data["expected_header"] = [f"0x{dw:08X}" for dw in expected]

            tlp_cfg = {
                "tlp_type": "ERRF",
                "requester_id": 0x9999,
                "tag": 0x99,
            }
            resp = self._capture_and_send([tlp_cfg])
            rows = self._extract_rows(resp)
            self._collect_dw17_dw18(rows)

            r.data["total_rows"] = len(rows)
            corr = self._correlate_test(
                "4.3", "ERR_FATAL", expected, rows, TlpType.ERR_FATAL
            )
            r.data["correlation"] = corr

            score = corr["best_match"]["score"]
            flit_hits = corr.get("flit_analysis", {}).get("total_flit_hits", 0)
            r.expected = f"Find {len(expected)} header DWs (msgcode=0x33)"
            r.actual = (
                f"score={score}/{len(expected)}, "
                f"flit_hits={flit_hits}, "
                f"buf_pos={corr['best_match']['buffer_start_pos']}"
            )
            r.status = "PASS" if score >= 2 else ("WARN" if score >= 1 else "FAIL")
            if len(rows) == 0:
                r.status = "WARN"
                r.notes = "No non-empty rows captured"

        self._run_test("4.3_err_fatal", 4, "ERR_FATAL reqid=0x9999 msgcode=0x33", test_4_3)

    # -----------------------------------------------------------------------
    # Phase 5: Consensus Mapping & DW17/DW18 Analysis
    # -----------------------------------------------------------------------

    def phase5_consensus(self):
        print("\n=== Phase 5: Consensus Mapping ===")

        # 5.1 — DW17/DW18 analysis
        def test_5_1(r: TestResult):
            dw17_analysis = self._analyze_dw17()
            dw18_analysis = self._analyze_dw18()
            r.data = {
                "dw17_analysis": dw17_analysis,
                "dw18_analysis": dw18_analysis,
            }
            r.expected = "DW17 monotonic (timestamp), DW18 top byte=0x00"
            r.actual = (
                f"DW17: monotonic={dw17_analysis.get('monotonic_per_capture')}, "
                f"count={dw17_analysis.get('count')}; "
                f"DW18: top_byte_zero={dw18_analysis.get('top_byte_always_zero')}"
            )
            r.status = "PASS" if dw17_analysis.get("count", 0) > 0 else "WARN"
            if dw17_analysis.get("count", 0) == 0:
                r.notes = "No DW17/DW18 values collected (no non-empty rows)"

        self._run_test("5.1_dw17_dw18", 5, "DW17/DW18 timestamp analysis", test_5_1)

        # 5.2 — Consensus mapping
        def test_5_2(r: TestResult):
            mapping = self._build_consensus_mapping()
            r.data = {"consensus_mapping": mapping}
            r.expected = "Consistent buffer offset for TLP headers across tests"
            confidence = mapping.get("confidence", "none")
            consensus_pos = mapping.get("consensus_start_pos", -1)
            r.actual = (
                f"consensus_start_pos={consensus_pos}, "
                f"confidence={confidence}, "
                f"tests_agreeing={mapping.get('tests_agreeing', 0)}/"
                f"{mapping.get('total_tests_with_matches', 0)}"
            )
            r.status = (
                "PASS" if confidence == "high"
                else ("WARN" if confidence in ("medium", "low") else "FAIL")
            )
            if confidence == "none":
                r.notes = "No matches found across any test — buffer may not contain TLP headers"

        self._run_test("5.2_consensus", 5, "Cross-test consensus mapping", test_5_2)

    def _analyze_dw17(self) -> dict:
        """Analyze DW17 values for timestamp characteristics (per capture)."""
        all_values = [v for capture in self.per_capture_dw17 for v in capture]
        if not all_values:
            return {"count": 0, "monotonic_per_capture": None, "deltas": []}

        # Check monotonicity within each capture (not across captures)
        per_capture_monotonic = []
        all_deltas = []
        for capture in self.per_capture_dw17:
            if len(capture) >= 2:
                mono = all(capture[i] <= capture[i + 1] for i in range(len(capture) - 1))
                per_capture_monotonic.append(mono)
                # Use modular arithmetic for 32-bit unsigned deltas
                for i in range(len(capture) - 1):
                    all_deltas.append((capture[i + 1] - capture[i]) & 0xFFFFFFFF)

        all_monotonic = all(per_capture_monotonic) if per_capture_monotonic else None
        unique = len(set(all_values))

        return {
            "count": len(all_values),
            "captures_analyzed": len(self.per_capture_dw17),
            "unique_values": unique,
            "monotonic_per_capture": all_monotonic,
            "per_capture_monotonic": per_capture_monotonic,
            "min": f"0x{min(all_values):08X}",
            "max": f"0x{max(all_values):08X}",
            "deltas": [f"0x{d:08X}" for d in all_deltas[:20]],
            "avg_delta": sum(all_deltas) / len(all_deltas) if all_deltas else 0,
            "sample_values": [f"0x{v:08X}" for v in all_values[:20]],
        }

    def _analyze_dw18(self) -> dict:
        """Analyze DW18 values for reserved-bit characteristics."""
        all_values = [v for capture in self.per_capture_dw18 for v in capture]
        if not all_values:
            return {"count": 0, "top_byte_always_zero": None}

        top_bytes = [(v >> 24) & 0xFF for v in all_values]
        top_byte_zero = all(b == 0 for b in top_bytes)
        unique_top = set(top_bytes)

        return {
            "count": len(all_values),
            "top_byte_always_zero": top_byte_zero,
            "unique_top_bytes": [f"0x{b:02X}" for b in sorted(unique_top)],
            "sample_values": [f"0x{v:08X}" for v in all_values[:20]],
        }

    def _build_consensus_mapping(self) -> dict:
        """Cross-reference all correlation results to find consensus buffer layout."""
        # Collect (start_pos, match_type) from tests with score >= 2
        position_votes: dict[int, list[str]] = {}
        tests_with_matches = 0

        for corr in self.correlations:
            best = corr["best_match"]
            if best["score"] >= 2:
                tests_with_matches += 1
                pos = best["buffer_start_pos"]
                if pos not in position_votes:
                    position_votes[pos] = []
                position_votes[pos].append(corr["test_id"])

        if not position_votes:
            return {
                "consensus_start_pos": -1,
                "confidence": "none",
                "tests_agreeing": 0,
                "total_tests_with_matches": tests_with_matches,
                "mapping": {},
                "all_votes": {},
            }

        # Find the most-voted position
        best_pos = max(position_votes, key=lambda p: len(position_votes[p]))
        agreeing = len(position_votes[best_pos])

        # Determine confidence
        if tests_with_matches == 0:
            confidence = "none"
        elif agreeing == tests_with_matches and agreeing >= 3:
            confidence = "high"
        elif agreeing >= tests_with_matches * 0.6:
            confidence = "medium"
        else:
            confidence = "low"

        # Build the mapping table
        mapping = {}
        # Determine max header DWs (4 for 64-bit/message, 5 for MW64 with data)
        max_header_dws = 5
        for i in range(max_header_dws):
            buf_dw = best_pos + i
            if buf_dw < TBUF_ROW_DWORDS:
                if i == 0:
                    mapping[f"DW{buf_dw}"] = "TLP Header DW0 (Fmt/Type/Length)"
                elif i == 1:
                    mapping[f"DW{buf_dw}"] = "TLP Header DW1 (ReqID/Tag/BE or MsgCode)"
                elif i == 2:
                    mapping[f"DW{buf_dw}"] = "TLP Header DW2 (Addr[31:0] or Addr[63:32])"
                elif i == 3:
                    mapping[f"DW{buf_dw}"] = "TLP Header DW3 (Addr[31:0] for 4DW or Data)"
                elif i == 4:
                    mapping[f"DW{buf_dw}"] = "TLP Data DW (for write TLPs)"

        # Add DW17/DW18 annotations
        mapping["DW17"] = "Timestamp (pending confirmation)"
        mapping["DW18"] = "Metadata / Reserved (top 8 bits = 0x00)"

        return {
            "consensus_start_pos": best_pos,
            "confidence": confidence,
            "tests_agreeing": agreeing,
            "total_tests_with_matches": tests_with_matches,
            "mapping": mapping,
            "all_votes": {str(k): v for k, v in position_votes.items()},
        }

    # -----------------------------------------------------------------------
    # Phase 6: Raw Buffer Diagnostic Dump
    # -----------------------------------------------------------------------

    def phase6_raw_dump(self):
        """Capture and dump raw buffer data for manual inspection.

        Sends a simple MR32 TLP and dumps the full buffer contents, plus
        tries data_cap=True and different trace points to compare.
        """
        print("\n=== Phase 6: Raw Buffer Diagnostic Dump ===")

        tlp_cfg = {
            "tlp_type": "mr32",
            "address": 0xFACE0000,
            "requester_id": 0xABCD,
            "tag": 0xFE,
            "length_dw": 1,
        }
        expected = build_tlp_header(
            TlpType.MR32,
            address=0xFACE0000,
            requester_id=0xABCD,
            tag=0xFE,
            length_dw=1,
        )
        flit_search = _build_flit_search_terms(expected, TlpType.MR32)

        # 6.1 — Default config dump (trace_point=0, data_cap=False)
        def test_6_1(r: TestResult):
            resp = self._capture_and_send([tlp_cfg], trace_point=0, data_cap=False)
            rows = self._extract_rows(resp)

            samples = self._dump_sample_rows(rows, max_rows=20)
            # Aggregate non-zero DW positions across all rows
            dw_occupancy = [0] * TBUF_ROW_DWORDS
            for _idx, dwords in rows:
                for i, dw in enumerate(dwords):
                    if dw != 0:
                        dw_occupancy[i] += 1

            # Flit scan
            flit_total = 0
            flit_sample = []
            for row_idx, dwords in rows[:50]:
                result = _scan_row_flit_mode(dwords, flit_search, row_idx)
                flit_total += result["total_hits"]
                if result["total_hits"] > 0 and len(flit_sample) < 3:
                    flit_sample.append(result)

            r.data = {
                "config": "trace_point=0, data_cap=False (default)",
                "total_rows": len(rows),
                "sample_rows": samples,
                "dw_occupancy": {
                    f"DW{i}": count for i, count in enumerate(dw_occupancy) if count > 0
                },
                "expected_header": [f"0x{dw:08X}" for dw in expected],
                "flit_type_byte": f"0x{flit_search['flit_type_byte']:02X}",
                "flit_total_hits": flit_total,
                "flit_sample_hits": flit_sample,
            }
            r.expected = "Dump raw buffer for inspection"
            r.actual = (
                f"rows={len(rows)}, "
                f"flit_hits={flit_total}, "
                f"active_dws={[f'DW{i}' for i, c in enumerate(dw_occupancy) if c > 0]}"
            )
            r.status = "PASS"

        self._run_test(
            "6.1_raw_default", 6,
            "Raw dump: tp=0 data_cap=off", test_6_1,
        )

        # 6.2 — data_cap=True
        def test_6_2(r: TestResult):
            resp = self._capture_and_send([tlp_cfg], trace_point=0, data_cap=True)
            rows = self._extract_rows(resp)
            samples = self._dump_sample_rows(rows, max_rows=20)

            dw_occupancy = [0] * TBUF_ROW_DWORDS
            for _idx, dwords in rows:
                for i, dw in enumerate(dwords):
                    if dw != 0:
                        dw_occupancy[i] += 1

            flit_total = 0
            for row_idx, dwords in rows[:50]:
                result = _scan_row_flit_mode(dwords, flit_search, row_idx)
                flit_total += result["total_hits"]

            r.data = {
                "config": "trace_point=0, data_cap=True",
                "total_rows": len(rows),
                "sample_rows": samples,
                "dw_occupancy": {
                    f"DW{i}": count for i, count in enumerate(dw_occupancy) if count > 0
                },
                "flit_total_hits": flit_total,
            }
            r.expected = "Dump raw buffer with data_cap=True"
            r.actual = (
                f"rows={len(rows)}, "
                f"flit_hits={flit_total}, "
                f"active_dws={[f'DW{i}' for i, c in enumerate(dw_occupancy) if c > 0]}"
            )
            r.status = "PASS"

        self._run_test(
            "6.2_raw_datacap", 6,
            "Raw dump: tp=0 data_cap=on", test_6_2,
        )

        # 6.3 — trace_point=1 (Unscrambler/OSGen)
        def test_6_3(r: TestResult):
            resp = self._capture_and_send([tlp_cfg], trace_point=1, data_cap=False)
            rows = self._extract_rows(resp)
            samples = self._dump_sample_rows(rows, max_rows=20)

            dw_occupancy = [0] * TBUF_ROW_DWORDS
            for _idx, dwords in rows:
                for i, dw in enumerate(dwords):
                    if dw != 0:
                        dw_occupancy[i] += 1

            flit_total = 0
            for row_idx, dwords in rows[:50]:
                result = _scan_row_flit_mode(dwords, flit_search, row_idx)
                flit_total += result["total_hits"]

            r.data = {
                "config": "trace_point=1 (Unscrambler/OSGen), data_cap=False",
                "total_rows": len(rows),
                "sample_rows": samples,
                "dw_occupancy": {
                    f"DW{i}": count for i, count in enumerate(dw_occupancy) if count > 0
                },
                "flit_total_hits": flit_total,
            }
            r.expected = "Dump raw buffer with trace_point=1"
            r.actual = (
                f"rows={len(rows)}, "
                f"flit_hits={flit_total}, "
                f"active_dws={[f'DW{i}' for i, c in enumerate(dw_occupancy) if c > 0]}"
            )
            r.status = "PASS"

        self._run_test(
            "6.3_raw_tp1", 6,
            "Raw dump: tp=1 (Unscram) data_cap=off", test_6_3,
        )

    # -----------------------------------------------------------------------
    # Phase 7: Filtered Capture Experiments
    # -----------------------------------------------------------------------

    def phase7_filtered_capture(self):
        """Test PTrace hardware filter to exclude idle/NOP data.

        Uses the 512-bit match/mask filter system (filter_en + filter index 0)
        to capture only specific TLP types. Compares results against the
        constant idle pattern observed in unfiltered captures.
        """
        print("\n=== Phase 7: Filtered Capture Experiments ===")

        # First, capture an unfiltered baseline to identify the idle pattern
        baseline_tlp_cfg = {
            "tlp_type": "mr32",
            "address": 0x00010000,
            "requester_id": 0x0001,
            "tag": 0x01,
            "length_dw": 1,
        }

        def _get_idle_signature(rows: list[tuple[int, list[int]]]) -> tuple[int, str]:
            """Extract the dominant DW11-DW15 pattern as an idle signature.

            Returns (row_count, hex signature of DW11-DW15 from first row).
            """
            if not rows:
                return 0, ""
            # Use first row's DW11-DW15 as the idle reference
            _, first_dwords = rows[0]
            sig_dws = first_dwords[11:16] if len(first_dwords) >= 16 else []
            sig_hex = "_".join(f"{dw:08X}" for dw in sig_dws)
            return len(rows), sig_hex

        def _rows_differ_from_idle(
            rows: list[tuple[int, list[int]]], idle_sig: str
        ) -> bool:
            """Check if captured rows differ from the constant idle pattern."""
            if not rows:
                # No rows at all — filter may have excluded everything (good)
                return True
            if not idle_sig:
                return True
            # Check if any row has DW11-DW15 different from idle signature
            for _, dwords in rows:
                if len(dwords) >= 16:
                    row_sig = "_".join(f"{dw:08X}" for dw in dwords[11:16])
                    if row_sig != idle_sig:
                        return True
            # Also check if DW0-DW10 has any non-zero content (TLP data)
            for _, dwords in rows:
                for i in range(min(11, len(dwords))):
                    if dwords[i] != 0:
                        return True
            return False

        # --- Capture unfiltered baseline ---
        def test_7_0(r: TestResult):
            resp = self._capture_and_send_custom(
                [baseline_tlp_cfg], trace_point=0, data_cap=False
            )
            rows = self._extract_rows(resp)
            idle_count, idle_sig = _get_idle_signature(rows)

            # Store baseline for sub-tests
            self._phase7_idle_sig = idle_sig
            self._phase7_idle_count = idle_count

            dw_occupancy = [0] * TBUF_ROW_DWORDS
            for _, dwords in rows:
                for i, dw in enumerate(dwords):
                    if dw != 0:
                        dw_occupancy[i] += 1

            r.data = {
                "config": "Unfiltered baseline (no filter_en)",
                "total_rows": idle_count,
                "idle_signature": idle_sig,
                "dw_occupancy": {
                    f"DW{i}": count for i, count in enumerate(dw_occupancy) if count > 0
                },
                "sample_rows": self._dump_sample_rows(rows, max_rows=5),
            }
            r.expected = "Capture idle baseline for comparison"
            r.actual = f"rows={idle_count}, idle_sig={idle_sig[:40]}..."
            r.status = "PASS" if idle_count > 0 else "WARN"
            if idle_count == 0:
                r.notes = "No rows in baseline — filtered tests may not be comparable"

        self._run_test(
            "7.0_baseline", 7,
            "Unfiltered baseline capture", test_7_0,
        )

        # --- Filter test definitions ---
        # CfgRd0 flit type byte: Fmt=0b00, Type=0b00100 → 0x04
        # MW32 flit type byte: Fmt=0b10, Type=0b00000 → 0x40
        filter_tests = [
            {
                "test_id": "7.1_cfgrd0_dw0",
                "name": "Filter CfgRd0 (0x04) at DW0",
                "tlp_type": "cfrd0",
                "tlp_cfg": {
                    "tlp_type": "cfrd0",
                    "target_id": 0x0500,
                    "requester_id": 0xF001,
                    "tag": 0x71,
                    "length_dw": 1,
                },
                "match_byte": 0x04,
                "dw_position": 0,
            },
            {
                "test_id": "7.2_cfgrd0_dw11",
                "name": "Filter CfgRd0 (0x04) at DW11",
                "tlp_type": "cfrd0",
                "tlp_cfg": {
                    "tlp_type": "cfrd0",
                    "target_id": 0x0500,
                    "requester_id": 0xF002,
                    "tag": 0x72,
                    "length_dw": 1,
                },
                "match_byte": 0x04,
                "dw_position": 11,
            },
            {
                "test_id": "7.3_mw32_dw0",
                "name": "Filter MW32 (0x40) at DW0",
                "tlp_type": "mw32",
                "tlp_cfg": {
                    "tlp_type": "mw32",
                    "address": 0xF0CE0000,
                    "requester_id": 0xF003,
                    "tag": 0x73,
                    "length_dw": 1,
                    "data": "DEADF00D",
                },
                "match_byte": 0x40,
                "dw_position": 0,
            },
            {
                "test_id": "7.4_mw32_dw11",
                "name": "Filter MW32 (0x40) at DW11",
                "tlp_type": "mw32",
                "tlp_cfg": {
                    "tlp_type": "mw32",
                    "address": 0xF0CE0000,
                    "requester_id": 0xF004,
                    "tag": 0x74,
                    "length_dw": 1,
                    "data": "DEADF00D",
                },
                "match_byte": 0x40,
                "dw_position": 11,
            },
        ]

        # Store per-test results for summary
        self._phase7_results: list[dict] = []

        for ft in filter_tests:
            def _make_test(ft_spec: dict):
                def test_fn(r: TestResult):
                    match_hex, mask_hex = _build_filter_hex(
                        ft_spec["match_byte"], ft_spec["dw_position"]
                    )

                    r.data["filter_match_hex"] = match_hex
                    r.data["filter_mask_hex"] = mask_hex
                    r.data["match_byte"] = f"0x{ft_spec['match_byte']:02X}"
                    r.data["dw_position"] = ft_spec["dw_position"]

                    resp = self._capture_with_filter(
                        [ft_spec["tlp_cfg"]],
                        filter_match_hex=match_hex,
                        filter_mask_hex=mask_hex,
                        trace_point=0,
                        data_cap=False,
                    )
                    rows = self._extract_rows(resp)
                    samples = self._dump_sample_rows(rows, max_rows=10)

                    dw_occupancy = [0] * TBUF_ROW_DWORDS
                    for _, dwords in rows:
                        for i, dw in enumerate(dwords):
                            if dw != 0:
                                dw_occupancy[i] += 1

                    idle_sig = getattr(self, "_phase7_idle_sig", "")
                    idle_count = getattr(self, "_phase7_idle_count", 0)
                    differs = _rows_differ_from_idle(rows, idle_sig)

                    r.data["total_rows"] = len(rows)
                    r.data["idle_baseline_rows"] = idle_count
                    r.data["content_differs_from_idle"] = differs
                    r.data["sample_rows"] = samples
                    r.data["dw_occupancy"] = {
                        f"DW{i}": count
                        for i, count in enumerate(dw_occupancy)
                        if count > 0
                    }

                    r.expected = (
                        f"Filter byte 0x{ft_spec['match_byte']:02X} "
                        f"at DW{ft_spec['dw_position']} — "
                        f"buffer differs from idle"
                    )
                    r.actual = (
                        f"rows={len(rows)} (baseline={idle_count}), "
                        f"differs={differs}, "
                        f"active_dws="
                        f"{[f'DW{i}' for i, c in enumerate(dw_occupancy) if c > 0]}"
                    )

                    # PASS if content differs from constant idle pattern
                    # or if fewer rows captured (filter excluded idle)
                    if differs:
                        r.status = "PASS"
                        r.notes = "Filter produced non-idle content"
                    elif len(rows) < idle_count:
                        r.status = "PASS"
                        r.notes = (
                            f"Fewer rows ({len(rows)} vs {idle_count}) — "
                            f"filter excluded some data"
                        )
                    else:
                        r.status = "FAIL"
                        r.notes = "Same idle data as unfiltered — filter had no effect"

                    # Record for summary
                    self._phase7_results.append({
                        "test_id": ft_spec["test_id"],
                        "match_byte": f"0x{ft_spec['match_byte']:02X}",
                        "dw_position": ft_spec["dw_position"],
                        "rows": len(rows),
                        "differs_from_idle": differs,
                        "status": r.status,
                    })

                return test_fn
            self._run_test(
                ft["test_id"], 7, ft["name"], _make_test(ft),
            )

    # -----------------------------------------------------------------------
    # Run all phases
    # -----------------------------------------------------------------------

    def run(self) -> int:
        if not self.discover():
            return 2

        phase_map = {
            1: self.phase1_mem32,
            2: self.phase2_mem64,
            3: self.phase3_config,
            4: self.phase4_messages,
            5: self.phase5_consensus,
            6: self.phase6_raw_dump,
            7: self.phase7_filtered_capture,
        }

        for phase_num in sorted(self.phases):
            fn = phase_map.get(phase_num)
            if fn:
                try:
                    fn()
                except Exception as exc:
                    print(f"\n  PHASE {phase_num} ABORTED: {exc}")
                    self.results.append(TestResult(
                        test_id=f"phase_{phase_num}_abort",
                        phase=phase_num,
                        name=f"Phase {phase_num} aborted",
                        status="ERROR",
                        notes=f"{type(exc).__name__}: {exc}",
                    ))

        # Compute consensus once and reuse
        self._cached_consensus = self._build_consensus_mapping()
        self._write_results()
        return self._print_summary()

    def _write_results(self):
        all_dw17 = [v for cap in self.per_capture_dw17 for v in cap]
        all_dw18 = [v for cap in self.per_capture_dw18 for v in cap]
        output = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "device_id": self.device_id,
            "device_info": self.device_info,
            "test_port": self.port_number,
            "wait_ms": self.wait_ms,
            "trace_point": self.trace_point,
            "data_cap": self.data_cap,
            "results": [asdict(r) for r in self.results],
            "correlations": self.correlations,
            "dw17_values": [f"0x{v:08X}" for v in all_dw17],
            "dw18_values": [f"0x{v:08X}" for v in all_dw18],
            "consensus_mapping": self._cached_consensus,
        }
        results_path = self.output_dir / "results.json"
        with open(results_path, "w") as f:
            json.dump(output, f, indent=2, default=str)
        print(f"\n  Results written to: {results_path}")

    def _print_summary(self) -> int:
        counts = {"PASS": 0, "FAIL": 0, "WARN": 0, "ERROR": 0, "SKIP": 0}
        for r in self.results:
            counts[r.status] = counts.get(r.status, 0) + 1

        mapping = self._cached_consensus

        lines = [
            "",
            "=" * 72,
            "PTrace Capture Correlation Report",
            "=" * 72,
            f"Device:    {self.device_id}",
            f"Chip ID:   0x{self.device_info.get('chip_id', 0):04X}",
            f"Test port: {self.port_number}",
            f"Wait ms:   {self.wait_ms}",
            f"Trace pt:  {self.trace_point}",
            f"Data cap:  {self.data_cap}",
            f"Timestamp: {datetime.now(timezone.utc).isoformat()}",
            "",
            "--- Test Results ---",
            f"  PASS:  {counts['PASS']:3d}",
            f"  FAIL:  {counts['FAIL']:3d}",
            f"  WARN:  {counts['WARN']:3d}",
            f"  ERROR: {counts['ERROR']:3d}",
            f"  SKIP:  {counts['SKIP']:3d}",
            f"  TOTAL: {sum(counts.values()):3d}",
            "",
            "--- Per-TLP Correlation ---",
        ]

        for corr in self.correlations:
            best = corr["best_match"]
            buf_start = best["buffer_start_pos"]
            buf_str = f"DW{buf_start:<2d}" if buf_start >= 0 else "N/A  "
            lines.append(
                f"  {corr['test_id']:5s} {corr['tlp_type']:10s}: "
                f"score={best['score']}/{corr['num_expected_dws']}  "
                f"buf_start={buf_str}  "
                f"type={best['match_type'] or 'none':<12s}  "
                f"rows={corr['total_non_empty_rows']}"
            )

        lines.append("")
        lines.append("--- Consensus Buffer Layout ---")
        consensus_pos = mapping.get("consensus_start_pos", -1)
        pos_str = f"DW{consensus_pos}" if consensus_pos >= 0 else "N/A"
        lines.append(f"  Header start position: {pos_str}")
        lines.append(
            f"  Confidence: {mapping.get('confidence', 'unknown')}"
        )
        lines.append(
            f"  Tests agreeing: {mapping.get('tests_agreeing', 0)}/"
            f"{mapping.get('total_tests_with_matches', 0)}"
        )
        lines.append("")

        for dw_name, desc in mapping.get("mapping", {}).items():
            lines.append(f"  {dw_name:6s} = {desc}")

        # --- Flit-Mode Analysis ---
        lines.append("")
        lines.append("--- Flit-Mode Analysis ---")
        flit_tests_with_hits = 0
        total_flit_hits = 0
        for corr in self.correlations:
            fa = corr.get("flit_analysis", {})
            hits = fa.get("total_flit_hits", 0)
            if hits > 0:
                flit_tests_with_hits += 1
            total_flit_hits += hits
        lines.append(f"  Tests with Flit hits: {flit_tests_with_hits}/{len(self.correlations)}")
        lines.append(f"  Total Flit hits: {total_flit_hits}")
        if total_flit_hits > 0:
            lines.append("  Per-test Flit hits:")
            for corr in self.correlations:
                fa = corr.get("flit_analysis", {})
                hits = fa.get("total_flit_hits", 0)
                if hits > 0:
                    best_row = fa.get("best_row", {})
                    lines.append(
                        f"    {corr['test_id']:5s} {corr['tlp_type']:10s}: "
                        f"flit_hits={hits}, "
                        f"rows_with_hits={fa.get('rows_with_hits', 0)}"
                    )
                    if best_row:
                        for bh in best_row.get("flit_byte_hits", [])[:2]:
                            lines.append(
                                f"      type_byte @ DW{bh['dw_pos']}[byte{bh['byte_pos']}] "
                                f"= {bh['dw_value']}"
                            )
                        for wh in best_row.get("word_hits", [])[:3]:
                            lines.append(
                                f"      word {wh['value']} ({wh['field']}) "
                                f"@ DW{wh['dw_pos']}.{wh['half']} = {wh['dw_value']}"
                            )
        else:
            lines.append("  No Flit-mode matches found in any test.")
            lines.append(
                "  (Buffer data may require Broadcom decode step to interpret.)"
            )
        lines.append("")

        # --- Raw Dump Summary ---
        raw_dump_results = [r for r in self.results if r.phase == 6]
        if raw_dump_results:
            lines.append("--- Raw Buffer Dump Summary ---")
            for r in raw_dump_results:
                lines.append(f"  {r.test_id}: {r.name}")
                lines.append(f"    {r.actual}")
            lines.append("")

        # --- Filtered Capture Experiments ---
        phase7_results = getattr(self, "_phase7_results", [])
        if phase7_results:
            lines.append("--- Filtered Capture Experiments ---")
            idle_count = getattr(self, "_phase7_idle_count", 0)
            lines.append(f"  Baseline (unfiltered) rows: {idle_count}")
            for pr in phase7_results:
                status_char = {"PASS": "+", "FAIL": "!", "WARN": "~", "ERROR": "X"}.get(
                    pr["status"], "?"
                )
                lines.append(
                    f"  [{status_char}] {pr['test_id']:20s}: "
                    f"filter={pr['match_byte']} @ DW{pr['dw_position']:<2d}  "
                    f"rows={pr['rows']:3d}  "
                    f"differs={pr['differs_from_idle']}"
                )
            lines.append("")

        lines.append("--- DW17/DW18 Analysis ---")

        dw17 = self._analyze_dw17()
        lines.append(f"  DW17 count: {dw17.get('count', 0)}")
        lines.append(
            f"  DW17 monotonic (per capture): {dw17.get('monotonic_per_capture')}"
        )
        if dw17.get("count", 0) > 0:
            lines.append(f"  DW17 range: {dw17.get('min')} .. {dw17.get('max')}")

        dw18 = self._analyze_dw18()
        lines.append(f"  DW18 count: {dw18.get('count', 0)}")
        lines.append(f"  DW18 top byte always 0x00: {dw18.get('top_byte_always_zero')}")

        for status_type in ("FAIL", "ERROR", "WARN"):
            items = [r for r in self.results if r.status == status_type]
            if items:
                lines.append(f"\n--- {status_type} ---")
                for r in items:
                    lines.append(f"  {r.test_id}: {r.name}")
                    if r.notes:
                        for line in r.notes.split("\n"):
                            lines.append(f"    {line}")

        lines.extend([
            "",
            "--- NOTES ---",
            "  1. Score = number of consecutive header DWORDs matched at best position.",
            "  2. A high-confidence consensus requires 3+ tests agreeing on the same",
            "     buffer start position with score >= 2.",
            "  3. DW17 monotonicity suggests it contains a timestamp counter.",
            "  4. DW18 top byte = 0x00 confirms 8 reserved bits per the spec.",
            "  5. If all rows are empty, try a different trace point or direction.",
            "  6. Gen6 Flit mode: TLP type byte at DW0[7:0], not DW0[31:24].",
            "     Flit hits indicate Flit-mode encoding detected in buffer.",
            "  7. Phase 6 raw dumps compare trace_point/data_cap configurations",
            "     to identify which settings produce meaningful captured data.",
            "  8. Raw buffer may require Broadcom 'decode' step (SwitchCLID utility)",
            "     to fully interpret captured Flit data.",
            "  9. Phase 7 uses 512-bit match/mask filters (filter_en + filter index 0)",
            "     to test whether hardware filtering can exclude idle/NOP Flit data.",
            "     Mask polarity: bit=1 → don't care, bit=0 → must match.",
            "=" * 72,
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
        description="PTrace Capture Correlation Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Run all phases against auto-detected device\n"
            "  python scripts/ptrace_capture_correlation.py\n\n"
            "  # Specific device and port, phases 1-3 only\n"
            "  python scripts/ptrace_capture_correlation.py "
            "--device-id dev_03_00 --port 16 --phases 1,2,3\n\n"
            "  # Custom server URL and longer wait\n"
            "  python scripts/ptrace_capture_correlation.py "
            "--base-url http://192.168.1.100:8000 --wait-ms 1000\n"
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
        "--output-dir", default="./ptrace_correlation",
        help="Output directory (default: ./ptrace_correlation)",
    )
    parser.add_argument(
        "--wait-ms", type=int, default=500,
        help="Post-trigger wait in ms (default: 500)",
    )
    parser.add_argument(
        "--phases", default="1,2,3,4,5,6,7",
        help="Comma-separated phase numbers to run (default: 1,2,3,4,5,6,7)",
    )
    parser.add_argument(
        "--trace-point", type=int, default=0,
        help="PTrace capture trace point: 0=DLLP/TLP (default), 1=Unscrambler/OSGen",
    )
    parser.add_argument(
        "--data-cap", action="store_true", default=False,
        help="Enable data capture mode in PTrace (default: off)",
    )
    args = parser.parse_args()

    phases = {int(p.strip()) for p in args.phases.split(",") if p.strip()}

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir) / ts
    output_dir.mkdir(parents=True, exist_ok=True)

    print("PTrace Capture Correlation")
    print(f"Output: {output_dir}")
    print(f"Phases: {sorted(phases)}")
    print(f"Trace point: {args.trace_point}")
    print(f"Data capture: {args.data_cap}")

    correlator = CaptureCorrelator(
        base_url=args.base_url,
        device_id=args.device_id,
        port_number=args.port,
        output_dir=output_dir,
        phases=phases,
        wait_ms=args.wait_ms,
        trace_point=args.trace_point,
        data_cap=args.data_cap,
    )

    sys.exit(correlator.run())


if __name__ == "__main__":
    main()
