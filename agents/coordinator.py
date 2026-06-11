"""
Coordinator agent — execution stage.

Receives the risk_window handoff from Forecaster via Band.
Executes the dispatch strategy the scenario specifies over the battery fleet
(Layer 1), producing a dispatch plan and the resulting per-node voltage
trajectory:
  - naive run  -> naive price-following dispatch (herding) -> breaches
  - gossip run -> gossip-protocol coordination            -> flattened, clean

Hands off to Compliance via Band:
  - dispatch_plan: structured summary of the EXECUTED plan (strategy, synchrony,
    convergence, metrics) — always describes the strategy actually run
  - voltage_trajectory: the executed plan's own per-node voltage breach events,
    which Compliance reviews for violations

Because the dispatch_plan and the reviewed trajectory both come from the same
executed run, the strategy label can never disagree with the breach data.

Real delegation: Coordinator does NOT decide compliance. It executes the
dispatch strategy and passes results downstream for review.
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
        Execute the scenario's own dispatch strategy and hand off the resulting
        plan + voltage trajectory to Compliance.

        The Coordinator runs the SAME strategy the scenario specifies (naive for
        the baseline run, gossip for the coordinated run), so dispatch_plan and
        the reviewed trajectory always describe one and the same executed plan.
        """
        scenario_name = risk_window["scenario_name"]
        load_source   = risk_window["load_source"]
        n_homes       = risk_window["n_homes"]
        strategy      = risk_window["strategy"]
        heterogeneous = risk_window["heterogeneous"]

        # --- Execute the scenario's own dispatch strategy ---
        aemo_profile = None
        if load_source == "aemo":
            aemo_profile, _ = load_aemo_profile()

        result = run_scenario(
            strategy=strategy,
            heterogeneous=heterogeneous,
            n_homes=n_homes,
            rng_seed=42,
            load_source=load_source,
            aemo_profile=aemo_profile,
        )
        metrics = compute_metrics(result)

        # --- Dispatch plan summary (reflects the EXECUTED strategy) ---
        dispatch = np.array(result["dispatch_series"])
        BAT_WIN_START = 204
        BAT_WIN_END   = 260
        bat_dispatch  = dispatch[:, BAT_WIN_START:BAT_WIN_END]
        simultaneous  = np.sum(bat_dispatch == 1, axis=0)

        dispatch_plan = {
            "scenario_name": scenario_name,
            "load_source": load_source,
            "strategy": strategy,
            "heterogeneous": heterogeneous,
            "n_homes": n_homes,
            # naive dispatch does not converge, so rounds_to_converge is None there
            "rounds_to_converge": result.get("rounds_to_converge"),
            "battery_window_simultaneous_discharge": simultaneous.tolist(),
            "peak_simultaneous": int(np.max(simultaneous)),
            "synchrony_ratio": round(float(np.max(simultaneous)) / n_homes, 3),
            "metrics": metrics,
        }

        # --- Voltage trajectory under the executed plan (what Compliance reviews) ---
        breach_events = result["voltage_breach_events"]
        voltage_trajectory = {
            "strategy": strategy,
            "voltage_breach_events": breach_events,
            "bat_overvolt_steps": _count_by_cause_dir(breach_events, "battery_herding", "upper"),
            "bat_undervolt_steps": _count_by_cause_dir(breach_events, "battery_herding", "lower"),
            "pv_overvolt_steps": _count_by_cause_dir(breach_events, "pv_export", "upper"),
        }

        self._band.handoff(
            sender=AGENT_ID,
            recipient="compliance",
            task_type="dispatch_plan_and_trajectory",
            payload={
                "risk_window": risk_window,
                "dispatch_plan": dispatch_plan,
                # the executed plan's own trajectory — what Compliance reviews
                "voltage_trajectory": voltage_trajectory,
            },
        )


def _count_by_cause_dir(events: list, cause: str, direction: str) -> int:
    """Count unique (step,) intervals that have at least one event matching cause+direction."""
    steps = {e["step"] for e in events if e["cause"] == cause and e["band_limit_crossed"] == direction}
    return len(steps)
