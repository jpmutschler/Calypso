"""Human-readable decode renderers for PCIe capability structures.

Each render function takes a capability base offset and a reg_map dict,
then emits NiceGUI widgets showing decoded bitfields.
"""

from __future__ import annotations

from nicegui import ui

from calypso.ui.theme import COLORS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _kv(label: str, value: str) -> None:
    ui.label(label).style(f"color: {COLORS.text_secondary}; font-size: 13px")
    ui.label(value).style(f"color: {COLORS.text_primary}; font-size: 13px")


def _flag(name: str, active: bool) -> None:
    color = COLORS.cyan if active else COLORS.text_muted
    prefix = "[x]" if active else "[ ]"
    ui.label(f"{prefix} {name}").style(f"color: {color}; font-family: monospace; font-size: 12px")


def _reg(offset: int, reg_map: dict[int, int]) -> int:
    return reg_map.get(offset, 0xFFFFFFFF)


_SPEED_NAMES = {1: "Gen1", 2: "Gen2", 3: "Gen3", 4: "Gen4", 5: "Gen5", 6: "Gen6"}
_PAYLOAD_SIZES = [128, 256, 512, 1024, 2048, 4096]


# ---------------------------------------------------------------------------
# Standard capabilities
# ---------------------------------------------------------------------------


def render_power_management(base: int, reg_map: dict[int, int]) -> None:
    """Decode Power Management capability (cap_id=0x01)."""
    header = _reg(base, reg_map)
    pmc = (header >> 16) & 0xFFFF
    pmcsr_raw = _reg(base + 0x04, reg_map)
    pmcsr = pmcsr_raw & 0xFFFF

    pm_version = pmc & 0x7
    pme_clock = bool(pmc & (1 << 3))
    d1_support = bool(pmc & (1 << 9))
    d2_support = bool(pmc & (1 << 10))
    pme_support = (pmc >> 11) & 0x1F

    power_state = pmcsr & 0x3
    state_names = {0: "D0", 1: "D1", 2: "D2", 3: "D3hot"}
    no_soft_reset = bool(pmcsr & (1 << 3))
    pme_enabled = bool(pmcsr & (1 << 8))
    pme_status = bool(pmcsr & (1 << 15))

    with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
        _kv("PM Version", str(pm_version))
        _kv("Current State", state_names.get(power_state, f"?({power_state})"))
        _kv("D1 Support", "Yes" if d1_support else "No")
        _kv("D2 Support", "Yes" if d2_support else "No")
        _kv("PME Clock", "Yes" if pme_clock else "No")
        _kv("No Soft Reset", "Yes" if no_soft_reset else "No")
        _kv("PME Enabled", "Yes" if pme_enabled else "No")
        _kv("PME Status", "Asserted" if pme_status else "Clear")
        pme_from = []
        if pme_support & 0x01:
            pme_from.append("D0")
        if pme_support & 0x02:
            pme_from.append("D1")
        if pme_support & 0x04:
            pme_from.append("D2")
        if pme_support & 0x08:
            pme_from.append("D3hot")
        if pme_support & 0x10:
            pme_from.append("D3cold")
        _kv("PME From", ", ".join(pme_from) if pme_from else "None")


def render_msi(base: int, reg_map: dict[int, int]) -> None:
    """Decode MSI capability (cap_id=0x05)."""
    header = _reg(base, reg_map)
    msg_ctrl = (header >> 16) & 0xFFFF

    enabled = bool(msg_ctrl & (1 << 0))
    mmc = (msg_ctrl >> 1) & 0x7
    mme = (msg_ctrl >> 4) & 0x7
    is_64bit = bool(msg_ctrl & (1 << 7))
    pvm = bool(msg_ctrl & (1 << 8))

    with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
        _kv("MSI Enabled", "Yes" if enabled else "No")
        _kv("Vectors Capable", str(1 << mmc))
        _kv("Vectors Enabled", str(1 << mme))
        _kv("64-bit Address", "Yes" if is_64bit else "No")
        _kv("Per-Vector Masking", "Yes" if pvm else "No")
        addr_lo = _reg(base + 0x04, reg_map)
        if is_64bit:
            addr_hi = _reg(base + 0x08, reg_map)
            _kv("Address", f"0x{addr_hi:08X}_{addr_lo:08X}")
            data = _reg(base + 0x0C, reg_map) & 0xFFFF
        else:
            _kv("Address", f"0x{addr_lo:08X}")
            data = _reg(base + 0x08, reg_map) & 0xFFFF
        _kv("Data", f"0x{data:04X}")


