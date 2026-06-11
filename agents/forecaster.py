"""
Forecaster agent — planning stage.

Reads the grid state + AEMO/synthetic demand data for the day.
Identifies:
  - The evening oversupply/peak window (steps 204-260, 17:00-21:40)
  - Intervals where battery-herding risk is highest (where price threshold
    is likely to trigger simultaneous discharge across the fleet)

Produces a structured "risk_window" context object and hands it off
to the Coordinator through Band.
"""

import numpy as np

from agents.band_interface import BandInterface

AGENT_ID = "forecaster"

# Evening battery window (mirrors simulator.py constants)
BAT_WIN_START = 204   # step 204 = 17:00
BAT_WIN_END   = 260   # step 260 = 21:40

# Price-herding risk threshold: steps where many batteries likely trigger at once
# Naive batteries fire when price >= willingness_threshold.
# Homogeneous fleet: all thresholds ~0.50 => any price spike in window = mass trigger.
# We flag intervals where the naive strategy fires >= 40% of the fleet simultaneously.
HIGH_SYNCHRONY_THRESHOLD = 0.40   # fraction of fleet


class ForecasterAgent:
    """
    Analyses grid state and identifies battery-herding risk windows.
    Outputs a handoff to Coordinator via Band.
    """

    def __init__(self, band: BandInterface) -> None:
        self._band = band
        self._band.register(AGENT_ID, ["planning", "demand_forecast", "risk_identification"])
        self._received: list[dict] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        scenario_result: dict,
        scenario_name: str,
        load_source: str,
    ) -> None:
        """
        Analyse scenario_result (from sim/simulator.py run_scenario) and hand off
        a structured risk_window context to the Coordinator.

        scenario_result keys used:
          dispatch_series    (N, N_STEPS) int — naive schedule
          voltage_series     (N, N_STEPS) float
          voltage_breach_events list of breach event dicts
          n_homes            int
          strategy           str
          aggregate_demand_series (N_STEPS,) float
        """
        n_homes = scenario_result["n_homes"]
        dispatch = np.array(scenario_result["dispatch_series"])   # (N, N_STEPS)
        voltage_series = np.array(scenario_result["voltage_series"])
        demand = np.array(scenario_result["aggregate_demand_series"])
        breach_events = scenario_result["voltage_breach_events"]

        # --- Identify high-synchrony intervals in the battery window ---
        bat_window_dispatch = dispatch[:, BAT_WIN_START:BAT_WIN_END]
        simultaneous_discharge = np.sum(bat_window_dispatch == 1, axis=0)  # shape (window_len,)
        synchrony_fracs = simultaneous_discharge / n_homes

        high_risk_intervals = []
        for offset, frac in enumerate(synchrony_fracs):
            step = BAT_WIN_START + offset
            if frac >= HIGH_SYNCHRONY_THRESHOLD:
                high_risk_intervals.append({
                    "step": int(step),
                    "time_hhmm": f"{(step * 5) // 60:02d}:{(step * 5) % 60:02d}",
                    "synchrony_fraction": round(float(frac), 3),
                    "simultaneous_count": int(simultaneous_discharge[offset]),
                })

        # --- Summarise battery-window voltage state ---
        bat_voltages = voltage_series[:, BAT_WIN_START:BAT_WIN_END]
        bat_demand = demand[BAT_WIN_START:BAT_WIN_END]

        # --- Identify battery_herding breach events ---
        herding_breaches = [
            e for e in breach_events if e["cause"] == "battery_herding"
        ]
        herding_overvolt = [e for e in herding_breaches if e["band_limit_crossed"] == "upper"]

        # --- Build risk_window context object ---
        # Include the current scenario's breach events so the Coordinator can
        # forward them to Compliance as the "current plan trajectory" for review.
        # This is the core traceability: Compliance sees what would happen under
        # the current (naive) plan, not just the proposed gossip plan.
        risk_window = {
            "scenario_name": scenario_name,
            "load_source": load_source,
            "strategy": scenario_result["strategy"],
            "n_homes": n_homes,
            "battery_window": {
                "start_step": BAT_WIN_START,
                "end_step": BAT_WIN_END,
                "start_time": "17:00",
                "end_time": "21:40",
            },
            "high_synchrony_intervals": high_risk_intervals,
            "high_synchrony_interval_count": len(high_risk_intervals),
            "peak_synchrony_fraction": round(float(np.max(synchrony_fracs)), 3),
            "peak_simultaneous_discharge": int(np.max(simultaneous_discharge)),
            "bat_window_peak_demand_kw": round(float(np.max(bat_demand)), 2),
            "bat_window_voltage_max_pu": round(float(np.max(bat_voltages)), 4),
            "bat_window_voltage_min_pu": round(float(np.min(bat_voltages)), 4),
            "herding_breach_event_count": len(herding_breaches),
            "herding_overvolt_event_count": len(herding_overvolt),
            "risk_level": _classify_risk(len(high_risk_intervals), float(np.max(synchrony_fracs))),
            # Current plan's voltage breach events — passed through to Compliance
            "current_plan_breach_events": breach_events,
        }

        self._band.handoff(
            sender=AGENT_ID,
            recipient="coordinator",
            task_type="risk_window",
            payload=risk_window,
        )


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _classify_risk(high_sync_count: int, peak_sync_frac: float) -> str:
    if peak_sync_frac >= 0.90:
        return "CRITICAL"
    if peak_sync_frac >= 0.40:
        return "HIGH"
    if high_sync_count > 0:
        return "MODERATE"
    return "LOW"
