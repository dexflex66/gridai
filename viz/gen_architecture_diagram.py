#!/usr/bin/env python3
"""Generate GridAI architecture diagram PNG for README."""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np
import os

OUT = os.path.join(os.path.dirname(__file__), "screenshots", "gridai_architecture.png")

# ── colour palette ──────────────────────────────────────────────────
BG          = "#0D1117"
PANEL_BG    = "#161B22"
LAYER_BG    = "#1C2333"
ELECTRIC    = "#58A6FF"
AMBER       = "#F0A030"
WHITE       = "#E6EDF3"
DIM         = "#8B949E"
GREEN       = "#3FB950"
RED_SOFT    = "#F85149"
SHIELD_BG   = "#0E2A1E"
SHIELD_BD   = "#238636"
REPAIR_BG   = "#2A1A0E"
REPAIR_BD   = "#D29922"
INPUT_BG    = "#0D1B2A"
INPUT_BD    = "#1F6FEB"
OUTPUT_BG   = "#0D1B2A"
OUTPUT_BD   = "#1F6FEB"
AGENT_BG    = "#161B22"
AGENT_BD    = "#58A6FF"

DPI = 180
FIG_W, FIG_H = 18, 22

fig, ax = plt.subplots(figsize=(FIG_W, FIG_H), dpi=DPI)
fig.patch.set_facecolor(BG)
ax.set_facecolor(BG)
ax.set_xlim(0, FIG_W)
ax.set_ylim(0, FIG_H)
ax.axis("off")

# ── helpers ──────────────────────────────────────────────────────────
def draw_rounded_box(x, y, w, h, fc, ec, lw=1.5, alpha=1.0, zorder=2):
    box = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.15",
                         facecolor=fc, edgecolor=ec, linewidth=lw,
                         alpha=alpha, zorder=zorder)
    ax.add_patch(box)
    return box

def text(x, y, s, fontsize=11, color=WHITE, weight="normal", ha="center", va="center", zorder=5, fontstyle="normal"):
    return ax.text(x, y, s, fontsize=fontsize, color=color, weight=weight,
                   ha=ha, va=va, zorder=zorder, fontfamily="Helvetica Neue",
                   fontstyle=fontstyle)

def arrow_down(x, y1, y2, color=ELECTRIC, lw=2.0):
    ax.annotate("", xy=(x, y2), xytext=(x, y1),
                arrowprops=dict(arrowstyle="-|>", color=color, lw=lw),
                zorder=3)

def layer_label(x, y, label, color=ELECTRIC):
    text(x, y, label, fontsize=13, color=color, weight="bold", ha="left", va="center")

# ── layout constants ─────────────────────────────────────────────────
CX = FIG_W / 2
LX = 1.5
RX = FIG_W - 1.5
CONTENT_W = RX - LX

# ── TITLE ────────────────────────────────────────────────────────────
text(CX, FIG_H - 0.8, "GridAI Architecture: Fail-Closed Coordination for Home Battery Fleets",
     fontsize=20, color=WHITE, weight="bold")
text(CX, FIG_H - 1.5, "Priority-based multi-agent dispatch with voltage/SOC/kW-position validation",
     fontsize=13, color=DIM)

# Tagline
tagline_y = FIG_H - 2.4
draw_rounded_box(CX - 3.5, tagline_y - 0.35, 7, 0.7, SHIELD_BG, SHIELD_BD, lw=2, zorder=4)
text(CX, tagline_y, "Agents propose.  Physics decides.", fontsize=15, color=GREEN, weight="bold")

# ── LAYER 1 — Inputs / Grid World ───────────────────────────────────
L1_TOP = FIG_H - 3.5
L1_H = 2.8
L1_BOT = L1_TOP - L1_H
draw_rounded_box(LX, L1_BOT, CONTENT_W, L1_H, INPUT_BG, INPUT_BD, lw=2)
layer_label(LX + 0.4, L1_TOP - 0.4, "LAYER 1  —  INPUTS / GRID WORLD", color=ELECTRIC)

