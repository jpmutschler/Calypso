#!/usr/bin/env python3
"""Convert PTrace JSON captures to .trace / hex / binary formats for SwitchCLID.

Reads the raw JSON files produced by ptrace_capture_correlation.py (or the
Calypso PTrace API buffer endpoint) and writes multiple output formats so the
user can determine which one SwitchCLID accepts.

Output formats:
  1. hex_dw0first.txt  — "Row NNNN: DW0DW1...DW18" (Calypso native order)
  2. hex_dw18first.txt — "Row NNNN: DW18DW17...DW0" (reversed, MSB-first)
  3. hex_payload.txt   — "Row NNNN: DW0DW1...DW15" (512-bit payload only)
  4. binary_le.trace   — 76 bytes/row (19 LE DWORDs), no header
  5. binary_be.trace   — 76 bytes/row (19 BE DWORDs), no header
  6. csv_dwords.csv    — row_index, dword_0 .. dword_18

Usage:
    python scripts/ptrace_export_trace.py <input.json> [--output-dir ./]
    python scripts/ptrace_export_trace.py ptrace_correlation/*/raw/1.2_mw32.json

The script auto-detects the JSON structure:
  - Calypso API buffer response (has "rows" with "dwords")
  - Correlation raw file (has "correlation.sample_rows" or "sample_rows")
  - results.json (extracts all correlations)
"""

from __future__ import annotations

import argparse
import csv
import json
import struct
import sys
from pathlib import Path

TBUF_ROW_DWORDS = 19


def _extract_rows_from_json(data: dict) -> list[tuple[int, list[int]]]:
    """Extract (row_index, dwords) tuples from various JSON structures."""
    rows: list[tuple[int, list[int]]] = []

    # Format 1: Calypso API buffer response {"rows": [{"row_index": N, "dwords": [...]}]}
    if "rows" in data and isinstance(data["rows"], list):
        for r in data["rows"]:
            if isinstance(r, dict) and "dwords" in r:
                rows.append((r.get("row_index", len(rows)), r["dwords"]))
        if rows:
            return rows

    # Format 2: Correlation raw file with sample_rows containing hex strings
    sample_rows = data.get("sample_rows", [])
    if not sample_rows:
        corr = data.get("correlation", {})
        sample_rows = corr.get("sample_rows", [])

    for sr in sample_rows:
        dwords_hex = sr.get("dwords_hex", [])
        if dwords_hex:
            dwords = [int(h, 16) for h in dwords_hex]
            rows.append((sr.get("row_index", len(rows)), dwords))

    if rows:
        return rows

    # Format 3: results.json — extract anomalous rows from all correlations
    for corr in data.get("correlations", []):
        for ar in corr.get("anomalous_rows", []):
            dwords_hex = ar.get("dwords_hex", [])
            if dwords_hex:
                dwords = [int(h, 16) for h in dwords_hex]
                rows.append((ar.get("row_index", len(rows)), dwords))
        for sr in corr.get("sample_rows", []):
            dwords_hex = sr.get("dwords_hex", [])
            if dwords_hex:
                dwords = [int(h, 16) for h in dwords_hex]
                rows.append((sr.get("row_index", len(rows)), dwords))

    return rows


def write_hex_dw0first(rows: list[tuple[int, list[int]]], path: Path) -> None:
    """DW0 DW1 ... DW18 (Calypso native order)."""
    with open(path, "w") as f:
        for row_idx, dwords in rows:
            hex_str = "".join(f"{d:08X}" for d in dwords)
            f.write(f"Row {row_idx:4d}: {hex_str}\n")


def write_hex_dw18first(rows: list[tuple[int, list[int]]], path: Path) -> None:
    """DW18 DW17 ... DW0 (reversed / MSB-first)."""
    with open(path, "w") as f:
        for row_idx, dwords in rows:
            hex_str = "".join(f"{d:08X}" for d in reversed(dwords))
            f.write(f"Row {row_idx:4d}: {hex_str}\n")


def write_hex_payload(rows: list[tuple[int, list[int]]], path: Path) -> None:
    """DW0 DW1 ... DW15 (512-bit payload only, no metadata)."""
    with open(path, "w") as f:
        for row_idx, dwords in rows:
            hex_str = "".join(f"{d:08X}" for d in dwords[:16])
            f.write(f"Row {row_idx:4d}: {hex_str}\n")


