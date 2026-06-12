# GridAI — Real Band Parity Report

Full four-agent chain run over the REAL Band platform (`https://app.band.ai`), one shared room per scenario, compared field-by-field against the committed MockBand records.

## naive_homogeneous (naive)

- Band room: `3954e8f3-8f0c-4dee-9be1-51e0c97fc694`  ·  chain completed in 6.2s
- Operator decision: **HOLD**

| field | mock | real Band | match |
|---|---|---|---|
| scenario_name | `naive_homogeneous` | `naive_homogeneous` | ✓ |
| strategy | `naive` | `naive` | ✓ |
| coordinator_synchrony_ratio | `1.0` | `1.0` | ✓ |
| coordinator_rounds_to_converge | `None` | `None` | ✓ |
| herding_overvolt_event_count | `471` | `471` | ✓ |
| pv_export_event_count | `0` | `0` | ✓ |
| pv_export_flagged_as_protocol_failure | `False` | `False` | ✓ |
| compliance_decision | `ESCALATE` | `ESCALATE` | ✓ |

Band native trail (Coordinator's view; @mention isolation means each agent sees only messages it sent-to or was-mentioned-in):

- `GridAI Forecaster` → coordinator : handoff:risk_window
- `GridAI Operator` → ALL : operator_decision

## gossip_heterogeneous (gossip)

- Band room: `86ea849e-7ce7-42ba-9752-07cedf2d9d3b`  ·  chain completed in 6.0s
- Operator decision: **ACKNOWLEDGED_CLEAN**

| field | mock | real Band | match |
|---|---|---|---|
| scenario_name | `gossip_heterogeneous` | `gossip_heterogeneous` | ✓ |
| strategy | `gossip` | `gossip` | ✓ |
| coordinator_synchrony_ratio | `0.167` | `0.167` | ✓ |
| coordinator_rounds_to_converge | `1` | `1` | ✓ |
| herding_overvolt_event_count | `0` | `0` | ✓ |
| pv_export_event_count | `0` | `0` | ✓ |
| pv_export_flagged_as_protocol_failure | `False` | `False` | ✓ |
| compliance_decision | `APPROVED` | `APPROVED` | ✓ |

Band native trail (Coordinator's view; @mention isolation means each agent sees only messages it sent-to or was-mentioned-in):

- `GridAI Forecaster` → coordinator : handoff:risk_window
- `GridAI Operator` → ALL : operator_decision

## Verdict

ALL FIELDS MATCH — real Band run is identical to the mock.