def render_msix(base: int, reg_map: dict[int, int]) -> None:
    """Decode MSI-X capability (cap_id=0x11)."""
    header = _reg(base, reg_map)
    msg_ctrl = (header >> 16) & 0xFFFF

    enabled = bool(msg_ctrl & (1 << 15))
    func_mask = bool(msg_ctrl & (1 << 14))
    table_size = (msg_ctrl & 0x7FF) + 1

    table_offset_bir = _reg(base + 0x04, reg_map)
    table_bir = table_offset_bir & 0x7
    table_offset = table_offset_bir & ~0x7

    pba_offset_bir = _reg(base + 0x08, reg_map)
    pba_bir = pba_offset_bir & 0x7
    pba_offset = pba_offset_bir & ~0x7

    with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
        _kv("MSI-X Enabled", "Yes" if enabled else "No")
        _kv("Function Mask", "Yes" if func_mask else "No")
        _kv("Table Size", str(table_size))
        _kv("Table BAR", f"BAR{table_bir}")
        _kv("Table Offset", f"0x{table_offset:X}")
        _kv("PBA BAR", f"BAR{pba_bir}")
        _kv("PBA Offset", f"0x{pba_offset:X}")


def render_pcie_cap(base: int, reg_map: dict[int, int]) -> None:
    """Decode PCI Express capability (cap_id=0x10)."""
    header = _reg(base, reg_map)
    pcie_caps = (header >> 16) & 0xFFFF
    cap_version = pcie_caps & 0xF
    dev_type = (pcie_caps >> 4) & 0xF
    slot_impl = bool(pcie_caps & (1 << 8))

    type_names = {
        0: "Endpoint",
        1: "Legacy Endpoint",
        4: "Root Port",
        5: "Upstream Switch Port",
        6: "Downstream Switch Port",
        7: "PCIe-to-PCI Bridge",
        8: "PCI-to-PCIe Bridge",
        9: "Root Complex Integrated Endpoint",
        10: "Root Complex Event Collector",
    }

    dev_cap = _reg(base + 0x04, reg_map)
    mps_code = dev_cap & 0x7
    mps = _PAYLOAD_SIZES[mps_code] if mps_code < len(_PAYLOAD_SIZES) else 0
    ext_tag = bool(dev_cap & (1 << 5))
    flr = bool(dev_cap & (1 << 28))

    link_cap = _reg(base + 0x0C, reg_map)
    max_speed = link_cap & 0xF
    max_width = (link_cap >> 4) & 0x3F
    port_num = (link_cap >> 24) & 0xFF
    aspm_code = (link_cap >> 10) & 0x3
    dll_active_rpt = bool(link_cap & (1 << 20))
    surprise_down = bool(link_cap & (1 << 19))

    link_ctl_sts = _reg(base + 0x10, reg_map)
    status_word = (link_ctl_sts >> 16) & 0xFFFF
    ctrl_word = link_ctl_sts & 0xFFFF
    cur_speed = status_word & 0xF
    cur_width = (status_word >> 4) & 0x3F
    dll_active = bool(status_word & (1 << 13))
    link_training = bool(status_word & (1 << 11))

    aspm_names = {0: "Disabled", 1: "L0s", 2: "L1", 3: "L0s+L1"}
    aspm_support = {0: "None", 1: "L0s", 2: "L1", 3: "L0s+L1"}

    with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
        _kv("Cap Version", str(cap_version))
        _kv("Device/Port Type", type_names.get(dev_type, f"Unknown({dev_type})"))
        _kv("Slot Implemented", "Yes" if slot_impl else "No")
        _kv("Port Number", str(port_num))

    ui.separator().style(f"background: {COLORS.border}")
    ui.label("Device Capabilities").style(
        f"color: {COLORS.cyan}; font-size: 12px; font-weight: bold"
    )
    with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
        _kv("MPS Supported", f"{mps} bytes")
        _kv("Ext Tag", "Yes" if ext_tag else "No")
        _kv("FLR Capable", "Yes" if flr else "No")

    ui.separator().style(f"background: {COLORS.border}")
    ui.label("Link Capabilities").style(f"color: {COLORS.cyan}; font-size: 12px; font-weight: bold")
    with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
        _kv("Max Speed", _SPEED_NAMES.get(max_speed, f"?({max_speed})"))
        _kv("Max Width", f"x{max_width}")
        _kv("ASPM Support", aspm_support.get(aspm_code, f"?({aspm_code})"))
        _kv("DLL Active Reporting", "Yes" if dll_active_rpt else "No")
        _kv("Surprise Down", "Yes" if surprise_down else "No")

    ui.separator().style(f"background: {COLORS.border}")
    ui.label("Link Status").style(f"color: {COLORS.cyan}; font-size: 12px; font-weight: bold")
    with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
        _kv("Current Speed", _SPEED_NAMES.get(cur_speed, f"?({cur_speed})"))
        _kv("Current Width", f"x{cur_width}")
        _kv("DLL Active", "Yes" if dll_active else "No")
        _kv("Link Training", "Yes" if link_training else "No")
        _kv("ASPM Control", aspm_names.get(ctrl_word & 0x3, "?"))

    dev_cap2 = _reg(base + 0x24, reg_map)
    link_cap2 = _reg(base + 0x2C, reg_map)
    if dev_cap2 != 0xFFFFFFFF:
        ui.separator().style(f"background: {COLORS.border}")
        ui.label("Device Capabilities 2").style(
            f"color: {COLORS.cyan}; font-size: 12px; font-weight: bold"
        )
        with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
            cto_ranges = dev_cap2 & 0xF
            _kv("Completion Timeout Ranges", f"0x{cto_ranges:X}")
            _kv("CTO Disable", "Yes" if dev_cap2 & (1 << 4) else "No")
            _kv("ARI Forwarding", "Yes" if dev_cap2 & (1 << 5) else "No")
            _kv("AtomicOp Routing", "Yes" if dev_cap2 & (1 << 6) else "No")
            _kv("LTR Supported", "Yes" if dev_cap2 & (1 << 11) else "No")
            _kv("10-Bit Tag Completer", "Yes" if dev_cap2 & (1 << 16) else "No")
            _kv("10-Bit Tag Requester", "Yes" if dev_cap2 & (1 << 17) else "No")

    if link_cap2 != 0xFFFFFFFF:
        ui.separator().style(f"background: {COLORS.border}")
        ui.label("Link Capabilities 2").style(
            f"color: {COLORS.cyan}; font-size: 12px; font-weight: bold"
        )
        speed_vec = (link_cap2 >> 1) & 0x7F
        supported = []
        for bit, name in enumerate(["Gen1", "Gen2", "Gen3", "Gen4", "Gen5", "Gen6"], start=0):
            if speed_vec & (1 << bit):
                supported.append(name)
        with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
            _kv("Supported Speeds", ", ".join(supported) if supported else "None")
            _kv("Crosslink Supported", "Yes" if link_cap2 & (1 << 8) else "No")
            _kv("DRS Supported", "Yes" if link_cap2 & (1 << 31) else "No")

        link_ctl2_sts2 = _reg(base + 0x30, reg_map)
        if link_ctl2_sts2 != 0xFFFFFFFF:
            target_speed = link_ctl2_sts2 & 0xF
            sts2 = (link_ctl2_sts2 >> 16) & 0xFFFF
            _kv("Target Speed", _SPEED_NAMES.get(target_speed, f"?({target_speed})"))
            _kv("Flit Mode Status", "Active" if sts2 & (1 << 10) else "Inactive")


