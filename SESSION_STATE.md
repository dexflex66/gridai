# Session State

## DONE (Day 4 — Layer 3 visualisation, verified)

- `viz/build_demo.py`: generator — reads outputs/ JSON, extracts a COMPACT real-data
  bundle (dispatch as sparse active-home lists, voltage rounded 4dp, demand, battery_herding
  breach events, compact Band audit, compliance summaries, 3-way numbers) and injects it into
  `viz/gridai_demo.html` as inline `const DATA` (self-contained, no fetch/CORS, no build at open).
- `viz/gridai_demo.html`: single self-contained file (~406 KB), pure Canvas + vanilla JS, no CDN.
  Side-by-side naive/gossip neighbourhood grids (amber=discharge, red=overvolt, purple=undervolt),
  per-node voltage sparklines, animated aggregate demand curve, dual Band audit-trail panels,
  compliance ESCALATE/APPROVED cards, 3-way heterogeneity panel, play/pause + speed + scrubber +
  "Jump to Evening Peak". Toggles: Side-by-side / Naive only / Gossip only.
- VERIFIED render (headless Chromium via Playwright, screenshots in viz/screenshots/):
  - 12:00 midday: both grids calm, demand curve drawn to noon — healthy baseline.
  - 17:35 naive: ALL 60 homes flash amber simultaneously + red breaches ("47 breach", node 37
    @1.10pu upper) + demand rebound spike + Compliance ESCALATE → Operator HOLD.
  - 17:35 gossip: staggered sparse amber (desync ripple), 0 overvoltage, Compliance APPROVED.
  - Only console message is a harmless favicon 404; no JS errors.
- Data integrity cross-checked against real JSON: naive max-simultaneous=60, gossip=10; naive
  battery_herding overvolt events=471, gossip=0; synchrony 1.000 vs 0.167.
- HONEST framing note: at the evening peak the gossip grid shows undervoltage (purple) at far-feeder
  nodes (16 nodes @ step 211; 435 battery_herding UNDERvolt events total) — the documented tradeoff
  of desynchronisation. The headline metric is scoped to OVERvoltage herding (471→0) and the legend
  distinguishes purple from red, so nothing is inflated. RESOLVED (user decision): added an explicit
  honest on-screen annotation under the gossip grid — "herding overvoltage 471 -> 0" plus a note that
  far-feeder nodes sag to mild undervoltage (a known desync tradeoff, a tuning target, not the herding failure).
- sim/ and agents/ NOT modified (no new output fields were needed). Tests still 82 (unchanged).

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
- **Total (Day 1+2): 36 tests, 36 passed, 0 failed, 1.19s**
- Day 1 git commit: `1e2f549`
- Day 2 git commit: (see below after commit)

## IN PROGRESS

_Nothing in progress._

## DONE (Day 3 — verified)

