"""
Layer 2 agent runner.

Executes the full four-agent chain on both naive and gossip AEMO scenarios.
The Forecaster analyses the scenario, the Coordinator runs gossip coordination,
Compliance reviews for battery_herding overvoltage, and Operator records
the governance decision.

Emits to outputs/:
  band_audit_naive_aemo.json     — full Band audit log for naive run
  band_audit_gossip_aemo.json    — full Band audit log for gossip run
  compliance_decision_naive_aemo.json
  compliance_decision_gossip_aemo.json
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.mock_band import MockBand
from agents.forecaster import ForecasterAgent
from agents.coordinator import CoordinatorAgent
from agents.compliance import ComplianceAgent
from agents.grid_operator import OperatorAgent
from sim.runner import numpy_to_python
from sim.simulator import run_scenario
from sim.aemo import load_aemo_profile

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs")


def run_agent_chain(
    scenario_name: str,
    strategy: str,
    load_source: str,
    heterogeneous: bool,
    aemo_profile=None,
) -> dict:
    """
    Execute the full Forecaster→Coordinator→Compliance→Operator chain
    for one scenario. Returns a summary dict.
    """
    print(f"\n{'='*60}")
    print(f"Agent chain: {scenario_name} [{load_source}]")
    print(f"{'='*60}")

    # --- Instantiate fresh Band and agents for this run ---
    band = MockBand()
    forecaster  = ForecasterAgent(band)
    coordinator = CoordinatorAgent(band)
    compliance  = ComplianceAgent(band)
    operator    = OperatorAgent(band)

    # --- Layer 1: run the scenario to give Forecaster real data ---
    print(f"  [Layer 1] Running {strategy} scenario...", end=" ", flush=True)
    result = run_scenario(
        strategy=strategy,
        heterogeneous=heterogeneous,
        n_homes=60,
        rng_seed=42,
        load_source=load_source,
        aemo_profile=aemo_profile,
    )
    print("done")

    # --- Agent 1: Forecaster analyses grid state ---
    print("  [Forecaster] Identifying risk window...", end=" ", flush=True)
    forecaster.run(result, scenario_name=scenario_name, load_source=load_source)
    print(f"done  (handed off to coordinator via Band)")

    # --- Agent 2: Coordinator receives handoff, runs gossip, hands off to Compliance ---
    print("  [Coordinator] Processing risk_window handoff...", end=" ", flush=True)
    processed = coordinator.process_pending()
    assert processed == 1, f"Expected 1 handoff processed, got {processed}"
    print(f"done  (ran gossip coordination, handed off to compliance)")

    # --- Agent 3: Compliance reviews voltage trajectory ---
    print("  [Compliance] Reviewing dispatch plan...", end=" ", flush=True)
    processed = compliance.process_pending()
    assert processed == 1, f"Expected 1 handoff processed by compliance, got {processed}"
    decision = compliance.decision_records[-1]
    print(f"done  → {decision['compliance_decision']}")

    # --- Agent 4: Operator processes compliance result ---
    print("  [Operator] Recording governance decision...", end=" ", flush=True)
    processed = operator.process_pending()
    assert processed == 1, f"Expected 1 decision by operator, got {processed}"
    op_decision = operator.decisions[-1]
    print(f"done  → {op_decision['operator_decision']}")

    # --- Collect outputs ---
    audit = band.audit_log()

    # Confirm all four agents participated
    agent_ids_in_log = {e["sender"] for e in audit} | {e["recipient"] for e in audit}
    for aid in ["forecaster", "coordinator", "compliance", "operator"]:
        assert aid in agent_ids_in_log, f"Agent {aid} missing from audit log"

    print(f"\n  Audit log: {len(audit)} entries")
    print(f"  Compliance decision: {decision['compliance_decision']}")
    print(f"  Operator decision:   {op_decision['operator_decision']}")
    print(f"  herding_overvolt_events: {decision['herding_overvolt_event_count']}")
    print(f"  pv_export_events (not flagged): {decision['pv_export_event_count']}")

    return {
        "scenario_name": scenario_name,
        "load_source": load_source,
        "strategy": strategy,
        "band_audit": audit,
        "compliance_decision": decision,
        "operator_decision": op_decision,
    }


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load AEMO profile once
    aemo_profile, aemo_meta = load_aemo_profile()
    print(f"AEMO profile: {aemo_meta['representative_date']} ({aemo_meta['reason']})")

    # --- Run 1: NAIVE scenario → should trigger Compliance escalation ---
    naive_run = run_agent_chain(
        scenario_name="naive_homogeneous",
        strategy="naive",
        load_source="aemo",
        heterogeneous=False,
        aemo_profile=aemo_profile,
    )

    # --- Run 2: GOSSIP scenario → Compliance should approve clean ---
    gossip_run = run_agent_chain(
        scenario_name="gossip_heterogeneous",
        strategy="gossip",
        load_source="aemo",
        heterogeneous=True,
        aemo_profile=aemo_profile,
    )

    # --- Write audit logs ---
    for tag, run_data in [("naive_aemo", naive_run), ("gossip_aemo", gossip_run)]:
        audit_path = os.path.join(OUTPUT_DIR, f"band_audit_{tag}.json")
        with open(audit_path, "w") as f:
            json.dump(numpy_to_python(run_data["band_audit"]), f, indent=2)
        print(f"\nAudit log written: {audit_path}")

        decision_path = os.path.join(OUTPUT_DIR, f"compliance_decision_{tag}.json")
        with open(decision_path, "w") as f:
            json.dump(numpy_to_python(run_data["compliance_decision"]), f, indent=2)
        print(f"Compliance decision written: {decision_path}")

    # --- Final summary ---
    print("\n" + "="*60)
    print("LAYER 2 AGENT CHAIN SUMMARY")
    print("="*60)
    for tag, run_data in [("NAIVE", naive_run), ("GOSSIP", gossip_run)]:
        cd = run_data["compliance_decision"]
        od = run_data["operator_decision"]
        print(f"\n{tag}:")
        print(f"  Compliance: {cd['compliance_decision']}")
        print(f"  Operator:   {od['operator_decision']}")
        print(f"  herding_overvolt_events: {cd['herding_overvolt_event_count']}")
        print(f"  pv_export_events (ignored): {cd['pv_export_event_count']}")
        print(f"  Band audit entries: {len(run_data['band_audit'])}")


if __name__ == "__main__":
    main()
