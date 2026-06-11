# Session State

## DONE (verified)

- `/Users/mayank/gridai/` repo created, git initialised, initial commit made
- `sim/feeder.py`: LV radial feeder, N=60 homes, prefix-sum voltage model (AS IEC 60038:2022: 0.94–1.10 pu), Z=0.001 pu/kW, 288 steps × 5 min
- `sim/profiles.py`: synthetic load (morning + evening peaks), PV (bell curve, 65% penetration), 5 kW battery, price signal, make_homes() with heterogeneous/homogeneous modes
- `sim/strategies.py`: Strategy A (naive price-following), Strategy B (gossip decentralised), MAX_CONCURRENT_DISCHARGE=20 from voltage physics
- `sim/simulator.py`: full 24h simulation engine, per-home SOC/voltage/dispatch tracking, compute_metrics() with battery-window and PV-window separation
- `sim/runner.py`: runs 4 scenarios, writes `outputs/scenario_*.json` (full time series for Layer 3) and `outputs/summary.json`
- `tests/test_simulation.py`: 21 tests, all PASSING (pytest 0.40s)
- First git commit: `1e2f549`

## IN PROGRESS

_Nothing in progress._

## NEXT

- Day 2: tune scenarios so contrast is more visually dramatic; add AEMO 2012 Victorian load profile; lock headline numbers
- Day 3-4: Band SDK integration. Four agents (Forecaster, Coordinator, Compliance, Operator)

## VERIFIED NUMBERS

From actual run (python3 sim/runner.py):

**Demand swing in battery window 17:00–21:40 (primary herding metric):**
- Naive homogeneous:    361.0 kW range  (synchrony: 1.000)
- Gossip homogeneous:   99.9 kW range   (synchrony: 0.367)   [72.3% reduction]
- Naive heterogeneous:  249.5 kW range  (synchrony: 0.767)
- Gossip heterogeneous: 105.8 kW range  (synchrony: 0.200)   [57.6% reduction]

**Battery-window overvoltage violations (herding spike metric):**
- Naive homogeneous:    14 steps (herding causes overvoltage)
- Naive heterogeneous:  6 steps
- Gossip homogeneous:   0 steps (protocol prevents overvoltage)
- Gossip heterogeneous: 0 steps (protocol prevents overvoltage)

**Battery-window peak demand (post-discharge cliff):**
- Naive hom: 131.6 kW → Gossip hom: 116.3 kW  [11.6% reduction]
- Naive het: 130.7 kW → Gossip het: 126.6 kW  [3.2% reduction]

**Gossip convergence:**
- Homogeneous fleet: 2 rounds
- Heterogeneous fleet: 1 round

**PV overvoltage (midday, same for all strategies — not the battery story):**
- ~55–59 steps (10:00–15:00 window), equal across all scenarios

**Three-way heterogeneity contrast (synchrony ratios):**
- naive_hom:  1.000 (all 60 discharge simultaneously)
- gossip_hom: 0.367 (weak desynchronisation, tiebreaker only)
- gossip_het: 0.200 (strong desynchronisation, heterogeneity drives it)

**pytest: 21 tests passed, 0 failed, 0.40s**

## KNOWN ISSUES

- Battery-window undervoltage (22–27 steps) exists in ALL scenarios because the gossip protocol staggered discharge means fewer batteries help at any given moment. This is physically correct. The key story is OVERVOLTAGE elimination (the herding spike), not undervoltage.
- PV export overvoltage (midday): ~55 steps in all scenarios — this is a separate problem (smart inverter territory), not what GridAI addresses.
- Gossip-het shows slightly higher bat_peak_demand (126.6 kW) than gossip-hom (116.3 kW) because heterogeneous fleet distributes more evenly, but the gossip-hom ends up with a 22-battery cluster at step 234 (one big clump from the homogeneous tiebreaker). This is expected and illustrates the three-way contrast in synchrony.

## DO NOT

- Do not build a React/websocket dashboard; Layer 3 is precomputed JSON to standalone HTML
- Do not add a full power-flow solver; linear voltage approximation is correct for this layer
- Do not make all agents homogeneous by default; heterogeneity is the intellectual core
- Do not weaken test assertions to force green; fix the model instead
- Do not add Band SDK in Layer 1; that is Layer 2
- Do not increase MAX_CONCURRENT_DISCHARGE beyond ~20 without recalibrating voltage physics
