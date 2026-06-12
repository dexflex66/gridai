"""
Verification-only test suite (does NOT modify production code).

Proves three properties of the Layer 2 agent collaboration:
  PROPERTY 1 — Genuine collaboration: removing ANY of the four agents prevents a
               valid end-to-end terminal result, AND the Coordinator's output is
               materially driven by the Forecaster handoff content (not hardcoded).
  PROPERTY 2 — Provenance coherence: each compliance decision record matches the
               underlying sim run field-by-field (strategy, synchrony, breach count,
               decision).
  PROPERTY 3 — Cause separation: on a scenario where both pv_export and
               battery_herding breaches exist, only battery_herding drives
               escalation; pv_export is never flagged as a protocol failure.
"""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.mock_band import MockBand
from agents.forecaster import ForecasterAgent
from agents.coordinator import CoordinatorAgent
from agents.compliance import ComplianceAgent
from agents.grid_operator import OperatorAgent
from sim.simulator import run_scenario
from sim.aemo import load_aemo_profile


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def aemo_profile():
    profile, _ = load_aemo_profile()
    return profile


def _scenario(strategy, heterogeneous, load_source, aemo_profile=None):
    return run_scenario(
        strategy=strategy,
        heterogeneous=heterogeneous,
        n_homes=60,
        rng_seed=42,
        load_source=load_source,
        aemo_profile=aemo_profile,
    )


def _full_chain(result, scenario_name, load_source):
    band = MockBand()
    f = ForecasterAgent(band)
    c = CoordinatorAgent(band)
    cp = ComplianceAgent(band)
    o = OperatorAgent(band)
    f.run(result, scenario_name=scenario_name, load_source=load_source)
    c.process_pending()
    cp.process_pending()
    o.process_pending()
    return band, f, c, cp, o


def _herding_overvolt_events(res):
    return [e for e in res["voltage_breach_events"]
            if e["cause"] == "battery_herding" and e["band_limit_crossed"] == "upper"]


def _pv_export_events(res):
    return [e for e in res["voltage_breach_events"] if e["cause"] == "pv_export"]


def _synchrony(res, n_homes=60):
    d = np.array(res["dispatch_series"])[:, 204:260]
    return round(float(np.max(np.sum(d == 1, axis=0))) / n_homes, 3)


# ===========================================================================
# PROPERTY 1 — Genuine collaboration, not a thin wrapper
# ===========================================================================

class TestProperty1Interdependence:
    """Removing any single agent must prevent a valid end-to-end terminal result.

    Terminal result == the Operator recorded a governance decision (the closed loop).
    'Remove' == do not instantiate that agent (so nothing drains its inbox).
    """

    def _naive(self):
        return _scenario("naive", False, "synthetic")

    def test_remove_forecaster_no_terminal_result(self):
        band = MockBand()
        ForecasterAgent(band)            # present but NEVER runs (no risk window emitted)
        c = CoordinatorAgent(band)
        cp = ComplianceAgent(band)
        o = OperatorAgent(band)
        assert c.process_pending() == 0
        assert cp.process_pending() == 0
        o.process_pending()
        assert len(o.decisions) == 0, "No risk window -> Coordinator idle -> no terminal decision"

    def test_remove_coordinator_no_terminal_result(self):
        band = MockBand()
        f = ForecasterAgent(band)
        CoordinatorAgent(band)           # registered but stays silent (never processes)
        cp = ComplianceAgent(band)
        o = OperatorAgent(band)
        f.run(self._naive(), scenario_name="naive_homogeneous", load_source="synthetic")
        # Coordinator does NOT process -> no dispatch handoff
        assert cp.process_pending() == 0
        assert len(cp.decision_records) == 0
        o.process_pending()
        assert len(o.decisions) == 0, "No dispatch plan -> Compliance idle -> no terminal decision"

    def test_remove_compliance_no_terminal_result(self):
        band = MockBand()
        f = ForecasterAgent(band)
        c = CoordinatorAgent(band)
        ComplianceAgent(band)            # registered but stays silent
        o = OperatorAgent(band)
        f.run(self._naive(), scenario_name="naive_homogeneous", load_source="synthetic")
        c.process_pending()
        # Compliance does NOT process -> no review/decision -> nothing for Operator
        assert o.process_pending() == 0
        assert len(o.decisions) == 0, "No compliance decision -> no terminal Operator decision"

    def test_remove_operator_governance_loop_incomplete(self):
        band = MockBand()
        f = ForecasterAgent(band)
        c = CoordinatorAgent(band)
        cp = ComplianceAgent(band)
        # Operator NOT instantiated
        f.run(self._naive(), scenario_name="naive_homogeneous", load_source="synthetic")
        c.process_pending()
        cp.process_pending()
        audit = band.audit_log()
        escalations = [e for e in audit if e["message_type"] == "handoff:compliance_escalation"]
        op_decisions = [e for e in audit if e["message_type"] == "operator_decision"]
        assert len(escalations) == 1, "Compliance should have escalated the naive breach"
        assert len(op_decisions) == 0, "No Operator -> escalation has no terminal decision (loop open)"

    def test_coordinator_genuinely_consumes_handoff_content(self, aemo_profile):
        """The Coordinator is NOT self-sufficient: its output is determined by the
        handoff's strategy field, proving the handoff is load-bearing, not decorative.
        Same agents, different risk-window strategy -> different executed plan."""
        results = {}
        for strat, het in [("naive", False), ("gossip", True)]:
            res = _scenario(strat, het, "synthetic")
            band, *_ = _full_chain(res, f"{strat}_x", "synthetic")
            h = [e for e in band.audit_log()
                 if e["message_type"] == "handoff:dispatch_plan_and_trajectory"][0]
            results[strat] = h["payload"]["dispatch_plan"]
        # The handoff content (strategy) materially changes the Coordinator's output
        assert results["naive"]["strategy"] == "naive"
        assert results["gossip"]["strategy"] == "gossip"
        assert results["naive"]["synchrony_ratio"] != results["gossip"]["synchrony_ratio"]
        assert results["naive"]["synchrony_ratio"] == 1.0   # naive herds
        assert results["gossip"]["synchrony_ratio"] < 1.0   # gossip desynchronises


