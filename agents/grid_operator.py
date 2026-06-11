"""
Operator agent — human-in-the-loop decision stage.

Receives escalations from Compliance via Band.
Models the human checkpoint: when Compliance flags a breach or low confidence,
the Operator is presented the full context + audit trail and records a decision
(approve / hold / request_replan).

Closes the governance loop — the regulated-workflows story.

In this simulation the decision is rule-based (deterministic) to allow
automated end-to-end testing. When a real operator UI is added, only the
_decide() method changes.
"""

from agents.band_interface import BandInterface

AGENT_ID = "operator"


class OperatorAgent:
    """
    Receives compliance escalations and approvals.
    Records a decision and broadcasts it as the final governance record.
    """

    def __init__(self, band: BandInterface) -> None:
        self._band = band
        self._band.register(
            AGENT_ID,
            ["decision", "governance", "human_in_the_loop"],
        )
        self._band.subscribe(AGENT_ID, self._on_message)
        # Final decisions recorded by this agent
        self.decisions: list[dict] = []

    def _on_message(self, message: dict) -> None:
        pass  # messages drained in process_pending

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_pending(self) -> int:
        """Process all pending messages. Returns count of decisions made."""
        msgs = self._band.drain(AGENT_ID)
        processed = 0
        for msg in msgs:
            if msg["message_type"] == "handoff:compliance_escalation":
                self._handle_escalation(msg["payload"])
                processed += 1
            elif msg["message_type"] == "compliance_approval":
                self._handle_approval(msg["payload"])
                processed += 1
        return processed

    # ------------------------------------------------------------------
    # Internal handlers
    # ------------------------------------------------------------------

    def _handle_escalation(self, compliance_payload: dict) -> None:
        """
        Escalation: Compliance found battery_herding overvoltage.
        Operator reviews full context + audit chain and records a decision.
        """
        operator_decision = self._decide(compliance_payload)

        record = {
            "operator_decision": operator_decision,
            "scenario_name": compliance_payload.get("scenario_name"),
            "load_source": compliance_payload.get("load_source"),
            "compliance_finding": compliance_payload.get("audit_chain", {}).get("compliance_finding"),
            "herding_overvolt_event_count": compliance_payload.get("herding_overvolt_event_count", 0),
            "compliance_reason": compliance_payload.get("reason"),
            "audit_chain": compliance_payload.get("audit_chain", {}),
            "full_compliance_payload_available": True,
        }

        self.decisions.append(record)

        # Broadcast the final governance decision so any downstream observer can see it
        self._band.broadcast(
            sender=AGENT_ID,
            msg_type="operator_decision",
            payload=record,
        )

    def _handle_approval(self, compliance_payload: dict) -> None:
        """
        Approval: Compliance found no battery_herding overvoltage.
        Operator acknowledges and records.
        """
        record = {
            "operator_decision": "ACKNOWLEDGED_CLEAN",
            "scenario_name": compliance_payload.get("scenario_name"),
            "load_source": compliance_payload.get("load_source"),
            "compliance_finding": compliance_payload.get("audit_chain", {}).get("compliance_finding"),
            "herding_overvolt_event_count": compliance_payload.get("herding_overvolt_event_count", 0),
            "compliance_reason": compliance_payload.get("reason"),
            "audit_chain": compliance_payload.get("audit_chain", {}),
            "full_compliance_payload_available": True,
        }

        self.decisions.append(record)

        self._band.broadcast(
            sender=AGENT_ID,
            msg_type="operator_decision",
            payload=record,
        )

    def _decide(self, compliance_payload: dict) -> str:
        """
        Rule-based decision for automated testing.

        In production this would present the audit trail to a human UI
        and wait for input. Here we implement:
          - HOLD if overvolt events >= threshold (requires re-plan or manual override)
          - REQUEST_REPLAN if moderate breach count
          - APPROVE_WITH_CAVEAT if minimal breach

        Returns one of: "HOLD", "REQUEST_REPLAN", "APPROVE_WITH_CAVEAT"
        """
        herding_count = compliance_payload.get("herding_overvolt_event_count", 0)

        if herding_count >= 50:
            return "HOLD"
        if herding_count >= 10:
            return "REQUEST_REPLAN"
        return "APPROVE_WITH_CAVEAT"
