# GridAI — Decentralised Battery Fleet Coordination

GridAI solves the herding problem in distributed energy resource (DER) coordination.

## The Problem

When thousands of home batteries follow the same price signal, they all discharge simultaneously and create a NEW synchronised demand spike instead of smoothing the existing one. This is the herding problem.

## The Solution

A gossip-based decentralised protocol where each battery agent negotiates only with its local neighbours. No central controller. The fleet desynchronises via local intent exchange, producing a flatter aggregate demand curve while respecting voltage limits (AS IEC 60038:2022 band: 0.94–1.10 pu) and owner preferences.

Critical design point: desynchronisation comes from fleet HETEROGENEITY (varied private thresholds and SOC), not from negotiation alone. The protocol channels heterogeneity; on a homogeneous fleet it only weakly desynchronises.

## Architecture

- **Layer 1** (this repo): Python simulation core — LV feeder, battery agents, gossip protocol, herding baseline
- **Layer 2** (next): Four AI agents over Band SDK (Forecaster, Coordinator, Compliance, Operator)
- **Layer 3** (next): Standalone HTML/Canvas animation replaying sim JSON

## Quick Start

```bash
cd /Users/mayank/gridai
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run all scenarios and write outputs/
python3 sim/runner.py

# Run tests
pytest tests/ -v
```

## Output Files

All outputs written to `outputs/`:
- `scenario_naive_homogeneous.json` — herding baseline, identical thresholds
- `scenario_naive_heterogeneous.json` — herding baseline, varied thresholds
- `scenario_gossip_homogeneous.json` — protocol on homogeneous fleet
- `scenario_gossip_heterogeneous.json` — protocol on heterogeneous fleet
- `summary.json` — headline metrics for all scenarios

## Hackathon

lablab.ai Band of Agents Hackathon, track: Regulated and High-Stakes Workflows.