# ---------------------------------------------------------------------------
# Extended capabilities
# ---------------------------------------------------------------------------


def render_aer(base: int, reg_map: dict[int, int]) -> None:
    """Decode AER extended capability (ext_cap_id=0x0001)."""
    uncorr = _reg(base + 0x04, reg_map)
    uncorr_mask = _reg(base + 0x08, reg_map)
    uncorr_sev = _reg(base + 0x0C, reg_map)
    corr = _reg(base + 0x10, reg_map)
    corr_mask = _reg(base + 0x14, reg_map)
    cap_ctl = _reg(base + 0x18, reg_map)
    first_err = cap_ctl & 0x1F
    ecrc_gen_cap = bool(cap_ctl & (1 << 5))
    ecrc_gen_en = bool(cap_ctl & (1 << 6))
    ecrc_chk_cap = bool(cap_ctl & (1 << 7))
    ecrc_chk_en = bool(cap_ctl & (1 << 8))

    header_log = [_reg(base + 0x1C + i * 4, reg_map) for i in range(4)]

    with ui.row().classes("w-full gap-4"):
        with ui.column().classes("flex-1"):
            ui.label(f"Uncorrectable Status (0x{uncorr:08X})").style(
                f"color: {COLORS.text_primary}; font-size: 13px"
            )
            uncorr_fields = [
                (4, "Data Link Protocol"),
                (5, "Surprise Down"),
                (12, "Poisoned TLP"),
                (13, "Flow Control Protocol"),
                (14, "Completion Timeout"),
                (15, "Completer Abort"),
                (16, "Unexpected Completion"),
                (17, "Receiver Overflow"),
                (18, "Malformed TLP"),
                (19, "ECRC Error"),
                (20, "Unsupported Request"),
                (21, "ACS Violation"),
                (22, "Internal Error"),
            ]
            for bit, name in uncorr_fields:
                active = bool(uncorr & (1 << bit))
                masked = bool(uncorr_mask & (1 << bit))
                fatal = bool(uncorr_sev & (1 << bit))
                color = COLORS.red if active else COLORS.text_muted
                suffix = ""
                if active:
                    suffix = f" ({'Fatal' if fatal else 'Non-Fatal'})"
                elif masked:
                    suffix = " (masked)"
                ui.label(f"{'!!' if active else '  '} {name}{suffix}").style(
                    f"color: {color}; font-family: monospace; font-size: 12px"
                )

        with ui.column().classes("flex-1"):
            ui.label(f"Correctable Status (0x{corr:08X})").style(
                f"color: {COLORS.text_primary}; font-size: 13px"
            )
            corr_fields = [
                (0, "Receiver Error"),
                (6, "Bad TLP"),
                (7, "Bad DLLP"),
                (8, "Replay Num Rollover"),
                (12, "Replay Timer Timeout"),
                (13, "Advisory Non-Fatal"),
                (14, "Corrected Internal"),
                (15, "Header Log Overflow"),
            ]
            for bit, name in corr_fields:
                active = bool(corr & (1 << bit))
                masked = bool(corr_mask & (1 << bit))
                color = COLORS.yellow if active else COLORS.text_muted
                suffix = " (masked)" if masked and not active else ""
                ui.label(f"{'!!' if active else '  '} {name}{suffix}").style(
                    f"color: {color}; font-family: monospace; font-size: 12px"
                )

    ui.separator().style(f"background: {COLORS.border}")
    with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
        _kv("First Error Pointer", str(first_err))
        _kv(
            "ECRC Generation",
            f"{'Capable' if ecrc_gen_cap else 'N/A'}{', Enabled' if ecrc_gen_en else ''}",
        )
        _kv(
            "ECRC Check",
            f"{'Capable' if ecrc_chk_cap else 'N/A'}{', Enabled' if ecrc_chk_en else ''}",
        )

    if any(h != 0 for h in header_log):
        ui.label("Header Log: " + " ".join(f"0x{h:08X}" for h in header_log)).style(
            f"color: {COLORS.text_secondary}; font-family: monospace; font-size: 12px"
        )


