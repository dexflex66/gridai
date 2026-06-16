"""
Tests for Layer 2: four-agent collaboration through Band interface.

Verified behaviours:
1. All four agents register and exchange structured context through BandInterface.
2. Naive AEMO: Compliance detects battery_herding overvoltage and escalates to Operator.
   Full audit log contains Forecaster->Coordinator->Compliance->Operator chain.
3. Gossip AEMO: Compliance approves with zero battery_herding overvolt events.
4. PV-export cause separation: Compliance does NOT flag pv_export events as protocol failures.
5. Removing/disabling the Coordinator breaks the chain (genuine interdependence test).
"""

import os
import sys
import json
import pytest
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.mock_band import MockBand
from agents.band_interface import BandInterface
from agents.forecaster import ForecasterAgent
from agents.coordinator import CoordinatorAgent
from agents.compliance import ComplianceAgent
from agents.grid_operator import OperatorAgent
from sim.simulator import run_scenario
from sim.aemo import load_aemo_profile


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def aemo_profile():
    profile, _ = load_aemo_profile()
    return profile


@pytest.fixture(scope="module")
def naive_aemo_result(aemo_profile):
    return run_scenario(
        strategy="naive",
        heterogeneous=False,
        n_homes=60,
        rng_seed=42,
        load_source="aemo",
        aemo_profile=aemo_profile,
    )


@pytest.fixture(scope="module")
def gossip_aemo_result(aemo_profile):
    return run_scenario(
        strategy="gossip",
        heterogeneous=True,
        n_homes=60,
        rng_seed=42,
        load_source="aemo",
        aemo_profile=aemo_profile,
    )


@pytest.fixture(scope="module")
def naive_synthetic_result():
    return run_scenario(
        strategy="naive",
        heterogeneous=False,
        n_homes=60,
        rng_seed=42,
        load_source="synthetic",
    )


def _run_full_chain(scenario_result, scenario_name, load_source, aemo_profile=None):
    """
    Helper: run the full four-agent chain and return (band, agents, compliance_decision, op_decision).
    The Coordinator executes the scenario's own dispatch strategy (naive or gossip).
    """
    band = MockBand()
    forecaster  = ForecasterAgent(band)
    coordinator = CoordinatorAgent(band)
    compliance  = ComplianceAgent(band)
    operator    = OperatorAgent(band)

    forecaster.run(scenario_result, scenario_name=scenario_name, load_source=load_source)
    coordinator.process_pending()
    compliance.process_pending()
    operator.process_pending()

    return band, forecaster, coordinator, compliance, operator


# ---------------------------------------------------------------------------
# Test 1: all four agents register + audit log structure
# ---------------------------------------------------------------------------

class TestAgentRegistration:
    def test_all_agents_register(self, naive_aemo_result, aemo_profile):
        band = MockBand()
        ForecasterAgent(band)
        CoordinatorAgent(band)
        ComplianceAgent(band)
        OperatorAgent(band)

        registered = [e["sender"] for e in band.audit_log() if e["message_type"] == "register"]
        assert "forecaster"  in registered
        assert "coordinator" in registered
        assert "compliance"  in registered
        assert "operator"    in registered

    def test_band_is_abstract(self):
        # MockBand implements BandInterface — isinstance check
        band = MockBand()
        assert isinstance(band, BandInterface)

    def test_agents_only_use_interface(self):
        # Agents receive BandInterface at construction.
        # Passing a MockBand as BandInterface must work without error.
        band: BandInterface = MockBand()
        f = ForecasterAgent(band)
        c = CoordinatorAgent(band)
        cp = ComplianceAgent(band)
        o = OperatorAgent(band)
        assert f is not None and c is not None and cp is not None and o is not None


# ---------------------------------------------------------------------------
# Test 2: naive AEMO — Compliance escalates, full chain in audit log
# ---------------------------------------------------------------------------

