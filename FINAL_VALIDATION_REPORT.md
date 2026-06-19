# GridAI Final Validation Report

- **Branch:** `main`
- **Commit:** `cc9d9f3`
- **Test command:** `pytest`
- **Test result:** 89 passed, 0 failed

## Headline Metrics (AEMO load profile)

| Scenario | OV events | UV events | OV steps | Synchrony | MaxSim | Rounds |
|---|---|---|---|---|---|---|
| Naive hom AEMO | 471 | 516 | 14 | 1.000 | 60 | N/A |
| Naive het AEMO | 15 | 364 | 2 | 0.700 | 42 | N/A |
| Gossip hom AEMO | 0 | 510 | 0 | 0.367 | 22 | 2 |
| Gossip het AEMO | 0 | 435 | 0 | 0.167 | 10 | 1 |

### Key metric definitions

- **OV/UV events:** Individual battery-herding voltage breach events (each home-step where voltage crossed the AS IEC 60038:2022 band 0.94–1.10 pu). Cause-separated from PV export.
- **Synchrony:** `max_simultaneous_discharge / N` — ratio of homes discharging at the peak step.
- **Rounds:** Gossip convergence rounds required.

## Honest limitation

Residual undervoltage remains visible on `main`. The headline gossip-heterogeneous AEMO scenario reports **435 battery-herding undervolt events**. This is disclosed transparently and is the primary tuning target. A prototyped voltage-aware extension on branch `voltage-aware-edge-coverage` reduces this by ~90% in experiments but is **not merged** into `main` and is **not** part of this submission.

GridAI is a hackathon prototype showing fail-closed coordination for home battery dispatch. It uses gossip-style scheduling and explicit validation to reduce unsafe herding behaviour in simulation, while transparently reporting residual voltage limitations.
