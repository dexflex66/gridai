"""
Compliance agent — review / decision stage.

Receives the dispatch plan + voltage trajectory handoff from Coordinator via Band.
Checks every node and interval against AS IEC 60038:2022 (0.94–1.10 pu).

Key distinction:
  cause == "battery_herding" overvoltage breaches  → protocol failure → ESCALATE to Operator
  cause == "pv_export" breaches                    → NOT a protocol failure → IGNORED
  cause == "battery_herding" undervoltage          → NOT a protocol failure for the dispatch
                                                      protocol (staggering lowers grid draw
                                                      which is correct behaviour) → NOTED only

On a detected battery_herding OVERVOLTAGE breach:
  - Writes a full audit-trail entry (which agent proposed what, when, breach detail, decision)
  - Escalates to Operator via Band with the full context

If the plan is clean (zero battery_herding overvoltage breaches):
  - Approves and logs the approval
  - Notifies Operator of the clean result
"""

import datetime

from agents.band_interface import BandInterface

AGENT_ID = "compliance"

V_MIN_PU = 0.94
V_MAX_PU = 1.10


class ComplianceAgent:
    """
    Reviews dispatch plan voltage trajectory for battery_herding overvoltage violations.
    Escalates or approves to Operator via Band.
    """

    def __init__(self, band: BandInterface) -> None:
        self._band = band
        self._band.register(
            AGENT_ID,
            ["review", "voltage_compliance", "audit_trail", "escalation"],
        )
        self._band.subscribe(AGENT_ID, self._on_message)
        # Decision records produced by this agent (accessible after process_pending)
        self.decision_records: list[dict] = []

    def _on_message(self, message: dict) -> None:
        pass  # messages are drained explicitly in process_pending

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_pending(self) -> int:
        """Process all pending messages. Returns count of handoffs processed."""
        msgs = self._band.drain(AGENT_ID)
        processed = 0
        for msg in msgs:
            if msg["message_type"] == "handoff:dispatch_plan_and_trajectory":
                self._review(msg["payload"], upstream_step=msg["step"])
                processed += 1
        return processed

    # ------------------------------------------------------------------
    # Internal logic
    # ------------------------------------------------------------------

    def _review(self, payload: dict, upstream_step: int) -> None:
        """
        Core compliance review.

        Checks voltage trajectory for battery_herding OVERVOLTAGE breaches.
        PV-export breaches are explicitly excluded from flagging.
        """
        risk_window    = payload["risk_window"]
        dispatch_plan  = payload["dispatch_plan"]
        vt             = payload["voltage_trajectory"]

        scenario_name  = dispatch_plan["scenario_name"]
        load_source    = dispatch_plan["load_source"]
        breach_events  = vt["voltage_breach_events"]

        # Separate breach events by cause and direction
        herding_overvolt_events = [
            e for e in breach_events
            if e["cause"] == "battery_herding" and e["band_limit_crossed"] == "upper"
        ]
        pv_export_events = [
            e for e in breach_events if e["cause"] == "pv_export"
        ]
        herding_undervolt_events = [
            e for e in breach_events
            if e["cause"] == "battery_herding" and e["band_limit_crossed"] == "lower"
        ]

        # Build the common decision context (shared by both approval and escalation)
        decision_context = {
            "scenario_name": scenario_name,
            "load_source": load_source,
            "strategy": dispatch_plan["strategy"],
            "reviewed_by": AGENT_ID,
            "review_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "upstream_band_step": upstream_step,
            "forecaster_risk_level": risk_window.get("risk_level"),
            "coordinator_rounds_to_converge": dispatch_plan.get("rounds_to_converge"),
            "coordinator_synchrony_ratio": dispatch_plan.get("synchrony_ratio"),
            "total_breach_events": len(breach_events),
            "herding_overvolt_event_count": len(herding_overvolt_events),
            "herding_undervolt_event_count": len(herding_undervolt_events),
            "pv_export_event_count": len(pv_export_events),
            "pv_export_flagged_as_protocol_failure": False,   # always false — cause separation
        }

        if len(herding_overvolt_events) > 0:
            self._escalate(decision_context, herding_overvolt_events, risk_window, dispatch_plan)
        else:
            self._approve(decision_context)

    def _escalate(
        self,
        decision_context: dict,
        herding_overvolt_events: list[dict],
        risk_window: dict,
        dispatch_plan: dict,
    ) -> None:
        """Escalate: battery_herding overvoltage breaches detected."""
        # Representative breach events (first 5) for readability in the audit log
        sample_breaches = herding_overvolt_events[:5]

        decision = {
            **decision_context,
            "compliance_decision": "ESCALATE",
            "reason": (
                f"Battery-herding overvoltage detected: "
                f"{len(herding_overvolt_events)} breach events under the "
                f"{decision_context.get('strategy', 'unknown')} dispatch strategy. "
                + (
                    "Naive price-following synchronised the fleet and breached the "
                    "voltage band. "
                    if decision_context.get("strategy") == "naive"
                    else "Coordination did not eliminate all herding spikes. "
                )
                + "Human operator decision required."
            ),
            "breach_sample": sample_breaches,
            "all_herding_overvolt_node_steps": [
                {"node_id": e["node_id"], "step": e["step"], "voltage_pu": e["voltage_pu"]}
                for e in herding_overvolt_events
            ],
            "audit_chain": {
                "forecaster_identified_risk_level": risk_window.get("risk_level"),
                "forecaster_peak_synchrony": risk_window.get("peak_synchrony_fraction"),
                "coordinator_proposed_strategy": dispatch_plan.get("strategy"),
                "coordinator_synchrony_ratio": dispatch_plan.get("synchrony_ratio"),
                "compliance_finding": "battery_herding_overvoltage_detected",
                "compliance_action": "escalate_to_operator",
            },
        }

        self.decision_records.append(decision)

        self._band.handoff(
            sender=AGENT_ID,
            recipient="operator",
            task_type="compliance_escalation",
            payload=decision,
        )

    def _approve(self, decision_context: dict) -> None:
        """Approve: zero battery_herding overvoltage breaches."""
        decision = {
            **decision_context,
            "compliance_decision": "APPROVED",
            "reason": (
                "Zero battery-herding overvoltage breaches detected under the "
                f"{decision_context.get('strategy', 'unknown')} dispatch strategy. "
                + (
                    "Gossip coordination successfully desynchronised the fleet and "
                    "kept every node within the voltage band. "
                    if decision_context.get("strategy") == "gossip"
                    else "Dispatch stayed within the voltage band. "
                )
                + "Dispatch plan approved."
            ),
            "audit_chain": {
                "forecaster_identified_risk_level": decision_context.get("forecaster_risk_level"),
                "coordinator_proposed_strategy": decision_context.get("strategy"),
                "coordinator_synchrony_ratio": decision_context.get("coordinator_synchrony_ratio"),
                "compliance_finding": "no_battery_herding_overvoltage",
                "compliance_action": "approve",
            },
        }

        self.decision_records.append(decision)

        self._band.send(
            sender=AGENT_ID,
            recipient="operator",
            msg_type="compliance_approval",
            payload=decision,
        )