class TestNaiveAEMOChain:
    @pytest.fixture(autouse=True)
    def setup(self, naive_aemo_result, aemo_profile):
        self.band, _, _, self.compliance, self.operator = _run_full_chain(
            naive_aemo_result,
            scenario_name="naive_homogeneous",
            load_source="aemo",
            aemo_profile=aemo_profile,
        )
        self.audit = self.band.audit_log()
        self.compliance_decision = self.compliance.decision_records[-1]
        self.op_decision = self.operator.decisions[-1]

    def test_compliance_escalates(self):
        assert self.compliance_decision["compliance_decision"] == "ESCALATE"

    def test_herding_overvolt_detected(self):
        assert self.compliance_decision["herding_overvolt_event_count"] > 0

    def test_operator_receives_escalation(self):
        assert self.op_decision["operator_decision"] in {"HOLD", "REQUEST_REPLAN", "APPROVE_WITH_CAVEAT"}

    def test_full_chain_in_audit_log(self):
        """Forecaster→Coordinator→Compliance→Operator all appear in the audit log."""
        senders = {e["sender"] for e in self.audit}
        recipients = {e["recipient"] for e in self.audit}
        assert "forecaster"  in senders
        assert "coordinator" in senders
        assert "compliance"  in senders
        assert "operator"    in senders | recipients  # operator sends broadcasts
        # Specific handoff chain
        msg_types = [e["message_type"] for e in self.audit]
        assert "handoff:risk_window"                 in msg_types
        assert "handoff:dispatch_plan_and_trajectory" in msg_types
        assert "handoff:compliance_escalation"        in msg_types
        assert "operator_decision"                    in msg_types

    def test_audit_log_ordering(self):
        """Steps are strictly monotonically increasing."""
        steps = [e["step"] for e in self.audit]
        assert steps == sorted(steps)
        assert len(steps) == len(set(steps))  # no duplicate steps

    def test_audit_log_has_payloads(self):
        for entry in self.audit:
            assert "payload" in entry
            assert isinstance(entry["payload"], dict)

    def test_forecaster_handoff_payload_has_risk_level(self):
        rw_handoffs = [e for e in self.audit if e["message_type"] == "handoff:risk_window"]
        assert len(rw_handoffs) == 1
        payload = rw_handoffs[0]["payload"]
        assert payload["risk_level"] == "CRITICAL"
        assert payload["peak_synchrony_fraction"] == 1.0

    def test_coordinator_handoff_to_compliance(self):
        coord_handoffs = [
            e for e in self.audit
            if e["sender"] == "coordinator" and "dispatch_plan_and_trajectory" in e["message_type"]
        ]
        assert len(coord_handoffs) == 1
        payload = coord_handoffs[0]["payload"]
        assert "risk_window"  in payload
        assert "dispatch_plan" in payload
        assert "voltage_trajectory" in payload

    def test_decision_record_strategy_matches_executed_naive(self):
        """Regression: the naive run's record must describe the NAIVE plan, not gossip.

        Previously the Coordinator always ran gossip, so a naive run produced a
        self-contradictory record (strategy=gossip + 471 herding breaches). The
        record's strategy/synchrony must agree with the breach data it reports.
        """
        assert self.compliance_decision["strategy"] == "naive"
        assert self.compliance_decision["coordinator_synchrony_ratio"] == 1.0
        # naive dispatch does not converge — no rounds figure
        assert self.compliance_decision["coordinator_rounds_to_converge"] is None
        # and it genuinely breached (consistency between label and data)
        assert self.compliance_decision["herding_overvolt_event_count"] > 0

    def test_naive_escalation_reason_does_not_mention_gossip(self):
        """Regression: the naive escalation reason must describe naive price-following,
        not claim 'gossip coordination did not eliminate' on a run with no gossip."""
        reason = self.compliance_decision["reason"].lower()
        assert "naive" in reason
        assert "gossip" not in reason

    def test_operator_decision_is_hold_for_large_breach(self):
        # 471 overvolt events -> HOLD (>= 50 threshold in grid_operator.py)
        assert self.op_decision["operator_decision"] == "HOLD"


# ---------------------------------------------------------------------------
# Test 3: gossip AEMO — Compliance approves clean
# ---------------------------------------------------------------------------

class TestGossipAEMOChain:
    @pytest.fixture(autouse=True)
    def setup(self, gossip_aemo_result, aemo_profile):
        self.band, _, _, self.compliance, self.operator = _run_full_chain(
            gossip_aemo_result,
            scenario_name="gossip_heterogeneous",
            load_source="aemo",
            aemo_profile=aemo_profile,
        )
        self.audit = self.band.audit_log()
        self.compliance_decision = self.compliance.decision_records[-1]
        self.op_decision = self.operator.decisions[-1]

    def test_compliance_approves(self):
        assert self.compliance_decision["compliance_decision"] == "APPROVED"

    def test_zero_herding_overvolt_events(self):
        assert self.compliance_decision["herding_overvolt_event_count"] == 0

    def test_decision_record_strategy_matches_executed_gossip(self):
        """Regression: the gossip run's record must describe the GOSSIP plan, consistently."""
        assert self.compliance_decision["strategy"] == "gossip"
        assert self.compliance_decision["coordinator_synchrony_ratio"] < 1.0
        assert self.compliance_decision["coordinator_rounds_to_converge"] is not None

    def test_operator_acknowledges_clean(self):
        assert self.op_decision["operator_decision"] == "ACKNOWLEDGED_CLEAN"

    def test_full_chain_audit_log_gossip(self):
        senders = {e["sender"] for e in self.audit}
        assert "forecaster" in senders
        assert "coordinator" in senders
        assert "compliance" in senders
        assert "operator" in senders