def render_serial_number(base: int, reg_map: dict[int, int]) -> None:
    """Decode Device Serial Number (ext_cap_id=0x0003)."""
    lo = _reg(base + 0x04, reg_map)
    hi = _reg(base + 0x08, reg_map)
    sn = (hi << 32) | lo
    # Format as standard XX-XX-XX-XX-XX-XX-XX-XX
    parts = [(sn >> (i * 8)) & 0xFF for i in range(7, -1, -1)]
    formatted = "-".join(f"{b:02X}" for b in parts)
    with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
        _kv("Serial Number", formatted)
        _kv("Raw", f"0x{hi:08X}_{lo:08X}")


def render_vc(base: int, reg_map: dict[int, int]) -> None:
    """Decode Virtual Channel (ext_cap_id=0x0002)."""
    cap1 = _reg(base + 0x04, reg_map)
    vc_ctl_sts = _reg(base + 0x0C, reg_map)
    ctrl = vc_ctl_sts & 0xFFFF
    status = (vc_ctl_sts >> 16) & 0xFFFF

    ext_vc_count = cap1 & 0x7
    lp_ext_vc_count = (cap1 >> 4) & 0x7
    ref_clock = (cap1 >> 8) & 0x3
    arb_table_size = (cap1 >> 24) & 0xFF

    with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
        _kv("Extended VC Count", str(ext_vc_count))
        _kv("LP Extended VC Count", str(lp_ext_vc_count))
        _kv("Reference Clock", f"{ref_clock}")
        _kv("Arb Table Entry Size", f"{arb_table_size}")
        _kv("VC Arb Select", f"0x{ctrl & 0x7:X}")
        _kv("VC Arb Table Status", "Valid" if status & 1 else "Invalid")


