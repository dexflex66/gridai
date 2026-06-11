"""
Coordinator agent — execution stage.

Receives the risk_window handoff from Forecaster via Band.
Runs the gossip-protocol coordination over the battery fleet (Layer 1),
producing a dispatch plan and the resulting per-node voltage trajectory.

Hands off to Compliance via Band:
  - current_plan_trajectory: the naive plan's voltage trajectory (from Forecaster context)
    — this is what would happen without coordination; Compliance reviews THIS for violations
  - proposed_plan_trajectory: the gossip plan's voltage trajectory (the proposed solution)
    — included for comparison and future use
  - dispatch_plan: structured summary of the gossip plan

Real delegation: Coordinator does NOT decide compliance. It executes the
coordination protocol and passes results downstream for review.
"""

import numpy as np

from agents.band_interface import BandInterface
from sim.simulator import run_scenario, compute_metrics
from sim.aemo import load_aemo_profile

AGENT_ID = "coordinator"


class CoordinatorAgent:
    """
    Receives risk_window from Forecaster.
    Runs gossip coordination to produce a proposed plan.
    Passes current plan trajectory (from Forecaster context) + proposed plan to Compliance.
    """

    def __init__(self, band: BandInterface) -> None:
        self._band = band
        self._band.register(
            AGENT_ID,
            ["execution", "gossip_coordination", "dispatch_planning"],
        )
        self._band.subscribe(AGENT_ID, self._on_message)

    def _on_message(self, message: dict) -> None:
        pass  # messages drained in process_pending

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_pending(self) -> int:
        """
        Process all pending messages. Returns count of handoffs processed.
        """
        msgs = self._band.drain(AGENT_ID)
        processed = 0
        for msg in msgs:
            if msg["message_type"] == "handoff:risk_window":
                self._handle_risk_window(msg["payload"])
                processed += 1
        return processed

    # ------------------------------------------------------------------
    # Internal handlers
    # ------------------------------------------------------------------

    def _handle_risk_window(self, risk_window: dict) -> None:
        """
        Run gossip coordination and hand off results to Compliance.

        The 'current plan' trajectory comes from Forecaster's risk context
        (the naive scenario breach events). Compliance reviews those for violations.
        The 'proposed plan' trajectory is the gossip run's result.
        """
        scenario_name = risk_window["scenario_name"]
        load_source   = risk_window["load_source"]
        n_homes       = risk_window["n_homes"]

        # --- Run the GOSSIP scenario as the proposed coordination plan ---
        aemo_profile = None
        if load_source == "aemo":
            aemo_profile, _ = load_aemo_profile()

        gossip_result = run_scenario(
            strategy="gossip",
            heterogeneous=True,
            n_homes=n_homes,
            rng_seed=42,
            load_source=load_source,
            aemo_profile=aemo_profile,
        )
        gossip_metrics = compute_metrics(gossip_result)

        # --- Dispatch plan summary ---
        dispatch = np.array(gossip_result["dispatch_series"])
        BAT_WIN_START = 204
        BAT_WIN_END   = 260
        bat_dispatch  = dispatch[:, BAT_WIN_START:BAT_WIN_END]
        simultaneous  = np.sum(bat_dispatch == 1, axis=0)

        dispatch_plan = {
            "scenario_name": scenario_name,
            "load_source": load_source,
            "strategy": "gossip",
            "heterogeneous": True,
            "n_homes": n_homes,
            "rounds_to_converge": gossip_result["rounds_to_converge"],
            "battery_window_simultaneous_discharge": simultaneous.tolist(),
            "peak_simultaneous": int(np.max(simultaneous)),
            "synchrony_ratio": round(float(np.max(simultaneous)) / n_homes, 3),
            "metrics": gossip_metrics,
        }

        # --- Current plan trajectory: the naive plan's breach events ---
        # These come from the Forecaster's risk context.
        # Compliance reviews these to detect battery_herding overvoltage violations.
        current_plan_breach_events = risk_window.get("current_plan_breach_events", [])

        current_plan_trajectory = {
            "strategy": risk_window["strategy"],     # "naive" or "gossip"
            "voltage_breach_events": current_plan_breach_events,
            "bat_overvolt_steps": _count_by_cause_dir(current_plan_breach_events, "battery_herding", "upper"),
            "bat_undervolt_steps": _count_by_cause_dir(current_plan_breach_events, "battery_herding", "lower"),
            "pv_overvolt_steps": _count_by_cause_dir(current_plan_breach_events, "pv_export", "upper"),
        }

        # --- Proposed plan trajectory: gossip result ---
        voltage_series = np.array(gossip_result["voltage_series"])
        proposed_plan_trajectory = {
            "strategy": "gossip",
            "voltage_series": voltage_series.tolist(),
            "voltage_breach_events": gossip_result["voltage_breach_events"],
            "bat_overvolt_steps": gossip_metrics["bat_overvolt_steps"],
            "bat_undervolt_steps": gossip_metrics["bat_undervolt_steps"],
        }

        self._band.handoff(
            sender=AGENT_ID,
            recipient="compliance",
            task_type="dispatch_plan_and_trajectory",
            payload={
                "risk_window": risk_window,
                "dispatch_plan": dispatch_plan,
                # current_plan = what is being reviewed for compliance violations
                "voltage_trajectory": current_plan_trajectory,
                # proposed_plan = gossip solution (for reference / future review)
                "proposed_plan_trajectory": proposed_plan_trajectory,
            },
        )


def _count_by_cause_dir(events: list, cause: str, direction: str) -> int:
    """Count unique (step,) intervals that have at least one event matching cause+direction."""
    steps = {e["step"] for e in events if e["cause"] == cause and e["band_limit_crossed"] == direction}
    return len(steps)