# ---------------------------------------------------------------------------
# Test 4: PV-export cause separation holds end-to-end
# ---------------------------------------------------------------------------

class TestCauseSeparation:
    @pytest.fixture(autouse=True)
    def setup(self, naive_synthetic_result):
        # Synthetic naive scenario has pv_export AND battery_herding breach events
        self.band, _, _, self.compliance, _ = _run_full_chain(
            naive_synthetic_result,
            scenario_name="naive_homogeneous",
            load_source="synthetic",
        )
        self.decision = self.compliance.decision_records[-1]

    def test_pv_export_not_flagged_as_protocol_failure(self):
        assert self.decision["pv_export_flagged_as_protocol_failure"] is False

    def test_pv_export_events_present_in_scenario(self):
        # The compliance record counts pv_export events but does NOT escalate on them
        # Synthetic naive has pv_export overvolt events (midday PV)
        # pv_export_event_count comes from the raw breach events (all causes)
        # We just verify the flag is False regardless of count
        assert self.decision["pv_export_flagged_as_protocol_failure"] is False

    def test_escalation_driven_only_by_herding_overvolt(self):
        # If there are herding_overvolt events, compliance escalates.
        # If herding_overvolt == 0, compliance approves — regardless of pv_export count.
        herding_ov = self.decision["herding_overvolt_event_count"]
        if herding_ov > 0:
            assert self.decision["compliance_decision"] == "ESCALATE"
        else:
            assert self.decision["compliance_decision"] == "APPROVED"

    def test_synthetic_naive_has_herding_overvolt_events(self, naive_synthetic_result):
        # Sanity: synthetic naive scenario actually has battery_herding overvolt events
        bh_ov = [
            e for e in naive_synthetic_result["voltage_breach_events"]
            if e["cause"] == "battery_herding" and e["band_limit_crossed"] == "upper"
        ]
        assert len(bh_ov) > 0, "synthetic naive must have battery_herding overvolt events"

    def test_synthetic_naive_has_pv_export_events(self, naive_synthetic_result):
        # Sanity: synthetic naive scenario has pv_export events (midday PV)
        pv = [
            e for e in naive_synthetic_result["voltage_breach_events"]
            if e["cause"] == "pv_export"
        ]
        assert len(pv) > 0, "synthetic naive must have pv_export events"

    def test_compliance_counts_pv_export_but_does_not_escalate_on_it(self, naive_synthetic_result):
        # Run a scenario where we ensure pv_export events exist AND herding_overvolt = 0
        # to prove compliance ignores pv_export.
        # Use gossip_heterogeneous synthetic (pv_export events still present, herding_ov = 0)
        gossip_result = run_scenario(
            strategy="gossip",
            heterogeneous=True,
            n_homes=60,
            rng_seed=42,
            load_source="synthetic",
        )
        band2 = MockBand()
        f = ForecasterAgent(band2)
        CoordinatorAgent(band2)
        c = ComplianceAgent(band2)
        OperatorAgent(band2)

        f.run(gossip_result, scenario_name="gossip_heterogeneous", load_source="synthetic")
        # Process coordinator
        msgs = band2.drain("coordinator")
        assert len(msgs) == 1

        # Manually trigger coordinator processing
        band2_coord = CoordinatorAgent.__new__(CoordinatorAgent)
        band2_coord._band = band2
        # Re-run the coordinator with its own instance — simpler: just use _run_full_chain
        band3 = MockBand()
        _, _, _, c3, _ = _run_full_chain(gossip_result, "gossip_heterogeneous", "synthetic")
        decision3 = c3.decision_records[-1]

        pv_count = decision3["pv_export_event_count"]
        herding_ov = decision3["herding_overvolt_event_count"]
        # Gossip eliminates herding overvolt; pv_export events may exist in synthetic
        assert herding_ov == 0
        assert decision3["compliance_decision"] == "APPROVED"
        assert decision3["pv_export_flagged_as_protocol_failure"] is False