def render_acs(base: int, reg_map: dict[int, int]) -> None:
    """Decode ACS (ext_cap_id=0x000D)."""
    cap_ctrl = _reg(base + 0x04, reg_map)
    cap = cap_ctrl & 0xFFFF
    ctrl = (cap_ctrl >> 16) & 0xFFFF

    fields = [
        (0, "Source Validation"),
        (1, "Translation Blocking"),
        (2, "P2P Request Redirect"),
        (3, "P2P Completion Redirect"),
        (4, "Upstream Forwarding"),
        (5, "P2P Egress Control"),
        (6, "Direct Translated P2P"),
    ]
    ui.label("Capability / Control").style(f"color: {COLORS.text_primary}; font-size: 13px")
    for bit, name in fields:
        capable = bool(cap & (1 << bit))
        enabled = bool(ctrl & (1 << bit))
        if capable:
            color = COLORS.cyan if enabled else COLORS.text_secondary
            status = "Enabled" if enabled else "Capable"
        else:
            color = COLORS.text_muted
            status = "N/A"
        ui.label(f"  {name}: {status}").style(
            f"color: {color}; font-family: monospace; font-size: 12px"
        )


def render_ari(base: int, reg_map: dict[int, int]) -> None:
    """Decode ARI (ext_cap_id=0x000E)."""
    cap_ctrl = _reg(base + 0x04, reg_map)
    cap = cap_ctrl & 0xFFFF
    ctrl = (cap_ctrl >> 16) & 0xFFFF
    next_fn = (cap >> 8) & 0xFF

    with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
        _kv("MFVC Group Cap", "Yes" if cap & 1 else "No")
        _kv("ACS Group Cap", "Yes" if cap & 2 else "No")
        _kv("Next Function", str(next_fn))
        _kv("MFVC Group Enable", "Yes" if ctrl & 1 else "No")
        _kv("ACS Group Enable", "Yes" if ctrl & 2 else "No")
        _kv("Function Group", str((ctrl >> 4) & 0x7))


def render_dpc(base: int, reg_map: dict[int, int]) -> None:
    """Decode DPC (ext_cap_id=0x001D)."""
    cap = _reg(base + 0x04, reg_map)
    dpc_cap = cap & 0xFFFF
    dpc_ctl = (cap >> 16) & 0xFFFF

    status_raw = _reg(base + 0x08, reg_map)
    dpc_status = status_raw & 0xFFFF

    trigger = bool(dpc_status & (1 << 0))
    trigger_reason = (dpc_status >> 1) & 0x3
    reason_names = {
        0: "Unmasked uncorrectable",
        1: "ERR_NONFATAL received",
        2: "ERR_FATAL received",
        3: "In-band (RP PIO)",
    }
    int_status = bool(dpc_status & (1 << 3))
    rp_busy = bool(dpc_status & (1 << 4))

    with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
        _kv("INT Message", str(dpc_cap & 0x1F))
        _kv("RP Extensions", "Yes" if dpc_cap & (1 << 5) else "No")
        _kv("Poisoned TLP Egress Block", "Yes" if dpc_cap & (1 << 6) else "No")
        _kv("Software Trigger", "Yes" if dpc_cap & (1 << 7) else "No")
        _kv("DL Active ERR_COR", "Yes" if dpc_cap & (1 << 12) else "No")

    ui.separator().style(f"background: {COLORS.border}")
    with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
        trigger_en = (dpc_ctl >> 1) & 0x3
        trigger_names = {0: "Disabled", 1: "ERR_FATAL", 2: "ERR_NONFATAL", 3: "Both"}
        _kv("Trigger Enable", trigger_names.get(trigger_en, f"?({trigger_en})"))
        _kv("Completion Control", "ERR_ABRT" if dpc_ctl & (1 << 4) else "UR")
        _kv("INT Enable", "Yes" if dpc_ctl & (1 << 3) else "No")

    ui.separator().style(f"background: {COLORS.border}")
    trig_color = COLORS.red if trigger else COLORS.text_muted
    ui.label(
        f"{'!!' if trigger else '  '} Trigger Status: {'TRIGGERED' if trigger else 'Clear'}"
    ).style(f"color: {trig_color}; font-family: monospace; font-size: 13px")
    if trigger:
        with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
            _kv("Reason", reason_names.get(trigger_reason, f"?({trigger_reason})"))
            _kv("INT Status", "Pending" if int_status else "Clear")
            _kv("RP Busy", "Yes" if rp_busy else "No")