def write_binary(
    rows: list[tuple[int, list[int]]], path: Path, *, big_endian: bool = False
) -> None:
    """Raw binary: 76 bytes per row (19 DWORDs)."""
    fmt_char = ">" if big_endian else "<"
    with open(path, "wb") as f:
        for _, dwords in rows:
            # Pad to 19 DWORDs if short
            padded = (dwords + [0] * TBUF_ROW_DWORDS)[:TBUF_ROW_DWORDS]
            f.write(struct.pack(f"{fmt_char}{TBUF_ROW_DWORDS}I", *padded))


def write_csv(rows: list[tuple[int, list[int]]], path: Path) -> None:
    """CSV with row_index and dword_0 through dword_18."""
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["row_index"] + [f"dword_{i}" for i in range(TBUF_ROW_DWORDS)])
        for row_idx, dwords in rows:
            writer.writerow(
                [row_idx] + [f"0x{d:08X}" for d in dwords]
            )


def write_hex_raw_no_prefix(rows: list[tuple[int, list[int]]], path: Path) -> None:
    """Plain hex lines (no 'Row NNNN:' prefix) — one 152-char hex line per row."""
    with open(path, "w") as f:
        for _, dwords in rows:
            hex_str = "".join(f"{d:08X}" for d in dwords)
            f.write(f"{hex_str}\n")


def write_hex_spaced(rows: list[tuple[int, list[int]]], path: Path) -> None:
    """Space-separated DWORDs per row: 'DW0 DW1 ... DW18'."""
    with open(path, "w") as f:
        for row_idx, dwords in rows:
            hex_str = " ".join(f"{d:08X}" for d in dwords)
            f.write(f"{hex_str}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Convert PTrace JSON to .trace formats for SwitchCLID",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/ptrace_export_trace.py "
            "ptrace_correlation/*/raw/1.2_mw32.json\n"
            "  python scripts/ptrace_export_trace.py "
            "ptrace_correlation/*/results.json --output-dir ./trace_export\n"
        ),
    )
    parser.add_argument("input", help="Input JSON file (raw capture or results.json)")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory (default: same dir as input file)",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: File not found: {input_path}")
        sys.exit(1)

    with open(input_path) as f:
        data = json.load(f)

    rows = _extract_rows_from_json(data)
    if not rows:
        print(f"ERROR: No buffer rows found in {input_path}")
        print("  Expected: Calypso API buffer response, correlation raw file, or results.json")
        sys.exit(1)

    out_dir = Path(args.output_dir) if args.output_dir else input_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = input_path.stem

    print(f"Input:  {input_path}")
    print(f"Rows:   {len(rows)}")
    print(f"Output: {out_dir}/")
    print()

    exports = [
        (f"{stem}_dw0first.txt", write_hex_dw0first,
         "Hex DW0-first (Calypso native)"),
        (f"{stem}_dw18first.txt", write_hex_dw18first,
         "Hex DW18-first (reversed)"),
        (f"{stem}_payload.txt", write_hex_payload,
         "Hex payload only (DW0-DW15)"),
        (f"{stem}_raw.txt", write_hex_raw_no_prefix,
         "Hex raw (no row prefix)"),
        (f"{stem}_spaced.txt", write_hex_spaced,
         "Hex space-separated DWORDs"),
        (f"{stem}_le.trace", lambda r, p: write_binary(r, p, big_endian=False),
         "Binary LE (76 bytes/row)"),
        (f"{stem}_be.trace", lambda r, p: write_binary(r, p, big_endian=True),
         "Binary BE (76 bytes/row)"),
        (f"{stem}.csv", write_csv,
         "CSV"),
    ]

    for filename, writer_fn, desc in exports:
        path = out_dir / filename
        writer_fn(rows, path)
        size = path.stat().st_size
        print(f"  {filename:40s}  {size:8d} bytes  ({desc})")

    print(f"\nDone. Try each format with SwitchCLID to find the right one.")
    print(f"Most likely candidates: *_le.trace or *_be.trace (binary),")
    print(f"or *_dw0first.txt / *_raw.txt (hex text).")


if __name__ == "__main__":
    main()