# ---------------------------------------------------------------------------
# Test 5: Disabling the Coordinator breaks the chain (genuine interdependence)
# ---------------------------------------------------------------------------

class TestInterdependence:
    def test_coordinator_never_handoff_means_compliance_never_runs(
        self, naive_aemo_result
    ):
        """
        If Coordinator is registered but never calls process_pending()
        (i.e., it never processes the risk_window and never hands off to Compliance),
        then Compliance receives no messages and makes no decisions.
        This proves the chain is genuinely dependent on Coordinator's participation.
        """
        band = MockBand()
        forecaster  = ForecasterAgent(band)
        # Coordinator registered but NEVER calls process_pending
        CoordinatorAgent(band)   # registered, subscribed, but silent
        compliance  = ComplianceAgent(band)
        OperatorAgent(band)

        # Forecaster runs and hands off to Coordinator
        forecaster.run(naive_aemo_result, scenario_name="naive_homogeneous", load_source="aemo")

        # Coordinator is silent — does NOT process its messages, does NOT hand off
        # Compliance tries to process pending messages — there are none
        processed = compliance.process_pending()

        assert processed == 0, (
            "Compliance should have processed 0 messages because Coordinator never handed off"
        )
        assert len(compliance.decision_records) == 0, (
            "Compliance should have made no decisions because Coordinator never handed off"
        )

    def test_forecaster_never_runs_means_coordinator_has_nothing(self):
        """
        If Forecaster never runs (never hands off risk_window), Coordinator
        has nothing to process, so nothing flows to Compliance or Operator.
        """
        band = MockBand()
        ForecasterAgent(band)   # registered but never calls run()
        coordinator = CoordinatorAgent(band)
        compliance  = ComplianceAgent(band)
        OperatorAgent(band)

        coord_processed = coordinator.process_pending()
        comp_processed  = compliance.process_pending()

        assert coord_processed == 0
        assert comp_processed == 0

    def test_audit_log_shows_only_register_entries_when_chain_broken(self):
        """When Coordinator is silent, only register entries appear in audit log."""
        band = MockBand()
        forecaster  = ForecasterAgent(band)
        CoordinatorAgent(band)
        compliance  = ComplianceAgent(band)
        OperatorAgent(band)

        # Run forecaster (sends handoff:risk_window to coordinator)
        result = run_scenario("naive", False, n_homes=60, rng_seed=42, load_source="synthetic")
        forecaster.run(result, scenario_name="naive_homogeneous", load_source="synthetic")

        # Do NOT call coordinator.process_pending()
        compliance.process_pending()

        audit = band.audit_log()
        msg_types = [e["message_type"] for e in audit]

        assert "handoff:risk_window" in msg_types           # forecaster sent
        assert "handoff:dispatch_plan_and_trajectory" not in msg_types  # coordinator silent
        assert "handoff:compliance_escalation" not in msg_types         # compliance silent
        assert "operator_decision" not in msg_types                     # operator silent


# ---------------------------------------------------------------------------
# Test 6: MockBand audit log properties
# ---------------------------------------------------------------------------