def render_ltr(base: int, reg_map: dict[int, int]) -> None:
    """Decode LTR (ext_cap_id=0x0018)."""
    max_snoop = _reg(base + 0x04, reg_map)
    snoop_val = max_snoop & 0x3FF
    snoop_scale = (max_snoop >> 10) & 0x7
    no_snoop_val = (max_snoop >> 16) & 0x3FF
    no_snoop_scale = (max_snoop >> 26) & 0x7

    scale_ns = {0: 1, 1: 32, 2: 1024, 3: 32768, 4: 1048576, 5: 33554432}

    def _format_latency(val: int, sc: int) -> str:
        ns = val * scale_ns.get(sc, 1)
        if ns >= 1_000_000:
            return f"{ns / 1_000_000:.1f} ms"
        if ns >= 1000:
            return f"{ns / 1000:.1f} us"
        return f"{ns} ns"

    with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
        _kv("Max Snoop Latency", _format_latency(snoop_val, snoop_scale))
        _kv("Max No-Snoop Latency", _format_latency(no_snoop_val, no_snoop_scale))


def render_secondary_pcie(base: int, reg_map: dict[int, int]) -> None:
    """Decode Secondary PCIe (ext_cap_id=0x0019)."""
    link_ctl3 = _reg(base + 0x04, reg_map)
    lane_err_sts = _reg(base + 0x08, reg_map)

    perf_eq = bool(link_ctl3 & (1 << 0))
    eq_int_en = bool(link_ctl3 & (1 << 1))

    with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
        _kv("Perform Equalization", "Yes" if perf_eq else "No")
        _kv("EQ Request INT Enable", "Yes" if eq_int_en else "No")
        if lane_err_sts:
            error_lanes = [i for i in range(32) if lane_err_sts & (1 << i)]
            _kv(
                "Lane Error Status",
                ", ".join(str(ln) for ln in error_lanes) if error_lanes else "Clear",
            )
        else:
            _kv("Lane Error Status", "Clear")


def render_data_link_feature(base: int, reg_map: dict[int, int]) -> None:
    """Decode Data Link Feature (ext_cap_id=0x0025)."""
    cap = _reg(base + 0x04, reg_map)
    status = _reg(base + 0x08, reg_map)

    scaled_fc = bool(cap & (1 << 0))
    exchange_credit = bool(cap & (1 << 1))

    remote_scaled_fc = bool(status & (1 << 0))
    valid = bool(status & (1 << 31))

    with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
        _kv("Scaled Flow Control", "Supported" if scaled_fc else "No")
        _kv("Exchange Credit Limit", "Supported" if exchange_credit else "No")
        _kv("Remote Scaled FC", "Yes" if remote_scaled_fc else "No")
        _kv("Remote Valid", "Yes" if valid else "No")


def render_physical_16gt(base: int, reg_map: dict[int, int]) -> None:
    """Decode Physical Layer 16.0 GT/s (ext_cap_id=0x0026)."""
    status_reg = _reg(base + 0x0C, reg_map)

    with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
        _kv("EQ Complete", "Yes" if status_reg & 1 else "No")
        _kv("Phase 1 Success", "Yes" if status_reg & 2 else "No")
        _kv("Phase 2 Success", "Yes" if status_reg & 4 else "No")
        _kv("Phase 3 Success", "Yes" if status_reg & 8 else "No")
        _kv("Link EQ Request", "Yes" if status_reg & 0x10 else "No")