inputs = [
    ("AEMO-style\nload / tariff signal", "⚡"),
    ("Home battery\nfleet (N homes)", "🔋"),
    ("Feeder\npositions", "📍"),
    ("Voltage\nlimits", "📏"),
    ("SOC\nlimits", "📊"),
]
iw = 2.8
igap = 0.35
total_iw = len(inputs) * iw + (len(inputs) - 1) * igap
ix_start = CX - total_iw / 2
iy = L1_BOT + L1_H / 2 - 0.3

for i, (label, icon) in enumerate(inputs):
    bx = ix_start + i * (iw + igap)
    draw_rounded_box(bx, iy - 0.6, iw, 1.2, PANEL_BG, INPUT_BD, lw=1.2)
    text(bx + iw / 2, iy, label, fontsize=10, color=WHITE, weight="normal")

# ── Arrow L1 → L2 ──────────────────────────────────────────────────
arrow_down(CX, L1_BOT, L1_BOT - 0.5, ELECTRIC, 2.5)

# ── LAYER 2 — Multi-Agent Coordination ──────────────────────────────
L2_TOP = L1_BOT - 0.6
L2_H = 3.2
L2_BOT = L2_TOP - L2_H
draw_rounded_box(LX, L2_BOT, CONTENT_W, L2_H, LAYER_BG, ELECTRIC, lw=2)
layer_label(LX + 0.4, L2_TOP - 0.4, "LAYER 2  —  MULTI-AGENT COORDINATION", color=ELECTRIC)

agents = [
    ("Forecaster\nAgent", "Load / price /\nrisk windows", ELECTRIC),
    ("Coordinator\nAgent", "Priority-based\ndispatch slots", AMBER),
    ("Compliance\nAgent", "Voltage, SOC &\nkW-position checks", GREEN),
    ("Operator\nAgent", "Schedule, alerts &\nresidual risk", DIM),
]
aw = 3.2
agap = 0.5
total_aw = len(agents) * aw + (len(agents) - 1) * agap
ax_start = CX - total_aw / 2
ay = L2_BOT + L2_H / 2 + 0.1

for i, (name, desc, accent) in enumerate(agents):
    bx = ax_start + i * (aw + agap)
    draw_rounded_box(bx, ay - 1.0, aw, 2.0, AGENT_BG, accent, lw=2)
    text(bx + aw / 2, ay + 0.45, name, fontsize=11, color=accent, weight="bold")
    text(bx + aw / 2, ay - 0.45, desc, fontsize=9, color=DIM)
    # small arrow between agent cards
    if i < len(agents) - 1:
        arr_x = bx + aw + agap * 0.15
        ax.annotate("", xy=(bx + aw + agap * 0.85, ay),
                    xytext=(bx + aw + agap * 0.15, ay),
                    arrowprops=dict(arrowstyle="-|>", color=DIM, lw=1.2),
                    zorder=3)

# ── Arrow L2 → L3 ──────────────────────────────────────────────────
arrow_down(CX, L2_BOT, L2_BOT - 0.5, AMBER, 2.5)

# ── LAYER 3 — Physical Safety Gate ──────────────────────────────────
L3_TOP = L2_BOT - 0.6
L3_H = 3.0
L3_BOT = L3_TOP - L3_H
draw_rounded_box(LX, L3_BOT, CONTENT_W, L3_H, SHIELD_BG, SHIELD_BD, lw=2.5)
layer_label(LX + 0.4, L3_TOP - 0.4, "LAYER 3  —  PHYSICAL SAFETY GATE  [SHIELD]", color=GREEN)

validations = [
    "Overvoltage\nvalidation",
    "Undervoltage\nvalidation",
    "Position-aware\nkW validation",
    "SOC / energy\nvalidation",
    "Final invariant\ncheck",
]
vw = 2.6
vgap = 0.3
total_vw = len(validations) * vw + (len(validations) - 1) * vgap
vx_start = CX - total_vw / 2
vy = L3_BOT + L3_H / 2 - 0.2

for i, label in enumerate(validations):
    bx = vx_start + i * (vw + vgap)
    draw_rounded_box(bx, vy - 0.55, vw, 1.1, "#0A1F14", SHIELD_BD, lw=1.2)
    text(bx + vw / 2, vy, label, fontsize=9.5, color=GREEN, weight="normal")

