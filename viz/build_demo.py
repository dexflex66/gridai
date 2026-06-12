#!/usr/bin/env python3
"""
Build the self-contained GridAI hackathon demo HTML.
Reads outputs/ JSON, extracts a compact bundle, inlines it as const DATA = {...}
in viz/gridai_demo.html.

Run:  python3 viz/build_demo.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUTS = os.path.join(ROOT, "outputs")
VIZ = os.path.dirname(os.path.abspath(__file__))


def load(name):
    path = os.path.join(OUTPUTS, name)
    with open(path) as f:
        return json.load(f)


def compact_audit(raw_audit, strategy):
    """Strip payloads down to one-line summaries."""
    result = []
    for entry in raw_audit:
        step = entry["step"]
        ts = entry["timestamp"][:19].replace("T", " ")
        sender = entry["sender"]
        recipient = entry["recipient"]
        msg_type = entry["message_type"]
        payload = entry.get("payload", {})

        if msg_type == "register":
            summary = f"register capabilities: {payload.get('capabilities', [])}"
        elif msg_type == "handoff:risk_window":
            summary = (
                f"risk_level={payload.get('risk_level','?')} "
                f"peak_synchrony={payload.get('peak_synchrony_fraction','?')} "
                f"herding_overvolt={payload.get('herding_overvolt_event_count','?')}"
            )
        elif msg_type == "handoff:dispatch_plan_and_trajectory":
            rw = payload.get("risk_window", {}) or {}
            summary = (
                f"risk_level={rw.get('risk_level','?')} "
                f"synchrony={rw.get('peak_synchrony_fraction','?')}"
            )
        elif msg_type in ("handoff:compliance_escalation", "compliance_approval"):
            summary = (
                f"decision={payload.get('compliance_decision','?')} "
                f"herding_overvolt={payload.get('herding_overvolt_event_count','?')} "
                f"reason={payload.get('reason','?')[:80]}"
            )
        elif msg_type == "operator_decision":
            summary = (
                f"operator_decision={payload.get('operator_decision','?')} "
                f"finding={payload.get('compliance_finding','?')}"
            )
        else:
            summary = str(payload)[:80]

        result.append(
            {
                "step": step,
                "timestamp": ts,
                "sender": sender,
                "recipient": recipient,
                "message_type": msg_type,
                "summary": summary,
            }
        )
    return result


def build_scenario_bundle(scenario_data, audit_data, compliance_data):
    n = scenario_data["n_homes"]
    positions = scenario_data["home_positions"]

    # Sparse dispatch: for each step, list of home indices discharging
    dispatch_series = scenario_data["dispatch_series"]
    dispatch_sparse = []
    for s in range(288):
        discharging = [h for h in range(n) if dispatch_series[h][s]]
        dispatch_sparse.append(discharging)

    # Voltage rounded to 4 decimals
    voltage = [
        [round(scenario_data["voltage_series"][h][s], 4) for s in range(288)]
        for h in range(n)
    ]

    # Demand rounded to 1 decimal
    demand = [round(v, 1) for v in scenario_data["aggregate_demand_series"]]

    # Breach events filtered to battery_herding only
    herding_breaches = [
        {
            "step": e["step"],
            "time_hhmm": e["time_hhmm"],
            "node_id": e["node_id"],
            "voltage_pu": round(e["voltage_pu"], 4),
            "band_limit_crossed": e["band_limit_crossed"],
        }
        for e in scenario_data["voltage_breach_events"]
        if e.get("cause") == "battery_herding"
    ]

    metrics = scenario_data["metrics"]

    return {
        "n_homes": n,
        "home_positions": positions,
        "dispatch": dispatch_sparse,
        "voltage": voltage,
        "demand": demand,
        "herding_breaches": herding_breaches,
        "pv_export_event_count": compliance_data.get("pv_export_event_count", 0),
        "peak_demand_kw": metrics["peak_demand_kw"],
        "max_simultaneous_discharge": metrics["max_simultaneous_discharge"],
        "synchrony_ratio": metrics["synchrony_ratio"],
        "bat_overvolt_steps": metrics["bat_overvolt_steps"],
        "audit": compact_audit(audit_data, compliance_data.get("strategy", "")),
        "compliance": {
            "decision": compliance_data["compliance_decision"],
            "reason": compliance_data["reason"],
            "risk_level": compliance_data["forecaster_risk_level"],
            "synchrony": compliance_data["coordinator_synchrony_ratio"],
            "rounds": compliance_data["coordinator_rounds_to_converge"],
            "herding_overvolt_event_count": compliance_data["herding_overvolt_event_count"],
            "pv_export_event_count": compliance_data["pv_export_event_count"],
            "pv_export_flagged_as_protocol_failure": compliance_data[
                "pv_export_flagged_as_protocol_failure"
            ],
        },
    }


def build_data_bundle():
    naive_scenario = load("scenario_naive_homogeneous_aemo.json")
    gossip_scenario = load("scenario_gossip_heterogeneous_aemo.json")
    naive_het_scenario = load("scenario_naive_heterogeneous_aemo.json")
    gossip_hom_scenario = load("scenario_gossip_homogeneous_aemo.json")

    audit_naive = load("band_audit_naive_aemo.json")
    audit_gossip = load("band_audit_gossip_aemo.json")
    comp_naive = load("compliance_decision_naive_aemo.json")
    comp_gossip = load("compliance_decision_gossip_aemo.json")

    naive_bundle = build_scenario_bundle(naive_scenario, audit_naive, comp_naive)
    gossip_bundle = build_scenario_bundle(gossip_scenario, audit_gossip, comp_gossip)

    # 3-way panel: synchrony and overvolt steps
    threeway = {
        "naive_hom": {
            "label": "Naive / Homogeneous",
            "synchrony": naive_scenario["metrics"]["synchrony_ratio"],
            "max_sim_discharge": naive_scenario["metrics"]["max_simultaneous_discharge"],
            "bat_overvolt_steps": naive_scenario["metrics"]["bat_overvolt_steps"],
            "peak_demand_kw": naive_scenario["metrics"]["peak_demand_kw"],
        },
        "gossip_hom": {
            "label": "Gossip / Homogeneous",
            "synchrony": gossip_hom_scenario["metrics"]["synchrony_ratio"],
            "max_sim_discharge": gossip_hom_scenario["metrics"]["max_simultaneous_discharge"],
            "bat_overvolt_steps": gossip_hom_scenario["metrics"]["bat_overvolt_steps"],
            "peak_demand_kw": gossip_hom_scenario["metrics"]["peak_demand_kw"],
        },
        "gossip_het": {
            "label": "Gossip / Heterogeneous",
            "synchrony": gossip_scenario["metrics"]["synchrony_ratio"],
            "max_sim_discharge": gossip_scenario["metrics"]["max_simultaneous_discharge"],
            "bat_overvolt_steps": gossip_scenario["metrics"]["bat_overvolt_steps"],
            "peak_demand_kw": gossip_scenario["metrics"]["peak_demand_kw"],
        },
        "naive_het": {
            "label": "Naive / Heterogeneous",
            "synchrony": naive_het_scenario["metrics"]["synchrony_ratio"],
            "max_sim_discharge": naive_het_scenario["metrics"]["max_simultaneous_discharge"],
            "bat_overvolt_steps": naive_het_scenario["metrics"]["bat_overvolt_steps"],
            "peak_demand_kw": naive_het_scenario["metrics"]["peak_demand_kw"],
        },
    }

    return {
        "naive": naive_bundle,
        "gossip": gossip_bundle,
        "threeway": threeway,
        "constants": {
            "STEPS": 288,
            "MIN_PU": 0.94,
            "MAX_PU": 1.10,
            "BATTERY_START": 204,
            "BATTERY_END": 260,
        },
    }


def crosscheck(bundle):
    naive = bundle["naive"]
    gossip = bundle["gossip"]

    naive_max_sim = naive["max_simultaneous_discharge"]
    gossip_max_sim = gossip["max_simultaneous_discharge"]
    naive_herding = len(naive["herding_breaches"])
    gossip_herding = len(gossip["herding_breaches"])
    naive_herding_overvolt = naive["compliance"]["herding_overvolt_event_count"]
    gossip_herding_overvolt = gossip["compliance"]["herding_overvolt_event_count"]

    print("Cross-check validation:")
    print(f"  NAIVE max_simultaneous_discharge: {naive_max_sim}  (expected 60)")
    print(f"  GOSSIP max_simultaneous_discharge: {gossip_max_sim}  (expected 10)")
    print(
        f"  NAIVE battery_herding total breach events (both bands): {naive_herding}  (expected 987)"
    )
    print(
        f"  NAIVE battery_herding OVERVOLT events (compliance): {naive_herding_overvolt}  (expected 471)"
    )
    print(
        f"  GOSSIP battery_herding total breach events: {gossip_herding}"
    )
    print(
        f"  GOSSIP battery_herding OVERVOLT events: {gossip_herding_overvolt}  (expected 0)"
    )
    print(f"  NAIVE compliance decision: {naive['compliance']['decision']}  (expected ESCALATE)")
    print(f"  GOSSIP compliance decision: {gossip['compliance']['decision']}  (expected APPROVED)")
    print(f"  NAIVE synchrony_ratio: {naive['synchrony_ratio']}  (expected 1.0)")
    print(f"  GOSSIP synchrony_ratio: {gossip['synchrony_ratio']}  (expected 0.167)")

    assert naive_max_sim == 60, f"NAIVE max_sim should be 60, got {naive_max_sim}"
    assert gossip_max_sim == 10, f"GOSSIP max_sim should be 10, got {gossip_max_sim}"
    assert naive_herding_overvolt == 471, f"NAIVE herding overvolt should be 471, got {naive_herding_overvolt}"
    assert gossip_herding_overvolt == 0, f"GOSSIP herding overvolt should be 0, got {gossip_herding_overvolt}"
    print("  All assertions passed.")


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GridAI — Decentralised Grid Intelligence Demo</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0a0e1a; color: #e2e8f0; font-family: 'Segoe UI', system-ui, sans-serif; min-height: 100vh; }
#app { max-width: 1400px; margin: 0 auto; padding: 16px; }
h1 { font-size: 1.6rem; font-weight: 700; color: #f8fafc; letter-spacing: -0.02em; }
h1 span { color: #3b82f6; }
.subtitle { color: #94a3b8; font-size: 0.85rem; margin-top: 4px; }

/* Metrics bar */
.metrics-bar { display: flex; gap: 12px; flex-wrap: wrap; margin: 16px 0; }
.metric-card { background: #0f172a; border: 1px solid #1e293b; border-radius: 10px; padding: 12px 18px; min-width: 160px; }
.metric-card .label { font-size: 0.7rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; }
.metric-card .value { font-size: 1.4rem; font-weight: 700; margin-top: 2px; }
.metric-card .change { font-size: 0.75rem; margin-top: 2px; }
.green { color: #22c55e; }
.amber { color: #f59e0b; }
.red { color: #ef4444; }
.blue { color: #3b82f6; }
.dimmed { color: #475569; }
.secondary-note { font-size: 0.7rem; color: #64748b; font-style: italic; }

/* Controls */
.controls { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin: 12px 0; background: #0f172a; border: 1px solid #1e293b; border-radius: 10px; padding: 12px 16px; }
.controls button { background: #1e293b; border: 1px solid #334155; color: #e2e8f0; border-radius: 6px; padding: 6px 14px; cursor: pointer; font-size: 0.85rem; transition: background 0.15s; }
.controls button:hover { background: #334155; }
.controls button.active { background: #3b82f6; border-color: #3b82f6; color: #fff; }
.controls label { font-size: 0.8rem; color: #94a3b8; }
.controls input[type=range] { width: 200px; accent-color: #3b82f6; }
.time-display { font-size: 1rem; font-weight: 700; color: #f59e0b; min-width: 48px; }

/* Toggle group */
.toggle-group { display: flex; gap: 0; }
.toggle-group button { border-radius: 0; border-right: none; }
.toggle-group button:first-child { border-radius: 6px 0 0 6px; }
.toggle-group button:last-child { border-radius: 0 6px 6px 0; border-right: 1px solid #334155; }

/* Main layout */
.main-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; }
.main-layout.single { grid-template-columns: 1fr; }
.panel { background: #0f172a; border: 1px solid #1e293b; border-radius: 10px; padding: 14px; }
.panel-title { font-size: 0.8rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 10px; display: flex; align-items: center; gap: 8px; }
.panel-title .badge { font-size: 0.65rem; padding: 2px 8px; border-radius: 20px; font-weight: 700; }
.badge-escalate { background: #7f1d1d; color: #fca5a5; }
.badge-approved { background: #14532d; color: #86efac; }

canvas { display: block; }

/* Bottom row */
.bottom-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; }
.audit-panel { background: #0f172a; border: 1px solid #1e293b; border-radius: 10px; padding: 14px; }
.audit-log { font-size: 0.72rem; font-family: 'Courier New', monospace; max-height: 200px; overflow-y: auto; color: #94a3b8; }
.audit-entry { padding: 4px 6px; border-bottom: 1px solid #1e293b; line-height: 1.4; }
.audit-entry:hover { background: #1e293b; }
.audit-entry .step-badge { color: #475569; }
.audit-entry .sender { color: #60a5fa; font-weight: 600; }
.audit-entry .recipient { color: #a78bfa; }
.audit-entry .msg-type { color: #f59e0b; }
.audit-entry .summary { color: #64748b; font-size: 0.68rem; }
.audit-entry.escalate { border-left: 3px solid #ef4444; background: rgba(239,68,68,0.05); }
.audit-entry.approved { border-left: 3px solid #22c55e; background: rgba(34,197,94,0.05); }
.audit-entry.operator { border-left: 3px solid #f59e0b; background: rgba(245,158,11,0.05); }

/* 3-way panel */
.threeway-panel { background: #0f172a; border: 1px solid #1e293b; border-radius: 10px; padding: 14px; margin-top: 12px; }
.threeway-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 10px; }
.threeway-card { background: #0a0e1a; border: 1px solid #1e293b; border-radius: 8px; padding: 10px; text-align: center; }
.threeway-card .tc-label { font-size: 0.7rem; color: #64748b; margin-bottom: 6px; }
.threeway-card .tc-sync { font-size: 1.3rem; font-weight: 700; }
.threeway-card .tc-overvolt { font-size: 0.8rem; margin-top: 4px; }
.threeway-card .tc-peak { font-size: 0.7rem; color: #64748b; margin-top: 2px; }
.threeway-card.naive-style { border-color: #7f1d1d; }
.threeway-card.gossip-style { border-color: #14532d; }

/* Phase indicator */
.phase-bar { background: #0f172a; border: 1px solid #1e293b; border-radius: 8px; padding: 8px 14px; margin: 10px 0; display: flex; align-items: center; gap: 10px; font-size: 0.78rem; }
.phase-label { color: #64748b; }
.phase-name { font-weight: 700; color: #e2e8f0; }
.phase-desc { color: #94a3b8; }

/* Compliance summary card */
.compliance-summary { padding: 10px 14px; background: #0a0e1a; border-radius: 8px; margin-top: 8px; border: 1px solid #1e293b; font-size: 0.78rem; }
.compliance-summary .decision { font-size: 1rem; font-weight: 700; margin-bottom: 4px; }
.compliance-summary .reason-text { color: #94a3b8; line-height: 1.5; }

/* Scrollbar styling */
::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-track { background: #0a0e1a; }
::-webkit-scrollbar-thumb { background: #334155; border-radius: 2px; }

/* Header row */
.header-row { display: flex; justify-content: space-between; align-items: flex-start; }
.logo-area h1 { font-size: 1.8rem; }
.logo-area .tagline { color: #475569; font-size: 0.78rem; margin-top: 2px; }
.view-controls { display: flex; gap: 8px; align-items: center; }
</style>
</head>
<body>
<div id="app">

  <div class="header-row">
    <div class="logo-area">
      <h1>Grid<span>AI</span></h1>
      <div class="tagline">Decentralised gossip coordination · AEMO load profile · 60 homes · 24 hours</div>
    </div>
    <div class="view-controls">
      <div class="toggle-group" id="viewToggle">
        <button onclick="setView('side')" class="active" id="btnSide">Side-by-side</button>
        <button onclick="setView('naive')" id="btnNaive">Naive only</button>
        <button onclick="setView('gossip')" id="btnGossip">Gossip only</button>
      </div>
    </div>
  </div>

  <!-- Phase indicator -->
  <div class="phase-bar">
    <span class="phase-label">Phase:</span>
    <span class="phase-name" id="phaseName">Morning</span>
    <span class="phase-desc" id="phaseDesc">Grid healthy, batteries charging</span>
  </div>

  <!-- Metrics bar -->
  <div class="metrics-bar">
    <div class="metric-card">
      <div class="label">Battery-Induced Overvolt Violations</div>
      <div class="value red" id="metNaiveOvervolt">— </div>
      <div class="change">NAIVE herding overvolt events</div>
    </div>
    <div class="metric-card">
      <div class="label">Gossip Overvolt Violations</div>
      <div class="value green">0</div>
      <div class="change green">↓ eliminated by desynchronisation</div>
    </div>
    <div class="metric-card">
      <div class="label">Synchrony (peak simultaneous / 60)</div>
      <div class="value red">1.000</div>
      <div class="change">NAIVE → <span class="green">0.167</span> GOSSIP</div>
    </div>
    <div class="metric-card">
      <div class="label">Gossip Convergence</div>
      <div class="value green">1 round</div>
      <div class="change green">lightweight coordination</div>
    </div>
    <div class="metric-card">
      <div class="label">Peak Demand Reduction</div>
      <div class="value dimmed">−0.9%</div>
      <div class="secondary-note">secondary · reported honestly · het case</div>
    </div>
  </div>

  <!-- Playback controls -->
  <div class="controls">
    <button onclick="togglePlay()" id="playBtn">&#9654; Play</button>
    <button onclick="jumpTo(204)">&#9654; Jump to Evening Peak</button>
    <button onclick="jumpTo(0)">&#8634; Reset</button>
    <label>Step: <input type="range" id="stepSlider" min="0" max="287" value="0" oninput="onSlider(this.value)"></label>
    <span class="time-display" id="timeDisplay">00:00</span>
    <label>Speed:
      <select id="speedSelect" onchange="onSpeedChange()" style="background:#1e293b;border:1px solid #334155;color:#e2e8f0;border-radius:6px;padding:4px 8px;font-size:0.8rem;">
        <option value="4">0.5×</option>
        <option value="8">1×</option>
        <option value="16" selected>2×</option>
        <option value="32">4×</option>
        <option value="64">8×</option>
      </select>
    </label>
    <span id="breachIndicator" style="display:none; color:#ef4444; font-weight:700; font-size:0.85rem;">⚡ VOLTAGE BREACH</span>
  </div>

  <!-- Main grid panels -->
  <div class="main-layout" id="mainLayout">
    <!-- Naive panel -->
    <div class="panel" id="naivePanel">
      <div class="panel-title">
        Naive (price-following)
        <span class="badge badge-escalate">ESCALATED</span>
      </div>
      <canvas id="naiveGrid" width="640" height="240"></canvas>
      <canvas id="naiveVoltage" width="640" height="100" style="margin-top:8px;"></canvas>
    </div>
    <!-- Gossip panel -->
    <div class="panel" id="gossipPanel">
      <div class="panel-title">
        Gossip (desynchronised)
        <span class="badge badge-approved">APPROVED</span>
      </div>
      <canvas id="gossipGrid" width="640" height="240"></canvas>
      <canvas id="gossipVoltage" width="640" height="100" style="margin-top:8px;"></canvas>
    </div>
  </div>

  <!-- Demand curve -->
  <div class="panel" style="margin-top:12px;">
    <div class="panel-title" style="margin-bottom:6px;">Aggregate Demand Curve (kW) — 24h AEMO profile</div>
    <canvas id="demandCanvas" width="1280" height="110"></canvas>
  </div>

  <!-- Compliance + Audit row -->
  <div class="bottom-row">
    <!-- Naive compliance -->
    <div class="audit-panel">
      <div class="panel-title">BAND Audit Trail — Naive</div>
      <div class="audit-log" id="naiveAuditLog"></div>
      <div class="compliance-summary" id="naiveComplianceSummary">
        <div class="decision red">&#9888; ESCALATE</div>
        <div class="reason-text" id="naiveReason"></div>
      </div>
    </div>
    <!-- Gossip compliance -->
    <div class="audit-panel">
      <div class="panel-title">BAND Audit Trail — Gossip</div>
      <div class="audit-log" id="gossipAuditLog"></div>
      <div class="compliance-summary" id="gossipComplianceSummary">
        <div class="decision green">&#10003; APPROVED</div>
        <div class="reason-text" id="gossipReason"></div>
      </div>
    </div>
  </div>

  <!-- 3-way heterogeneity panel -->
  <div class="threeway-panel">
    <div class="panel-title">3-Way Heterogeneity Contrast (secondary panel)</div>
    <div style="font-size:0.75rem;color:#64748b;margin-bottom:8px;">Battery-herding overvolt violations vs fleet synchrony. Gossip eliminates overvolt regardless of homogeneous/heterogeneous setup.</div>
    <div class="threeway-grid" id="threewayGrid"></div>
  </div>

</div><!-- /app -->

<script>
const DATA = __DATA_PLACEHOLDER__;

// ── constants ──
const STEPS = DATA.constants.STEPS;
const MIN_PU = DATA.constants.MIN_PU;
const MAX_PU = DATA.constants.MAX_PU;
const BAT_START = DATA.constants.BATTERY_START;
const BAT_END = DATA.constants.BATTERY_END;

// ── state ──
let currentStep = 0;
let playing = false;
let animHandle = null;
let lastFrameTime = 0;
let stepsPerFrame = 16; // default 2x
let view = 'side'; // 'side', 'naive', 'gossip'

// ── roundRect polyfill for older browsers ──
if (!CanvasRenderingContext2D.prototype.roundRect) {
  CanvasRenderingContext2D.prototype.roundRect = function(x, y, w, h, r) {
    r = Math.min(r || 0, Math.min(w, h) / 2);
    this.beginPath();
    this.moveTo(x + r, y);
    this.lineTo(x + w - r, y);
    this.quadraticCurveTo(x + w, y, x + w, y + r);
    this.lineTo(x + w, y + h - r);
    this.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    this.lineTo(x + r, y + h);
    this.quadraticCurveTo(x, y + h, x, y + h - r);
    this.lineTo(x, y + r);
    this.quadraticCurveTo(x, y, x + r, y);
    this.closePath();
    return this;
  };
}

// ── canvas refs ──
const naiveGridCvs = document.getElementById('naiveGrid');
const gossipGridCvs = document.getElementById('gossipGrid');
const naiveVoltageCvs = document.getElementById('naiveVoltage');
const gossipVoltageCvs = document.getElementById('gossipVoltage');
const demandCvs = document.getElementById('demandCanvas');

// ── helpers ──
function stepToTime(s) {
  const mins = s * 5;
  const hh = String(Math.floor(mins / 60)).padStart(2, '0');
  const mm = String(mins % 60).padStart(2, '0');
  return hh + ':' + mm;
}

function getPhase(s) {
  if (s < 72) return ['Morning', 'Grid healthy, batteries idle'];
  if (s < 144) return ['Midday', 'PV generation (separate phenomenon)'];
  if (s < 204) return ['Afternoon', 'Demand rising, batteries pre-charge'];
  if (s < 240) return ['Evening Peak', 'Battery window · Naive: synchronized flash · Gossip: ripple'];
  if (s < 270) return ['Late Evening', 'Batteries depleting'];
  return ['Night', 'Low demand, recovery'];
}

// ── layout ──
function setView(v) {
  view = v;
  document.getElementById('btnSide').classList.toggle('active', v === 'side');
  document.getElementById('btnNaive').classList.toggle('active', v === 'naive');
  document.getElementById('btnGossip').classList.toggle('active', v === 'gossip');

  const layout = document.getElementById('mainLayout');
  const naivePanel = document.getElementById('naivePanel');
  const gossipPanel = document.getElementById('gossipPanel');

  if (v === 'side') {
    layout.classList.remove('single');
    naivePanel.style.display = '';
    gossipPanel.style.display = '';
  } else if (v === 'naive') {
    layout.classList.add('single');
    naivePanel.style.display = '';
    gossipPanel.style.display = 'none';
  } else {
    layout.classList.add('single');
    naivePanel.style.display = 'none';
    gossipPanel.style.display = '';
  }
  resizeCanvases();
  renderAll();
}

function resizeCanvases() {
  const naivePanel = document.getElementById('naivePanel');
  const gossipPanel = document.getElementById('gossipPanel');
  const isSingle = view !== 'side';

  function resizePanel(panel, gridCvs, voltCvs) {
    const w = panel.offsetWidth - 28;
    const h = Math.round(w * 0.37);
    const vh = Math.round(w * 0.155);
    gridCvs.width = w; gridCvs.height = h;
    voltCvs.width = w; voltCvs.height = vh;
  }
  if (view === 'side' || view === 'naive') resizePanel(naivePanel, naiveGridCvs, naiveVoltageCvs);
  if (view === 'side' || view === 'gossip') resizePanel(gossipPanel, gossipGridCvs, gossipVoltageCvs);

  const demandW = document.getElementById('app').offsetWidth - 32;
  demandCvs.width = demandW;
  demandCvs.height = 110;
}

// ── grid drawing ──
function drawHomeGrid(canvas, scenario, step) {
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = '#0a0e1a';
  ctx.fillRect(0, 0, W, H);

  const n = scenario.n_homes;
  const cols = 10;
  const rows = Math.ceil(n / cols);
  const dispatch = scenario.dispatch[step];
  const voltage = scenario.voltage;
  const positions = scenario.home_positions;

  const padX = 18, padY = 14;
  const cellW = (W - padX * 2) / cols;
  const cellH = (H - padY * 2) / rows;
  const homeW = Math.max(cellW * 0.7, 20);
  const homeH = Math.max(cellH * 0.7, 14);

  const dischargingSet = new Set(dispatch);

  for (let h = 0; h < n; h++) {
    const col = h % cols;
    const row = Math.floor(h / cols);
    const cx = padX + col * cellW + cellW / 2;
    const cy = padY + row * cellH + cellH / 2;
    const x = cx - homeW / 2;
    const y = cy - homeH / 2;

    const v = voltage[h][step];
    const overvolt = v > MAX_PU;
    const undervolt = v < MIN_PU;
    const discharging = dischargingSet.has(h);

    // Base color: dark feeder position hint
    const pos = positions[h];
    const posNorm = pos / 59;
    const baseL = Math.round(12 + posNorm * 8);
    ctx.fillStyle = `hsl(220, 30%, ${baseL}%)`;
    ctx.beginPath();
    ctx.roundRect(x, y, homeW, homeH, 3);
    ctx.fill();

    if (overvolt) {
      // Red flash for overvoltage
      const pulse = 0.6 + 0.4 * Math.sin(Date.now() / 150);
      ctx.fillStyle = `rgba(239,68,68,${0.7 * pulse})`;
      ctx.beginPath();
      ctx.roundRect(x, y, homeW, homeH, 3);
      ctx.fill();
      ctx.strokeStyle = '#ef4444';
      ctx.lineWidth = 1.5;
      ctx.stroke();
    } else if (undervolt) {
      ctx.fillStyle = 'rgba(168,85,247,0.5)';
      ctx.beginPath();
      ctx.roundRect(x, y, homeW, homeH, 3);
      ctx.fill();
      ctx.strokeStyle = '#a855f7';
      ctx.lineWidth = 1;
      ctx.stroke();
    }

    if (discharging) {
      // Amber glow
      const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, homeW * 0.8);
      glow.addColorStop(0, 'rgba(245,158,11,0.85)');
      glow.addColorStop(1, 'rgba(245,158,11,0.0)');
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.roundRect(x - 3, y - 3, homeW + 6, homeH + 6, 5);
      ctx.fill();

      ctx.fillStyle = '#f59e0b';
      ctx.beginPath();
      ctx.roundRect(x, y, homeW, homeH, 3);
      ctx.fill();

      // lightning bolt icon (tiny)
      ctx.fillStyle = '#0a0e1a';
      ctx.font = `bold ${Math.max(8, homeH * 0.55)}px sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('⚡', cx, cy);
    } else {
      // House icon
      ctx.fillStyle = discharging ? '#0a0e1a' : '#475569';
      ctx.font = `${Math.max(7, homeH * 0.45)}px sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('⌂', cx, cy);
    }
  }

  // Draw legend
  ctx.fillStyle = '#f59e0b';
  ctx.fillRect(padX, H - 14, 10, 8);
  ctx.fillStyle = '#94a3b8';
  ctx.font = '10px sans-serif';
  ctx.textAlign = 'left';
  ctx.fillText('Discharging', padX + 13, H - 7);

  ctx.fillStyle = '#ef4444';
  ctx.fillRect(padX + 95, H - 14, 10, 8);
  ctx.fillText('Overvolt >1.10pu', padX + 108, H - 7);

  ctx.fillStyle = '#a855f7';
  ctx.fillRect(padX + 210, H - 14, 10, 8);
  ctx.fillText('Undervolt <0.94pu', padX + 223, H - 7);

  // Count label
  const dispCount = dispatch.length;
  const syncRatio = (dispCount / n).toFixed(3);
  ctx.fillStyle = '#e2e8f0';
  ctx.font = 'bold 11px sans-serif';
  ctx.textAlign = 'right';
  ctx.fillText(`${dispCount}/60 discharging  sync=${syncRatio}`, W - padX, H - 7);
}

// ── voltage series drawing ──
function drawVoltagePanel(canvas, scenario, step) {
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = '#0a0e1a';
  ctx.fillRect(0, 0, W, H);

  const padX = 36, padY = 10;
  const plotW = W - padX - 10;
  const plotH = H - padY * 2;

  const vMin = 0.88, vMax = 1.22;
  const vRange = vMax - vMin;

  function toY(v) {
    return padY + plotH - ((v - vMin) / vRange) * plotH;
  }

  // Background
  ctx.fillStyle = '#0f172a';
  ctx.fillRect(padX, padY, plotW, plotH);

  // Band limits
  const yMax = toY(MAX_PU);
  const yMin = toY(MIN_PU);
  ctx.fillStyle = 'rgba(239,68,68,0.07)';
  ctx.fillRect(padX, padY, plotW, yMax - padY); // above max
  ctx.fillRect(padX, yMin, plotW, H - yMin - padY + 10); // below min

  ctx.strokeStyle = '#ef444480';
  ctx.lineWidth = 1;
  ctx.setLineDash([3, 3]);
  ctx.beginPath();
  ctx.moveTo(padX, yMax); ctx.lineTo(padX + plotW, yMax);
  ctx.moveTo(padX, yMin); ctx.lineTo(padX + plotW, yMin);
  ctx.stroke();
  ctx.setLineDash([]);

  // Band limit labels
  ctx.fillStyle = '#ef444499';
  ctx.font = '9px sans-serif';
  ctx.textAlign = 'right';
  ctx.fillText('1.10', padX - 2, yMax + 3);
  ctx.fillText('0.94', padX - 2, yMin + 3);

  // Battery window shading
  const bxStart = padX + (BAT_START / STEPS) * plotW;
  const bxEnd = padX + (BAT_END / STEPS) * plotW;
  ctx.fillStyle = 'rgba(245,158,11,0.05)';
  ctx.fillRect(bxStart, padY, bxEnd - bxStart, plotH);

  // Voltage lines for each home (thin, colored by violation)
  const n = scenario.n_homes;
  for (let h = 0; h < n; h++) {
    const v = scenario.voltage[h][step];
    const isOver = v > MAX_PU;
    const isUnder = v < MIN_PU;
    ctx.strokeStyle = isOver ? 'rgba(239,68,68,0.8)' : isUnder ? 'rgba(168,85,247,0.6)' : 'rgba(59,130,246,0.25)';
    ctx.lineWidth = isOver || isUnder ? 1.5 : 0.8;
    ctx.beginPath();
    for (let s = 0; s <= step; s++) {
      const x = padX + (s / STEPS) * plotW;
      const y = toY(scenario.voltage[h][s]);
      s === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  // Current time marker
  const cx = padX + (step / STEPS) * plotW;
  ctx.strokeStyle = '#f59e0b';
  ctx.lineWidth = 1.5;
  ctx.setLineDash([4, 3]);
  ctx.beginPath();
  ctx.moveTo(cx, padY);
  ctx.lineTo(cx, padY + plotH);
  ctx.stroke();
  ctx.setLineDash([]);

  // Y label
  ctx.save();
  ctx.translate(10, padY + plotH / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillStyle = '#64748b';
  ctx.font = '9px sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('Voltage (pu)', 0, 0);
  ctx.restore();
}

// ── demand curve ──
function drawDemandCurve(canvas, step) {
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = '#0f172a';
  ctx.fillRect(0, 0, W, H);

  const padX = 44, padTop = 10, padBot = 22;
  const plotW = W - padX - 10;
  const plotH = H - padTop - padBot;

  const naiveDemand = DATA.naive.demand;
  const gossipDemand = DATA.gossip.demand;
  const allVals = [...naiveDemand, ...gossipDemand];
  const dMin = Math.min(...allVals);
  const dMax = Math.max(...allVals);
  const dRange = dMax - dMin || 1;

  function toY(v) {
    return padTop + plotH - ((v - dMin) / dRange) * plotH;
  }

  function toX(s) {
    return padX + (s / STEPS) * plotW;
  }

  // Grid lines
  ctx.strokeStyle = '#1e293b';
  ctx.lineWidth = 0.5;
  for (let kw = Math.ceil(dMin / 50) * 50; kw <= dMax; kw += 50) {
    const y = toY(kw);
    ctx.beginPath(); ctx.moveTo(padX, y); ctx.lineTo(padX + plotW, y); ctx.stroke();
    ctx.fillStyle = '#334155';
    ctx.font = '9px sans-serif';
    ctx.textAlign = 'right';
    ctx.fillText(kw, padX - 3, y + 3);
  }

  // Hour labels
  ctx.fillStyle = '#475569';
  ctx.font = '9px sans-serif';
  ctx.textAlign = 'center';
  for (let h = 0; h <= 24; h += 4) {
    const s = h * 12;
    const x = toX(s);
    ctx.fillText(String(h).padStart(2, '0') + ':00', x, H - 5);
    ctx.strokeStyle = '#1e293b';
    ctx.lineWidth = 0.5;
    ctx.beginPath(); ctx.moveTo(x, padTop); ctx.lineTo(x, padTop + plotH); ctx.stroke();
  }

  // Battery window
  const bxStart = toX(BAT_START);
  const bxEnd = toX(BAT_END);
  ctx.fillStyle = 'rgba(245,158,11,0.06)';
  ctx.fillRect(bxStart, padTop, bxEnd - bxStart, plotH);

  // Gossip demand (draw full to current)
  ctx.strokeStyle = '#22c55e';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  for (let s = 0; s <= step; s++) {
    const x = toX(s), y = toY(gossipDemand[s]);
    s === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Naive demand
  ctx.strokeStyle = '#ef4444';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  for (let s = 0; s <= step; s++) {
    const x = toX(s), y = toY(naiveDemand[s]);
    s === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Legend
  ctx.fillStyle = '#ef4444'; ctx.fillRect(padX, padTop, 18, 3);
  ctx.fillStyle = '#94a3b8'; ctx.font = '10px sans-serif'; ctx.textAlign = 'left';
  ctx.fillText('Naive', padX + 22, padTop + 8);
  ctx.fillStyle = '#22c55e'; ctx.fillRect(padX + 70, padTop, 18, 3);
  ctx.fillText('Gossip', padX + 92, padTop + 8);

  // Current time marker
  const tx = toX(step);
  ctx.strokeStyle = '#f59e0b80';
  ctx.lineWidth = 1;
  ctx.setLineDash([3, 3]);
  ctx.beginPath(); ctx.moveTo(tx, padTop); ctx.lineTo(tx, padTop + plotH); ctx.stroke();
  ctx.setLineDash([]);

  // Y axis label
  ctx.save();
  ctx.translate(12, padTop + plotH / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillStyle = '#64748b';
  ctx.font = '9px sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('Demand (kW)', 0, 0);
  ctx.restore();
}

// ── audit log rendering ──
function renderAuditLog(logEl, auditEntries, decision) {
  logEl.innerHTML = '';
  auditEntries.forEach(entry => {
    const div = document.createElement('div');
    div.className = 'audit-entry';
    const msgType = entry.message_type;
    if (msgType === 'handoff:compliance_escalation') div.classList.add('escalate');
    if (msgType === 'compliance_approval') div.classList.add('approved');
    if (msgType === 'operator_decision') div.classList.add('operator');

    div.innerHTML =
      `<span class="step-badge">[${entry.step}] ${entry.timestamp}</span> ` +
      `<span class="sender">${entry.sender}</span>` +
      `<span style="color:#475569"> → </span>` +
      `<span class="recipient">${entry.recipient}</span> ` +
      `<span class="msg-type">${entry.message_type}</span><br>` +
      `<span class="summary">${entry.summary}</span>`;
    logEl.appendChild(div);
  });
}

// ── 3-way panel ──
function renderThreeWay() {
  const grid = document.getElementById('threewayGrid');
  grid.innerHTML = '';
  const items = [
    { key: 'naive_hom', cls: 'naive-style' },
    { key: 'naive_het', cls: 'naive-style' },
    { key: 'gossip_hom', cls: 'gossip-style' },
    { key: 'gossip_het', cls: 'gossip-style' },
  ];
  items.forEach(({ key, cls }) => {
    const d = DATA.threeway[key];
    const isGossip = key.startsWith('gossip');
    const syncColor = isGossip ? '#22c55e' : '#ef4444';
    const overvoltColor = d.bat_overvolt_steps === 0 ? '#22c55e' : '#ef4444';
    const div = document.createElement('div');
    div.className = `threeway-card ${cls}`;
    div.innerHTML = `
      <div class="tc-label">${d.label}</div>
      <div class="tc-sync" style="color:${syncColor}">sync=${d.synchrony.toFixed(3)}</div>
      <div style="font-size:0.72rem;color:#64748b">(${d.max_sim_discharge}/60 homes)</div>
      <div class="tc-overvolt" style="color:${overvoltColor}">overvolt steps: ${d.bat_overvolt_steps}</div>
      <div class="tc-peak">peak ${d.peak_demand_kw.toFixed(1)} kW</div>
    `;
    grid.appendChild(div);
  });
}

// ── breach indicator ──
function updateBreachIndicator(step) {
  const naiveBreaches = DATA.naive.herding_breaches.filter(e => e.step === step);
  const ind = document.getElementById('breachIndicator');
  if (naiveBreaches.length > 0) {
    ind.style.display = 'inline';
    const e = naiveBreaches[0];
    ind.textContent = `⚡ VOLTAGE BREACH — node ${e.node_id} @ ${e.voltage_pu.toFixed(4)}pu (${e.band_limit_crossed}) step=${step} ${stepToTime(step)}`;
  } else {
    ind.style.display = 'none';
  }
}

// ── phase + time display ──
function updatePhase(step) {
  const [name, desc] = getPhase(step);
  document.getElementById('phaseName').textContent = name;
  document.getElementById('phaseDesc').textContent = desc;
  document.getElementById('timeDisplay').textContent = stepToTime(step);
  document.getElementById('stepSlider').value = step;
}

// ── main render ──
function renderAll() {
  const s = currentStep;
  if (view !== 'gossip') {
    drawHomeGrid(naiveGridCvs, DATA.naive, s);
    drawVoltagePanel(naiveVoltageCvs, DATA.naive, s);
  }
  if (view !== 'naive') {
    drawHomeGrid(gossipGridCvs, DATA.gossip, s);
    drawVoltagePanel(gossipVoltageCvs, DATA.gossip, s);
  }
  drawDemandCurve(demandCvs, s);
  updatePhase(s);
  updateBreachIndicator(s);
}

// ── playback ──
function togglePlay() {
  playing = !playing;
  document.getElementById('playBtn').textContent = playing ? '⏸ Pause' : '▶ Play';
  if (playing) requestAnimationFrame(animLoop);
}

function animLoop(ts) {
  if (!playing) return;
  if (ts - lastFrameTime >= (1000 / 60) * (stepsPerFrame / 16)) {
    currentStep = (currentStep + 1) % STEPS;
    renderAll();
    lastFrameTime = ts;
  }
  requestAnimationFrame(animLoop);
}

function jumpTo(step) {
  currentStep = step;
  renderAll();
}

function onSlider(val) {
  currentStep = parseInt(val);
  renderAll();
}

function onSpeedChange() {
  stepsPerFrame = parseInt(document.getElementById('speedSelect').value);
}

// ── init ──
window.addEventListener('DOMContentLoaded', () => {
  // Populate compliance reasons
  document.getElementById('naiveReason').textContent = DATA.naive.compliance.reason;
  document.getElementById('gossipReason').textContent = DATA.gossip.compliance.reason;

  // Populate audit logs
  renderAuditLog(document.getElementById('naiveAuditLog'), DATA.naive.audit, DATA.naive.compliance.decision);
  renderAuditLog(document.getElementById('gossipAuditLog'), DATA.gossip.audit, DATA.gossip.compliance.decision);

  // Metrics
  document.getElementById('metNaiveOvervolt').textContent = DATA.naive.compliance.herding_overvolt_event_count;

  // 3-way
  renderThreeWay();

  // Initial sizing
  resizeCanvases();
  window.addEventListener('resize', () => { resizeCanvases(); renderAll(); });

  // Initial render at step 0
  renderAll();
});
</script>
</body>
</html>
"""


def main():
    print("Building GridAI demo...")
    bundle = build_data_bundle()
    crosscheck(bundle)

    data_json = json.dumps(bundle, separators=(",", ":"))
    html = HTML_TEMPLATE.replace("__DATA_PLACEHOLDER__", data_json)

    out_path = os.path.join(VIZ, "gridai_demo.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    size_kb = os.path.getsize(out_path) / 1024
    print(f"\nWrote: {out_path}")
    print(f"Size:  {size_kb:.1f} KB")
    return out_path, size_kb


if __name__ == "__main__":
    main()