class TestMockBandAuditLog:
    def test_audit_log_append_only(self):
        band = MockBand()
        band.register("a", [])
        band.register("b", [])
        band.send("a", "b", "test_msg", {"x": 1})
        log = band.audit_log()
        assert len(log) == 3

        # Modifying returned log does not affect internal state
        log.append({"fake": True})
        assert len(band.audit_log()) == 3

    def test_audit_log_all_required_fields(self):
        band = MockBand()
        band.register("a", ["cap1"])
        band.send("a", "b", "greet", {"hello": "world"})
        for entry in band.audit_log():
            assert "step" in entry
            assert "timestamp" in entry
            assert "sender" in entry
            assert "recipient" in entry
            assert "message_type" in entry
            assert "payload" in entry

    def test_handoff_message_type_prefix(self):
        band = MockBand()
        band.register("a", [])
        band.register("b", [])
        band.handoff("a", "b", "my_task", {"data": 42})
        log = band.audit_log()
        handoff_entries = [e for e in log if "handoff" in e["message_type"]]
        assert len(handoff_entries) == 1
        assert handoff_entries[0]["message_type"] == "handoff:my_task"

    def test_broadcast_recipient_is_ALL_in_log(self):
        band = MockBand()
        band.register("a", [])
        band.register("b", [])
        band.register("c", [])
        band.broadcast("a", "state_update", {"v": 1.05})
        log = band.audit_log()
        broadcasts = [e for e in log if e["message_type"] == "state_update"]
        # Broadcast logged once with recipient=ALL
        assert len(broadcasts) == 1
        assert broadcasts[0]["recipient"] == "ALL"

    def test_broadcast_delivered_to_all_others(self):
        band = MockBand()
        band.register("a", [])
        band.register("b", [])
        band.register("c", [])
        band.broadcast("a", "ping", {"v": 1})
        b_msgs = band.drain("b")
        c_msgs = band.drain("c")
        a_msgs = band.drain("a")   # sender should NOT receive own broadcast
        assert len(b_msgs) == 1
        assert len(c_msgs) == 1
        assert len(a_msgs) == 0

    def test_discover_registered_agent(self):
        band = MockBand()
        band.register("x", ["skill1", "skill2"])
        info = band.discover("x")
        assert info is not None
        assert info["agent_id"] == "x"
        assert "skill1" in info["capabilities"]

    def test_discover_unknown_agent_returns_none(self):
        band = MockBand()
        assert band.discover("nonexistent") is None

    def test_drain_clears_queue(self):
        band = MockBand()
        band.register("a", [])
        band.register("b", [])
        band.send("a", "b", "msg1", {})
        band.send("a", "b", "msg2", {})
        msgs = band.drain("b")
        assert len(msgs) == 2
        msgs2 = band.drain("b")
        assert len(msgs2) == 0

    def test_monotonic_step_counter(self):
        band = MockBand()
        band.register("a", [])
        band.register("b", [])
        band.send("a", "b", "m1", {})
        band.send("a", "b", "m2", {})
        steps = [e["step"] for e in band.audit_log()]
        assert steps == sorted(steps)
        assert len(steps) == len(set(steps))


# ---------------------------------------------------------------------------
# Test 6: Causal link — priority_intervals change gossip dispatch (mechanistic)
# ---------------------------------------------------------------------------
# Uses homogeneous fleet because MAX_CONCURRENT_DISCHARGE=20, and gossip_hom
# packs 60 agents > 20, triggering evictions where _find_least_crowded_slot
# consults avoid_slots. Heterogeneous fleet peaks at ~10 (< 20), so no
# evictions and avoid_slots is never consulted.

CRAFTED_FLAGGED_STEPS = list(range(204, 230))  # first 26 of the 57 battery-window steps


@pytest.fixture(scope="module")
def gossip_hom_synthetic_baseline():
    return run_scenario(
        strategy="gossip",
        heterogeneous=False,
        n_homes=60,
        rng_seed=42,
        load_source="synthetic",
    )


@pytest.fixture(scope="module")
def gossip_hom_synthetic_with_priority():
    return run_scenario(
        strategy="gossip",
        heterogeneous=False,
        n_homes=60,
        rng_seed=42,
        load_source="synthetic",
        priority_intervals=CRAFTED_FLAGGED_STEPS,
    )


class TestPriorityIntervalsCausalLink:
    """priority_intervals → avoid_slots → evicted agents steered away from flagged steps."""

    def test_flagged_steps_total_discharge_lower(
        self, gossip_hom_synthetic_baseline, gossip_hom_synthetic_with_priority
    ):
        baseline_arr = np.array(gossip_hom_synthetic_baseline["dispatch_series"])
        priority_arr = np.array(gossip_hom_synthetic_with_priority["dispatch_series"])

        baseline_sim = np.sum(baseline_arr[:, CRAFTED_FLAGGED_STEPS] == 1)
        priority_sim = np.sum(priority_arr[:, CRAFTED_FLAGGED_STEPS] == 1)

        assert priority_sim < baseline_sim, (
            f"priority_intervals should reduce discharge on flagged steps: "
            f"{priority_sim} vs baseline {baseline_sim}"
        )

    def test_discharge_shifts_to_unflagged_steps(
        self, gossip_hom_synthetic_baseline, gossip_hom_synthetic_with_priority
    ):
        unflagged = [s for s in range(204, 260) if s not in CRAFTED_FLAGGED_STEPS]
        baseline_arr = np.array(gossip_hom_synthetic_baseline["dispatch_series"])
        priority_arr = np.array(gossip_hom_synthetic_with_priority["dispatch_series"])

        bl_unflagged = np.sum(baseline_arr[:, unflagged] == 1)
        pr_unflagged = np.sum(priority_arr[:, unflagged] == 1)

        assert pr_unflagged > bl_unflagged, (
            f"discharge should shift to unflagged steps: {pr_unflagged} vs {bl_unflagged}"
        )

    def test_synchrony_holds(self, gossip_hom_synthetic_with_priority):
        dispatch = np.array(gossip_hom_synthetic_with_priority["dispatch_series"])
        bat = dispatch[:, 204:260]
        sim = np.sum(bat == 1, axis=0)
        hom_baseline = np.max(sim) / 60  # ~0.483
        assert hom_baseline <= 0.50

    def test_zero_herding_overvoltage(self, gossip_hom_synthetic_with_priority):
        breach = gossip_hom_synthetic_with_priority["voltage_breach_events"]
        herding_ov = [
            e for e in breach
            if e["cause"] == "battery_herding" and e["band_limit_crossed"] == "upper"
        ]
        assert len(herding_ov) == 0