# ===========================================================================
# PROPERTY 2 — Provenance coherence (record matches the executed sim run)
# ===========================================================================

class TestProperty2ProvenanceCoherence:

    @pytest.mark.parametrize("strat,het,name,decision", [
        ("naive",  False, "naive_homogeneous",   "ESCALATE"),
        ("gossip", True,  "gossip_heterogeneous", "APPROVED"),
    ])
    def test_record_matches_sim(self, aemo_profile, strat, het, name, decision):
        res = _scenario(strat, het, "aemo", aemo_profile)
        _, _, _, cp, _ = _full_chain(res, name, "aemo")
        rec = cp.decision_records[-1]

        sim_herding = len(_herding_overvolt_events(res))
        sim_sync = _synchrony(res)

        assert rec["strategy"] == strat
        assert rec["coordinator_synchrony_ratio"] == sim_sync
        assert rec["herding_overvolt_event_count"] == sim_herding
        assert rec["compliance_decision"] == decision
        # decision is consistent with the breach count
        if decision == "ESCALATE":
            assert sim_herding > 0
        else:
            assert sim_herding == 0


# ===========================================================================
# PROPERTY 3 — Cause separation holds end to end
# ===========================================================================

class TestProperty3CauseSeparation:

    def test_only_battery_herding_drives_escalation(self):
        """Synthetic naive has BOTH pv_export and battery_herding breaches.
        Compliance must escalate on battery_herding only, never flagging pv_export."""
        res = _scenario("naive", False, "synthetic")
        sim_pv = len(_pv_export_events(res))
        sim_herding = len(_herding_overvolt_events(res))
        # precondition: both causes genuinely present in this scenario
        assert sim_pv > 0, "expected pv_export breaches present in synthetic naive"
        assert sim_herding > 0, "expected battery_herding breaches present in synthetic naive"

        _, _, _, cp, _ = _full_chain(res, "naive_homogeneous", "synthetic")
        rec = cp.decision_records[-1]

        assert rec["pv_export_event_count"] == sim_pv
        assert rec["herding_overvolt_event_count"] == sim_herding
        assert rec["compliance_decision"] == "ESCALATE"
        assert rec["pv_export_flagged_as_protocol_failure"] is False

    def test_pv_export_alone_does_not_escalate(self):
        """Gossip synthetic eliminates herding overvolt but pv_export still exists;
        Compliance must APPROVE (pv_export alone is not a protocol failure)."""
        res = _scenario("gossip", True, "synthetic")
        assert len(_pv_export_events(res)) > 0
        assert len(_herding_overvolt_events(res)) == 0
        _, _, _, cp, _ = _full_chain(res, "gossip_heterogeneous", "synthetic")
        rec = cp.decision_records[-1]
        assert rec["compliance_decision"] == "APPROVED"
        assert rec["pv_export_flagged_as_protocol_failure"] is False