# ── Arrow L3 → L4 ──────────────────────────────────────────────────
arrow_down(CX, L3_BOT, L3_BOT - 0.5, RED_SOFT, 2.5)

# ── LAYER 4 — Bounded Repair / Fail-Closed ──────────────────────────
L4_TOP = L3_BOT - 0.6
L4_H = 2.8
L4_BOT = L4_TOP - L4_H
draw_rounded_box(LX, L4_BOT, CONTENT_W, L4_H, REPAIR_BG, REPAIR_BD, lw=2.5)
layer_label(LX + 0.4, L4_TOP - 0.4, "LAYER 4  —  BOUNDED REPAIR / FAIL-CLOSED", color=AMBER)

repairs = [
    "Reallocate existing\ndischarge only",
    "Donor-removal\nsafety check",
    "UV\nsafe-stop",
    "No invented\nenergy",
    "residual_failure\nif unsafe",
]
rw = 2.6
rgap = 0.3
total_rw = len(repairs) * rw + (len(repairs) - 1) * rgap
rx_start = CX - total_rw / 2
ry = L4_BOT + L4_H / 2 - 0.2

for i, label in enumerate(repairs):
    bx = rx_start + i * (rw + rgap)
    is_fail = "residual_failure" in label
    fc = "#1A0A0A" if is_fail else "#1A150A"
    ec = RED_SOFT if is_fail else REPAIR_BD
    tc = RED_SOFT if is_fail else AMBER
    draw_rounded_box(bx, ry - 0.55, rw, 1.1, fc, ec, lw=1.2)
    text(bx + rw / 2, ry, label, fontsize=9.5, color=tc, weight="bold" if is_fail else "normal")

# ── Arrow L4 → L5 ──────────────────────────────────────────────────
arrow_down(CX, L4_BOT, L4_BOT - 0.5, ELECTRIC, 2.5)

# ── LAYER 5 — Outputs / Proof ───────────────────────────────────────
L5_TOP = L4_BOT - 0.6
L5_H = 2.8
L5_BOT = L5_TOP - L5_H
draw_rounded_box(LX, L5_BOT, CONTENT_W, L5_H, OUTPUT_BG, OUTPUT_BD, lw=2)
layer_label(LX + 0.4, L5_TOP - 0.4, "LAYER 5  —  OUTPUTS / PROOF", color=ELECTRIC)

outputs = [
    ("Validated dispatch\nschedule", GREEN),
    ("Operator alert /\nreport", AMBER),
    ("Validation metrics\ntable", ELECTRIC),
    ("Proof: OV, UV, KWpos,\nSOC, synchrony, fragmentation", DIM),
]
ow = 3.2
ogap = 0.5
total_ow = len(outputs) * ow + (len(outputs) - 1) * ogap
ox_start = CX - total_ow / 2
oy = L5_BOT + L5_H / 2 - 0.2

for i, (label, accent) in enumerate(outputs):
    bx = ox_start + i * (ow + ogap)
    draw_rounded_box(bx, oy - 0.55, ow, 1.1, PANEL_BG, accent, lw=1.2)
    text(bx + ow / 2, oy, label, fontsize=9.5, color=accent)

# ── Proof strip ─────────────────────────────────────────────────────
strip_y = L5_BOT - 0.7
draw_rounded_box(LX + 1, strip_y - 0.3, CONTENT_W - 2, 0.6, PANEL_BG, DIM, lw=1)
text(CX, strip_y,
     "Validation proof: 89 tests passing  |  OV/UV/KWpos reported  |  residual risk disclosed  |  fail-closed if unsafe",
     fontsize=10, color=DIM, weight="normal")

# ── Save ─────────────────────────────────────────────────────────────
fig.savefig(OUT, dpi=DPI, bbox_inches="tight", facecolor=BG, edgecolor="none",
            pad_inches=0.3)
plt.close(fig)
sz_mb = os.path.getsize(OUT) / 1e6
print(f"Saved {OUT}  ({sz_mb:.1f} MB)")