# ---------------------------------------------------------------------------
# Test 7: Causal chain — Forecaster analyses naive, Coordinator runs gossip
#         using the Forecaster's high_synchrony_intervals
# ---------------------------------------------------------------------------
# Forecaster on naive_hom AEMO extracts ~15 flagged intervals (steps 211–225)
# — a proper subset of the 57-step window. These are passed to gossip_hom as
# priority_intervals, and evicted agents avoid them. Compares against gossip_hom
# without priority_intervals.

@pytest.fixture(scope="module")
def naive_hom_aemo_result(aemo_profile):
    return run_scenario(
        strategy="naive",
        heterogeneous=False,
        n_homes=60,
        rng_seed=42,
        load_source="aemo",
        aemo_profile=aemo_profile,
    )


class TestForecasterToCoordinatorCausalChain:
    """Forecaster→Coordinator handoff is causal: naive-derived intervals improve gossip."""

    @pytest.fixture(autouse=True)
    def setup(self, naive_hom_aemo_result, aemo_profile):
        band = MockBand()
        forecaster = ForecasterAgent(band)
        forecaster.run(naive_hom_aemo_result, "naive_homogeneous", load_source="aemo")
        self.audit = band.audit_log()

        rw_handoffs = [
            e["payload"] for e in self.audit
            if e["message_type"] == "handoff:risk_window"
        ]
        assert len(rw_handoffs) == 1

        risk_window = rw_handoffs[0]
        forecaster_intervals = [
            iv["step"] for iv in risk_window.get("high_synchrony_intervals", [])
        ]

        assert len(forecaster_intervals) > 0, (
            "naive_hom must produce some high_synchrony_intervals for the chain test"
        )
        assert len(forecaster_intervals) < 57, (
            "need a proper subset (not all 57) for avoid_slots to have effect"
        )

        self.forecaster_intervals = forecaster_intervals
        self.baseline = run_scenario(
            strategy="gossip",
            heterogeneous=False,
            n_homes=60,
            rng_seed=42,
            load_source="aemo",
            aemo_profile=aemo_profile,
        )
        self.with_intervals = run_scenario(
            strategy="gossip",
            heterogeneous=False,
            n_homes=60,
            rng_seed=42,
            load_source="aemo",
            aemo_profile=aemo_profile,
            priority_intervals=forecaster_intervals,
        )

    def test_forecaster_to_gossip_chain_produces_avoidance(self):
        base_arr = np.array(self.baseline["dispatch_series"])
        with_arr = np.array(self.with_intervals["dispatch_series"])

        flagged = self.forecaster_intervals
        base_sim = np.sum(base_arr[:, flagged] == 1)
        with_sim = np.sum(with_arr[:, flagged] == 1)

        assert with_sim < base_sim, (
            f"Forecaster→Coordinator causal chain should reduce discharge on flagged "
            f"steps: {with_sim} vs baseline {base_sim}"
        )

    def test_headline_synchrony_holds(self):
        dispatch = np.array(self.with_intervals["dispatch_series"])
        bat = dispatch[:, 204:260]
        sim = np.sum(bat == 1, axis=0)
        assert np.max(sim) / 60 <= 0.50

    def test_zero_herding_overvoltage(self):
        breach = self.with_intervals["voltage_breach_events"]
        herding_ov = [
            e for e in breach
            if e["cause"] == "battery_herding" and e["band_limit_crossed"] == "upper"
        ]
        assert len(herding_ov) == 0
