# Session State

## DONE (verified)

- `/Users/mayank/gridai/` repo created, git initialised, initial commit made
- `sim/feeder.py`: LV radial feeder, N=60 homes, prefix-sum voltage model (AS IEC 60038:2022: 0.94–1.10 pu), Z=0.001 pu/kW, 288 steps × 5 min
- `sim/profiles.py`: synthetic load (morning + evening peaks), PV (bell curve, 65% penetration), 5 kW battery, price signal, make_homes() with heterogeneous/homogeneous modes, aemo_profile kwarg for real-data load shape
- `sim/strategies.py`: Strategy A (naive price-following), Strategy B (gossip decentralised), MAX_CONCURRENT_DISCHARGE=20 from voltage physics
- `sim/simulator.py`: full 24h simulation engine, per-home SOC/voltage/dispatch tracking, compute_metrics(), voltage_breach_events list (per-event node/step/voltage/cause)
- `sim/runner.py`: runs 4 scenarios × 2 load sources (synthetic, aemo), writes `outputs/scenario_*.json` and `outputs/summary*.json`; metric hierarchy corrected (PRIMARY=voltage+synchrony, SECONDARY=peak reduction)
- `sim/aemo.py`: loads 12 monthly AEMO 2012 Victorian CSV files, asserts 17,568 rows, resamples representative day to 288 steps; representative date: 2012-01-24
- `outputs/summary.json`: synthetic scenarios with correct PRIMARY/SECONDARY metric hierarchy
- `outputs/summary_aemo.json`: AEMO-driven scenarios
- `tests/test_simulation.py`: 21 tests, all PASSING
- `tests/test_aemo.py`: 15 tests covering AEMO load, row count, AEMO-driven herding story, breach cause separation — all PASSING
- **Total: 36 tests, 36 passed, 0 failed, 1.19s**
- Day 1 git commit: `1e2f549`
- Day 2 git commit: (see below after commit)

## IN PROGRESS

_Nothing in progress._

## NEXT

- Day 3-4: Band SDK integration. Four agents (Forecaster, Coordinator, Compliance, Operator)
  - Compliance agent catches `battery_herding` overvoltage breach events specifically
  - Each event in `voltage_breach_events` has: node_id, step, time_hhmm, voltage_pu, band_limit_crossed, band_limit_value, cause
  - `cause: "battery_herding"` is what Compliance watches for; `cause: "pv_export"` events are midday/smart-inverter territory and must NOT be confused with battery events

## VERIFIED NUMBERS

From actual run (python3 sim/runner.py) — Day 2:

**METRIC HIERARCHY (locked — do NOT reorder)**

### PRIMARY 1: Battery-induced voltage violations (EVENING 17:00-21:40)
The GridAI claim: herding causes these, gossip eliminates them.

**Synthetic load source:**
- Naive homogeneous:    14 steps OVERVOLTAGE  (all 60 discharge simultaneously)
- Naive heterogeneous:  6 steps overvoltage
- Gossip homogeneous:   0 steps  (ELIMINATED)
- Gossip heterogeneous: 0 steps  (ELIMINATED)

**AEMO load source (2012-01-24, Victorian summer evening peak 8863.8 MW):**
- Naive homogeneous:    14 steps OVERVOLTAGE
- Naive heterogeneous:  2 steps  overvoltage
- Gossip homogeneous:   0 steps  (ELIMINATED)
- Gossip heterogeneous: 0 steps  (ELIMINATED)

### PRIMARY 2: Synchrony collapse (mechanism)
Max simultaneous discharge / N_homes.

**Synthetic:**
- naive_hom:  1.000  (60/60)  → all batteries fire at once
- naive_het:  0.767  (46/60)
- gossip_hom: 0.367  (22/60)
- gossip_het: 0.200  (12/60)  ← the headline: 1.000→0.200 collapse

**AEMO:**
- naive_hom:  1.000  (60/60)
- naive_het:  0.700  (42/60)
- gossip_hom: 0.367  (22/60)
- gossip_het: 0.167  (10/60)

### SECONDARY: Battery-window peak demand (17:00-21:40)
Modest, honest values. Heterogeneous = realistic case. NEVER inflate or swap for swing in headline.

**Synthetic:**
- Naive hom 131.6 kW → Gossip hom 116.3 kW  [11.6% — homogeneous stress test]
- Naive het 130.7 kW → Gossip het 126.6 kW  [3.2% — realistic case, report this one]

**AEMO:**
- Naive hom 121.6 kW → Gossip hom 119.3 kW  [1.9%]
- Naive het 120.2 kW → Gossip het 121.3 kW  [-0.9%]  (load shape change, slight variation OK)

### BREACH CAUSE SEPARATION (pv_export vs battery_herding)

**Synthetic (naive_homogeneous):** pv_export=55 steps, battery_herding=14 steps (correctly separated)
**Synthetic (gossip scenarios):** pv_export=55–59 steps, battery_herding=0 overvoltage events
**AEMO (naive_homogeneous):** pv_export=0 steps (AEMO shape has no PV boost), battery_herding=14 steps

### SUPPORTING: Gossip convergence
- Homogeneous fleet: 2 rounds
- Heterogeneous fleet: 1 round

## AEMO REPRESENTATIVE DATE

**Date: 2012-01-24 (Tuesday)**
**Reason:** Highest evening peak (17:00-20:00 window) TOTALDEMAND = 8863.8 MW across all of January and February 2012. Victorian summer — air-conditioning, cooking, returning commuters. This is exactly the scenario where a coordinated battery fleet's simultaneous discharge-on-price creates the herding problem.

**Data facts:**
- 17,568 rows (2012 leap year: 366×48 half-hours) ✓
- Date range: 2012-01-01 00:30:00 to 2013-01-01 00:00:00
- Demand: min 3612.2 MW, max 9325.98 MW, mean 5657.27 MW
- Price: min -$150.18/MWh, max $9974.42/MWh, mean $44.40/MWh

**pytest: 36 tests passed, 0 failed, 1.19s**

## KNOWN ISSUES

- Battery-window undervoltage (22–27 steps) exists in ALL gossip scenarios because staggered discharge means fewer batteries helping at any given moment. This is physically correct. The key story is OVERVOLTAGE elimination (the herding spike), not undervoltage. Breach-cause separation correctly labels these as "battery_herding" band_limit_crossed="lower" — distinct from the overvoltage problem.
- PV export overvoltage (midday): ~55 steps in all synthetic scenarios — same for all strategies, a separate problem (smart inverter territory), cause="pv_export" in breach_events.
- AEMO-driven gossip_het shows slightly higher bat_peak_demand (121.3 kW) vs naive_het (120.2 kW) — the -0.9% is a load-shape artefact, not a regression. The voltage story is intact.

## DO NOT

- Do not build a React/websocket dashboard; Layer 3 is precomputed JSON to standalone HTML
- Do not add a full power-flow solver; linear voltage approximation is correct for this layer
- Do not make all agents homogeneous by default; heterogeneity is the intellectual core
- Do not weaken test assertions to force green; fix the model instead
- Do not add Band SDK in Layer 1; that is Layer 2
- Do not increase MAX_CONCURRENT_DISCHARGE beyond ~20 without recalibrating voltage physics
- Do not lead any metric with swing/range; voltage-violation elimination and synchrony collapse are the headline, peak reduction is secondary and reported at its real modest value
- Do not report the homogeneous stress-test peak reduction (11.6%) as the headline; the heterogeneous realistic case (3.2%) is the honest number
- Do not confuse pv_export and battery_herding breach causes; they are physically distinct phenomena; Compliance agent catches battery_herding overvoltage specifically