def render_physical_32gt(base: int, reg_map: dict[int, int]) -> None:
    """Decode Physical Layer 32.0 GT/s (ext_cap_id=0x002A)."""
    cap_reg = _reg(base + 0x04, reg_map)
    status_reg = _reg(base + 0x0C, reg_map)

    with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
        _kv("EQ Bypass to Highest", "Yes" if cap_reg & 1 else "No")
        _kv("No EQ Needed", "Yes" if cap_reg & 2 else "No")
        _kv("Modified TS Usage Mode", str((cap_reg >> 8) & 0x7))

    ui.separator().style(f"background: {COLORS.border}")
    with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
        _kv("EQ Complete", "Yes" if status_reg & 1 else "No")
        _kv("Phase 1 Success", "Yes" if status_reg & 2 else "No")
        _kv("Phase 2 Success", "Yes" if status_reg & 4 else "No")
        _kv("Phase 3 Success", "Yes" if status_reg & 8 else "No")
        _kv("EQ Request", "Yes" if status_reg & 0x10 else "No")
        _kv("Modified TS Received", "Yes" if status_reg & 0x20 else "No")
        _kv("Rx Lane Margin Capable", "Yes" if status_reg & 0x40 else "No")
        _kv("Rx Lane Margin Status", "Ready" if status_reg & 0x80 else "Not Ready")


def render_physical_64gt(base: int, reg_map: dict[int, int]) -> None:
    """Decode Physical Layer 64.0 GT/s (ext_cap_id=0x0031)."""
    cap_reg = _reg(base + 0x04, reg_map)
    status_reg = _reg(base + 0x0C, reg_map)

    with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
        _kv("Flit Mode Supported", "Yes" if cap_reg & 1 else "No")
        _kv("No EQ Needed", "Yes" if cap_reg & 2 else "No")

    ui.separator().style(f"background: {COLORS.border}")
    with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
        _kv("EQ Complete", "Yes" if status_reg & 1 else "No")
        _kv("Phase 1 Success", "Yes" if status_reg & 2 else "No")
        _kv("Phase 2 Success", "Yes" if status_reg & 4 else "No")
        _kv("Phase 3 Success", "Yes" if status_reg & 8 else "No")
        _kv("EQ Request", "Yes" if status_reg & 0x10 else "No")


def render_ptm(base: int, reg_map: dict[int, int]) -> None:
    """Decode PTM (ext_cap_id=0x001F)."""
    cap = _reg(base + 0x04, reg_map)
    ctrl = _reg(base + 0x08, reg_map)

    requester = bool(cap & (1 << 0))
    responder = bool(cap & (1 << 1))
    root = bool(cap & (1 << 2))
    local_granularity = (cap >> 8) & 0xFF

    enabled = bool(ctrl & (1 << 0))
    root_select = bool(ctrl & (1 << 1))
    eff_granularity = (ctrl >> 8) & 0xFF

    with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
        _kv("Requester Capable", "Yes" if requester else "No")
        _kv("Responder Capable", "Yes" if responder else "No")
        _kv("Root Capable", "Yes" if root else "No")
        _kv(
            "Local Clock Granularity", f"{local_granularity} ns" if local_granularity else "Unknown"
        )
        _kv("PTM Enabled", "Yes" if enabled else "No")
        _kv("Root Selected", "Yes" if root_select else "No")
        _kv("Effective Granularity", f"{eff_granularity} ns" if eff_granularity else "Unknown")


def render_l1_pm_substates(base: int, reg_map: dict[int, int]) -> None:
    """Decode L1 PM Substates (ext_cap_id=0x001E)."""
    cap = _reg(base + 0x04, reg_map)
    ctrl1 = _reg(base + 0x08, reg_map)

    with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
        _kv("PCI-PM L1.2", "Supported" if cap & 1 else "No")
        _kv("PCI-PM L1.1", "Supported" if cap & 2 else "No")
        _kv("ASPM L1.2", "Supported" if cap & 4 else "No")
        _kv("ASPM L1.1", "Supported" if cap & 8 else "No")
        _kv("L1 PM Substates", "Supported" if cap & 0x10 else "No")

    ui.separator().style(f"background: {COLORS.border}")
    with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
        _kv("PCI-PM L1.2 Enable", "Yes" if ctrl1 & 1 else "No")
        _kv("PCI-PM L1.1 Enable", "Yes" if ctrl1 & 2 else "No")
        _kv("ASPM L1.2 Enable", "Yes" if ctrl1 & 4 else "No")
        _kv("ASPM L1.1 Enable", "Yes" if ctrl1 & 8 else "No")


