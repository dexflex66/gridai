# GridAI — Coherence Verification Report

Verification-only session. No production code (`sim/`, `agents/`) was modified.
All numbers below come from real test runs and live sim/agent execution.

- **Committed state verified:** `39bf312`
- **Total tests passing:** **81** (72 pre-existing + 9 new in `tests/test_coherence_verification.py`)
- **Tests added:** `tests/test_coherence_verification.py` only.

---

## PROPERTY 1 — Genuine collaboration, not a thin wrapper

### Removal matrix (terminal result = Operator records a governance decision)

| Removed agent | Observed effect | Terminal result? | Verdict |
|---|---|---|---|
| **Forecaster** | Coordinator processes 0, Compliance processes 0, Operator decisions = 0 | No | **PASS** (chain breaks) |
| **Coordinator** | No dispatch handoff; Compliance processes 0, records = 0; Operator decisions = 0 | No | **PASS** (chain breaks) |
| **Compliance** | Operator processes 0; Operator decisions = 0 | No | **PASS** (chain breaks) |
| **Operator** | Compliance escalation sent = 1, Operator decisions = 0 (governance loop left open) | No | **PASS** (loop incomplete) |

Every agent is load-bearing: removing any one prevents a valid end-to-end result.

### Evidence the Coordinator genuinely CONSUMES the Forecaster handoff

The Day 3 Option A refactor moved strategy execution into the Coordinator, so the
critical risk was that the Coordinator became self-sufficient and ignored the
handoff. It does not. The Coordinator has **no hardcoded scenario** — it reads the
scenario configuration from the handoff and its output changes with the handoff
content:

| `risk_window.strategy` (handoff in) | `dispatch_plan.strategy` (Coordinator out) | synchrony |
|---|---|---|
| `naive`  | `naive`  | 1.0 |
| `gossip` | `gossip` | 0.2 |

Same four agents, same code — only the handoff content differs, and the Coordinator's
executed plan differs accordingly. With **no** handoff, the Coordinator processes 0
messages and emits nothing. The handoff is therefore **load-bearing, not decorative**.

### Honest nuance (reported, not a failure)

The Coordinator consumes only the **scenario-parameter** fields of the handoff
(`strategy`, `heterogeneous`, `n_homes`, `load_source`). It does **not** consume the
Forecaster's **analytical** output (`high_synchrony_intervals`,
`current_plan_breach_events`, `bat_window_*` stats). Of the Forecaster's analysis,
only `risk_level` and `peak_synchrony_fraction` are consumed downstream — by
**Compliance**, for the audit record (`forecaster_risk_level`,
`forecaster_peak_synchrony`) — not by the Coordinator.

Implications, stated plainly:
- The collaboration is genuine at the orchestration level (every handoff is necessary
  for a terminal result, and handoff content drives behaviour).
- But the **Forecaster is the most lightly-used agent**: the Coordinator would behave
  identically given the same scenario parameters regardless of the Forecaster's risk
  assessment, and a few Forecaster fields (`high_synchrony_intervals`,
  `current_plan_breach_events`) are currently consumed by **no** downstream agent
  (`current_plan_breach_events` became dead after the Option A refactor).

This is a design observation for post-kickoff, not a correctness failure.

---

## PROPERTY 2 — Provenance coherence (record matches the executed run)

Compliance decision record cross-checked field-by-field against a fresh sim run of
the same scenario (AEMO-driven, seed 42):

### NAIVE (`naive_homogeneous`, AEMO)
| Field | Record | Sim | Match |
|---|---|---|---|
| strategy | `naive` | `naive` | ✓ |
| synchrony_ratio | 1.0 | 1.0 | ✓ |
| herding_overvolt_event_count | 471 | 471 | ✓ |
| pv_export_event_count | 0 | 0 | ✓ |
| decision | ESCALATE | (471 breaches > 0) | ✓ consistent |

### GOSSIP (`gossip_heterogeneous`, AEMO)
| Field | Record | Sim | Match |
|---|---|---|---|
| strategy | `gossip` | `gossip` | ✓ |
| synchrony_ratio | 0.167 | 0.167 | ✓ |
| herding_overvolt_event_count | 0 | 0 | ✓ |
| pv_export_event_count | 0 | 0 | ✓ |
| decision | APPROVED | (0 breaches) | ✓ consistent |

The Day 3 provenance bug stays dead: record and sim come from the same run, and the
decision is consistent with the breach count in both cases.

---

## PROPERTY 3 — Cause separation holds end to end

Verified on **synthetic naive**, the scenario where both causes coexist (AEMO's
normalised profile has no midday PV-export spike, so it cannot exercise this):

| Cause | Event count (record == sim) | Drives escalation? |
|---|---|---|
| `battery_herding` (overvolt) | 511 | **Yes** — escalation reason cites it |
| `pv_export` | 893 | **No** — `pv_export_flagged_as_protocol_failure = false` |

- Decision: **ESCALATE**, driven solely by the 511 battery_herding overvoltage events.
- Despite 893 pv_export events present, `pv_export_flagged_as_protocol_failure` is
  `false`.
- Cross-check (gossip synthetic): pv_export events still present, herding overvolt = 0
  → Compliance **APPROVES**. PV-export alone never escalates.

Cause separation holds end to end.

### Minor wording issue (reported, not fixed — verification-only)

On a **naive** run the escalation `reason` string reads *"...Gossip coordination did
not eliminate all herding spikes..."* even though the naive run involves no gossip.
The decision, counts, and routing are all correct; only the human-readable reason text
is misleading. Worth a one-line wording fix in `agents/compliance.py` in a future
(non-verification) session.

---

## VERDICT

**This reads as a genuine multi-agent collaboration layer, not a wrapper.** All four
agents are load-bearing — removing any one prevents a valid end-to-end result — and the
Coordinator's behaviour is materially driven by the Forecaster handoff content. The one
honest caveat is that the Forecaster's *analytical* output is under-consumed (only
`risk_level`/`peak_synchrony` reach Compliance for logging; the Coordinator uses just
the scenario parameters), so the Forecaster is the agent whose handoff is closest to
informational rather than decisive. No handoff is fully decorative, and no property failed.
