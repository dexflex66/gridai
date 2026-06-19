# GridAI Final Validation Report

- **Branch:** `main`
- **Commit:** `178e92f`
- **Date:** 2026-06-19 03:48 UTC
- **Test command:** `pytest`

## Headline Metrics (AEMO load profile)

| Scenario | OV events | UV events | OV steps | Synchrony | MaxSim | Rounds |
|---|---|---|---|---|---|---|
| Naive hom AEMO | 471 | 516 | 14 | 1.000 | 60 | None |
| Naive het AEMO | 15 | 364 | 2 | 0.700 | 42 | None |
| Gossip hom AEMO | 0 | 510 | 0 | 0.367 | 22 | 2 |
| Gossip het AEMO | 0 | 435 | 0 | 0.167 | 10 | 1 |

## Test Results

........................................................................ [ 80%]
.................                                                        [100%]
89 passed in 7.73s

**All tests pass.**

## Limitations

GridAI is a hackathon prototype showing fail-closed coordination for home battery dispatch.
It uses gossip-style scheduling and explicit validation to reduce unsafe herding behaviour
in simulation, while transparently reporting residual voltage limitations.

- **Residual undervoltage:** The headline gossip-heterogeneous AEMO scenario reports
  **435 battery-herding undervolt events**. This is disclosed honestly and is the
  primary tuning target. A prototyped voltage-aware extension (branch
  `voltage-aware-edge-coverage`) reduces this by ~90%% in experiments.
- Not production-ready.
- Not decentralised — the Coordinator allocates dispatch slots using global fleet state. A fully decentralised peer-to-peer implementation is the next step.
- Not real-feeder validated.
- Not grid-agnostic.