def render_lane_margining(base: int, reg_map: dict[int, int]) -> None:
    """Decode Lane Margining at Receiver (ext_cap_id=0x0027)."""
    port_cap = _reg(base + 0x04, reg_map)
    port_status = _reg(base + 0x08, reg_map)

    margining_ready = bool(port_status & (1 << 0))
    software_ready = bool(port_status & (1 << 1))

    with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
        _kv("Margining Uses Driver SW", "Yes" if port_cap & 1 else "No")
        _kv("Margining Ready", "Yes" if margining_ready else "No")
        _kv("Software Ready", "Yes" if software_ready else "No")

    ui.label("(Detailed margining on Lane Margining page)").style(
        f"color: {COLORS.text_muted}; font-size: 12px; font-style: italic"
    )


def render_vendor_specific(base: int, reg_map: dict[int, int]) -> None:
    """Decode Vendor Specific capability."""
    header = _reg(base, reg_map)
    if base >= 0x100:
        dw1 = _reg(base + 0x04, reg_map)
        vsec_id = dw1 & 0xFFFF
        vsec_rev = (dw1 >> 16) & 0xF
        vsec_len = (dw1 >> 20) & 0xFFF
        with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
            _kv("VSEC ID", f"0x{vsec_id:04X}")
            _kv("VSEC Revision", str(vsec_rev))
            _kv("VSEC Length", f"{vsec_len} bytes")
    else:
        length = (header >> 16) & 0xFF
        with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
            _kv("Length", f"{length} bytes")
            data1 = _reg(base + 0x04, reg_map)
            _kv("Data[0]", f"0x{data1:08X}")


def render_dvsec(base: int, reg_map: dict[int, int]) -> None:
    """Decode DVSEC (ext_cap_id=0x0023)."""
    dw1 = _reg(base + 0x04, reg_map)
    dw2 = _reg(base + 0x08, reg_map)

    dvsec_vendor = dw1 & 0xFFFF
    dvsec_rev = (dw1 >> 16) & 0xF
    dvsec_len = (dw1 >> 20) & 0xFFF
    dvsec_id = dw2 & 0xFFFF

    with ui.grid(columns=2).classes("gap-x-4 gap-y-1"):
        _kv("DVSEC Vendor ID", f"0x{dvsec_vendor:04X}")
        _kv("DVSEC ID", f"0x{dvsec_id:04X}")
        _kv("DVSEC Revision", str(dvsec_rev))
        _kv("DVSEC Length", f"{dvsec_len} bytes")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

# Standard capability renderers: cap_id -> render_fn(base, reg_map)
_STD_RENDERERS: dict[int, object] = {
    0x01: render_power_management,
    0x05: render_msi,
    0x10: render_pcie_cap,
    0x11: render_msix,
    0x09: render_vendor_specific,
}

# Extended capability renderers: cap_id -> render_fn(base, reg_map)
_EXT_RENDERERS: dict[int, object] = {
    0x0001: render_aer,
    0x0002: render_vc,
    0x0003: render_serial_number,
    0x000B: render_vendor_specific,
    0x000D: render_acs,
    0x000E: render_ari,
    0x0018: render_ltr,
    0x0019: render_secondary_pcie,
    0x001D: render_dpc,
    0x001E: render_l1_pm_substates,
    0x001F: render_ptm,
    0x0023: render_dvsec,
    0x0025: render_data_link_feature,
    0x0026: render_physical_16gt,
    0x0027: render_lane_margining,
    0x002A: render_physical_32gt,
    0x0031: render_physical_64gt,
}


def render_capability(cap: dict, reg_map: dict[int, int]) -> bool:
    """Render a decoded capability detail if a renderer is available.

    Args:
        cap: Capability dict with 'cap_id', 'offset', etc.
        reg_map: Offset -> value mapping for all registers.

    Returns:
        True if a specific renderer handled this capability, False otherwise.
    """
    cap_id = cap["cap_id"]
    base = cap["offset"]
    is_extended = base >= 0x100

    if is_extended:
        renderer = _EXT_RENDERERS.get(cap_id)
    else:
        renderer = _STD_RENDERERS.get(cap_id)

    if renderer is None:
        return False

    renderer(base, reg_map)
    return True