- `agents/band_interface.py`: abstract BandInterface (register, discover, send, broadcast, handoff, subscribe, drain, audit_log)
- `agents/mock_band.py`: MockBand — in-process synchronous implementation; append-only audit log with step/timestamp/sender/recipient/message_type/payload
- `agents/forecaster.py`: ForecasterAgent — analyses naive scenario, identifies evening battery-herding risk window, hands off structured risk_window context to Coordinator
- `agents/coordinator.py`: CoordinatorAgent — receives risk_window, executes the scenario's OWN dispatch strategy (naive for baseline run, gossip for coordinated run) via Layer 1, hands off the executed plan + its own voltage trajectory to Compliance. dispatch_plan and reviewed trajectory always come from the same run, so strategy label and breach data can never disagree.
- `agents/compliance.py`: ComplianceAgent — reviews voltage trajectory for battery_herding OVERVOLTAGE breaches; ignores pv_export; escalates to Operator or approves; writes audit trail entries
- `agents/grid_operator.py`: OperatorAgent — receives escalations/approvals, records governance decision (HOLD/REQUEST_REPLAN/APPROVE_WITH_CAVEAT/ACKNOWLEDGED_CLEAN), broadcasts final decision
- `agents/run_agents.py`: full chain runner for both naive and gossip AEMO scenarios; emits band_audit_*.json and compliance_decision_*.json to outputs/
- `agents/BAND_INTEGRATION.md`: swap-seam doc; interface→SDK mapping; open questions
- `tests/test_agents.py`: 36 tests all passing (incl. 2 regression guards that the decision record's strategy/synchrony match the executed scenario)
- **Total: 72 tests, 72 passed, 0 failed**
- Day 3 git commit: (see below after commit)

### Day 3 fix (provenance bug)
- Earlier Day 3 build had the Coordinator ALWAYS run gossip, then label the naive run's decision record with strategy=gossip + synchrony 0.167 while reporting 471 naive breaches — internally self-contradictory and a Q&A liability. Fixed: Coordinator now runs the scenario's own strategy; records are consistent (naive: strategy=naive, synchrony=1.0, rounds=null, 471→ESCALATE | gossip: strategy=gossip, synchrony=0.167, rounds=1, 0→APPROVED). Guarded by regression tests.

### Hero demo numbers (AEMO-driven, confirmed)

**NAIVE chain:**
- Forecaster: risk_level=CRITICAL, peak_synchrony_fraction=1.0
- Compliance: ESCALATE — 471 battery_herding overvoltage breach events
- Operator: HOLD
- pv_export_flagged_as_protocol_failure: false

**GOSSIP chain:**
- Forecaster: risk_level=LOW, peak_synchrony_fraction=0.167
- Compliance: APPROVED — 0 battery_herding overvoltage breach events
- Operator: ACKNOWLEDGED_CLEAN
- pv_export_flagged_as_protocol_failure: false

**Band audit log (naive run, 8 entries):**
```
step=1  forecaster  -> BAND         [register]
step=2  coordinator -> BAND         [register]
step=3  compliance  -> BAND         [register]
step=4  operator    -> BAND         [register]
step=5  forecaster  -> coordinator  [handoff:risk_window]
step=6  coordinator -> compliance   [handoff:dispatch_plan_and_trajectory]
step=7  compliance  -> operator     [handoff:compliance_escalation]
step=8  operator    -> ALL          [operator_decision]
```

## DONE (Day 3 — Band swap, verified)

- Real Band SDK integrated as a TRANSPORT BUS behind the unchanged BandInterface:
  - `agents/real_band.py`: RealBand — authenticates each agent with its own Band API
    key, creates one shared coordination room and adds the 4 agents as participants,
    routes handoffs as @mention chat messages carrying a JSON envelope, drains each
    agent's inbox (get_next → processing → processed), mirrors a local audit log and
    exposes Band's native trail via native_trail().
  - `agents/band_interface.py`: + get_band() factory (USE_REAL_BAND flag). The abstract
    interface itself is UNCHANGED. The four agents are UNCHANGED.
  - `agents/run_agents.py`: uses get_band() so the same runner drives mock or real.
- Platform facts learned (live): base URL `https://app.band.ai`; package `band-sdk`
  (import `band` / `thenvoi_rest`); room `task_id` must be a UUID (no string room names);
  empty inbox returns HTTP 204 (raised as ApiError); message lifecycle is
  pending→processing→processed (skipping processing is a 422); @mention isolation means
  each agent only sees messages it sent-to or was-mentioned-in (full chain lives in our
  audit_log mirror / Human API, not any single agent's view).
- LIVE PARITY VERIFIED (outputs/band_parity_report.md): full 4-agent chain run over real
  Band for both scenarios; all 8 compared fields identical to the MockBand records:
  - naive  → strategy=naive,  synchrony=1.0,   herding_overvolt=471, ESCALATE → Operator HOLD
  - gossip → strategy=gossip, synchrony=0.167, herding_overvolt=0,   APPROVED → ACKNOWLEDGED_CLEAN
  Numbers come from the LOCAL sim; Band is a pipe, so parity is exact.
- Real keys live in `.env` (git-ignored, never committed); `.env.example` documents the keys.
- Two known issues from the coherence report RESOLVED:
  1. Compliance escalation/approval reason text is now strategy-accurate (naive no longer
     claims "gossip coordination did not eliminate..."). Guarded by a regression test.
  2. Coordinator now CONSUMES the Forecaster's high_synchrony_intervals: they are passed as
     `priority_intervals` into the gossip protocol (slot-eviction tiebreak steers dispatch
     away from flagged high-risk intervals). Default off → existing numbers unchanged;
     verified the agent-chain gossip headline numbers held (synchrony 0.167, 0 overvolt).
- **Tests: 82 passing** (81 + 1 new regression for the reason wording). Mock remains the
  default for the suite (offline, deterministic); real-Band parity proven via the live run.

## DONE (Day 5 — submission package, verified)

- `viz/NARRATION.md`: 90-second single-take narration mapped to exact demo scrubber steps/views
  (step 144 / 211, Naive-only / Gossip-only / 3-way), with honest-framing guardrails.
- `SUBMISSION.md`: structured to the lablab.ai form (title ≤50, short desc ≤255, track, technologies,
  long description: Problem / Solution / How Band was used / Evidence / What we don't claim / What's next,
  + deliverables checklist). All numbers verified, nothing inflated.
- Polish pass on `viz/gridai_demo.html` (regenerated via build_demo.py, re-verified headless):
  1. Inline SVG data-URI favicon → **0 console errors** (was a favicon 404).
  2. Each Compliance card now surfaces ONE real Band audit entry verbatim (step 7, compliance→operator,
     handoff:compliance_escalation / compliance_approval, decision + 471/0 + strategy-accurate reason).
  3. 3-way labels expanded for non-engineers: "homogeneous fleet (control)" / "heterogeneous fleet (realistic)".
- Re-verified renders at 12:00 / 17:35 naive / 17:35 gossip; screenshots refreshed in viz/screenshots/.
- Task 4 (Operator LLM narration via Featherless) SKIPPED by design: no FEATHERLESS_API_KEY in env and the
  brief marked it optional/skip-if-any-risk. Deterministic Operator record is unchanged; the demo doesn't need it.
- sim/, agents/, protocol logic UNCHANGED. 82 tests still green.

## DONE (Day 5 — GitHub Pages deployment, verified)

- GitHub repo: https://github.com/dexflex66/gridai
- GitHub Pages deployed at: **https://dexflex66.github.io/gridai/** (docs/index.html = viz/gridai_demo.html)
- Verified live: HTTP 200, loads correctly
- 82 tests still green (unchanged)

## NEXT

- Record the 90-second demo video (per viz/NARRATION.md) and submit before **June 19, 15:00 UTC**.
- Remaining lablab deliverables: slide deck (PDF).

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
- Band real-platform behaviours (not bugs, but constraints): rooms can't be given string names (task_id is a UUID); no single agent sees the whole handoff chain via the agent API (@mention isolation) — use the audit_log mirror or Human API; live chain runs ~6s/scenario over the network vs instant on mock. The 82-test suite runs on MockBand by design (offline/deterministic); running the whole suite against live Band would create a room per test and add network non-determinism — not worth it. Real-Band correctness is proven by the live parity run instead.

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
- Do not commit `.env` (real Band API keys); it is git-ignored. Never print key values to logs/terminal — reference by env-var name only
- Do not change the BandInterface abstract class or the four agents to make real Band work; only the implementation behind the interface (RealBand) and the get_band() factory may change. Real Band is a transport bus, NOT an LLM-agent rewrite (we have no LLM provider keys and our agents are deterministic compute)
- Do not run the full pytest suite against live Band (USE_REAL_BAND); it is mock-by-design. Prove real-Band behaviour with scripts/verify_band_parity.py instead
