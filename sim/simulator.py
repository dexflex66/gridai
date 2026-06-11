"""
Core simulation engine.

Takes a fleet of homes + a dispatch schedule and simulates the full 24h,
computing per-timestep:
  - Battery SOC for each home
  - Net power injection per home (positive = export, negative = import)
  - Per-home voltage along feeder
  - Aggregate feeder demand

Also provides a convenience function run_scenario() that ties together
profile generation, strategy selection, and simulation.
"""

import numpy as np

from sim.feeder import (
    compute_voltages,
    check_voltage_violations,
    V_MIN_PU,
    V_MAX_PU,
    N_HOMES_DEFAULT,
    N_STEPS,
    FEEDER_IMPEDANCE_PU,
)
from sim.profiles import (
    TIMESTEP_MINUTES,
    BATTERY_MAX_RATE_KW,
    price_signal,
    make_homes,
)
from sim.strategies import naive_dispatch, gossip_dispatch


def simulate(homes: list, schedule: np.ndarray) -> dict:
    """
    Run a 24h simulation given homes and a pre-computed dispatch schedule.

    schedule: (N, N_STEPS), 1=discharge, -1=charge, 0=idle
      (naive and gossip strategies only use 0 and 1)

    Returns a results dict with full time series:
      soc_series: (N, N_STEPS) SOC at end of each step
      dispatch_series: (N, N_STEPS) copy of schedule
      net_power_series: (N, N_STEPS) net power in kW (positive=export)
      voltage_series: (N, N_STEPS) pu voltage
      aggregate_demand_series: (N_STEPS,) total feeder demand kW (positive=import from grid)
      voltage_violations: (N, N_STEPS) boolean
      breach_flags: (N_STEPS,) True if ANY home violated voltage at that step
      home_positions: list of int (feeder position per home)
    """
    N = len(homes)
    dt_h = TIMESTEP_MINUTES / 60.0

    soc_series = np.zeros((N, N_STEPS))
    net_power_series = np.zeros((N, N_STEPS))
    voltage_series = np.zeros((N, N_STEPS))
    voltage_violations = np.zeros((N, N_STEPS), dtype=bool)
    breach_flags = np.zeros(N_STEPS, dtype=bool)

    # Initialise SOC from home parameters
    soc = np.array([h["soc_initial"] for h in homes], dtype=float)

    for t in range(N_STEPS):
        step_net_power = np.zeros(N)

        for i, home in enumerate(homes):
            base_load = home["base_load"][t]
            pv_gen = home["pv_gen"][t]
            cap = home["battery_capacity_kwh"]
            rate = home["battery_max_rate_kw"]
            eff = home["efficiency"]

            battery_power_kw = 0.0  # positive = discharge (export), negative = charge

            if schedule[i, t] == 1:
                # Discharge
                max_discharge_kwh = min(rate * dt_h, (soc[i] - home["soc_min"]) * cap)
                if max_discharge_kwh > 0.001:
                    discharge_kwh = max_discharge_kwh
                    battery_power_kw = discharge_kwh / dt_h
                    soc[i] -= discharge_kwh / cap

            elif schedule[i, t] == -1:
                # Charge (not used in current strategies but supported)
                max_charge_kwh = min(rate * dt_h, (home["soc_max"] - soc[i]) * cap)
                if max_charge_kwh > 0.001:
                    charge_kwh = max_charge_kwh
                    battery_power_kw = -charge_kwh / dt_h
                    soc[i] += (charge_kwh * eff) / cap

            # Net injection to grid: PV + battery discharge - base load
            # Positive = exporting to grid (or net generation)
            # Negative = importing from grid
            net_injection = pv_gen + battery_power_kw - base_load
            step_net_power[i] = net_injection
            soc_series[i, t] = soc[i]

        net_power_series[:, t] = step_net_power

        # Compute voltages for this timestep
        v = compute_voltages(step_net_power)
        voltage_series[:, t] = v
        viols = check_voltage_violations(v)
        voltage_violations[:, t] = viols
        if np.any(viols):
            breach_flags[t] = True

    # Aggregate demand: sum of imports (negative net_power across homes)
    # When net_power is negative, home is importing. Feeder demand = -sum(net_power)
    # but we want: total grid draw = sum(max(0, -net_injection))
    # For display we report total grid demand positive = grid is supplying load
    aggregate_demand_series = -np.sum(net_power_series, axis=0)

    return {
        "soc_series": soc_series,
        "dispatch_series": schedule,
        "net_power_series": net_power_series,
        "voltage_series": voltage_series,
        "voltage_violations": voltage_violations,
        "breach_flags": breach_flags,
        "aggregate_demand_series": aggregate_demand_series,
        "home_positions": [h["position"] for h in homes],
    }


def run_scenario(
    strategy: str,
    heterogeneous: bool,
    n_homes: int = N_HOMES_DEFAULT,
    rng_seed: int = 42,
) -> dict:
    """
    Run a complete scenario end-to-end.

    strategy: "naive" or "gossip"
    heterogeneous: True = varied thresholds/SOC, False = identical

    Returns result dict augmented with:
      strategy, heterogeneous, n_homes,
      rounds_to_converge (gossip only, else None),
      gossip_log (gossip only, else []),
      homes_meta: list of per-home parameters (no numpy arrays, for JSON)
    """
    homes = make_homes(n_homes, heterogeneous=heterogeneous, rng_seed=rng_seed)
    price = price_signal()

    rounds_to_converge = None
    gossip_log = []

    if strategy == "naive":
        schedule = naive_dispatch(homes, price)
    elif strategy == "gossip":
        schedule, rounds_to_converge, gossip_log = gossip_dispatch(
            homes, price, feeder_impedance=FEEDER_IMPEDANCE_PU
        )
    else:
        raise ValueError(f"Unknown strategy: {strategy}")

    result = simulate(homes, schedule)
    result["strategy"] = strategy
    result["heterogeneous"] = heterogeneous
    result["n_homes"] = n_homes
    result["rounds_to_converge"] = rounds_to_converge
    result["gossip_log"] = gossip_log

    # Strip numpy arrays from homes for JSON serialisation
    result["homes_meta"] = [
        {
            "id": h["id"],
            "position": h["position"],
            "has_pv": h["has_pv"],
            "soc_initial": h["soc_initial"],
            "willingness_threshold": h["willingness_threshold"],
            "battery_capacity_kwh": h["battery_capacity_kwh"],
            "battery_max_rate_kw": h["battery_max_rate_kw"],
        }
        for h in homes
    ]

    return result


def compute_metrics(result: dict) -> dict:
    """
    Compute headline metrics from a simulation result.
    """
    demand = result["aggregate_demand_series"]
    voltages = result["voltage_series"]
    breach_flags = result["breach_flags"]

    peak_demand = float(np.max(demand))
    mean_demand = float(np.mean(demand))

    # ALL violations (including PV midday)
    violation_steps = int(np.sum(breach_flags))
    violation_hours = violation_steps * TIMESTEP_MINUTES / 60.0

    # Battery-window violations only: evening peak 17:00-21:40 (steps 204-260)
    # This isolates battery-related violations from PV-related violations.
    # The demo story is about battery herding, not PV export management.
    BAT_WIN_START = 204   # 17:00
    BAT_WIN_END = 260     # 21:40
    v_bat = voltages[:, BAT_WIN_START:BAT_WIN_END]
    bat_overvolt_steps = int(np.sum(np.any(v_bat > V_MAX_PU, axis=0)))
    bat_undervolt_steps = int(np.sum(np.any(v_bat < V_MIN_PU, axis=0)))
    bat_violation_steps = bat_overvolt_steps + bat_undervolt_steps
    bat_violation_hours = round(bat_violation_steps * TIMESTEP_MINUTES / 60.0, 2)

    # PV-window violations: midday 10:00-15:00 (steps 120-180)
    PV_WIN_START = 120
    PV_WIN_END = 180
    v_pv = voltages[:, PV_WIN_START:PV_WIN_END]
    pv_overvolt_steps = int(np.sum(np.any(v_pv > V_MAX_PU, axis=0)))

    # Synchrony: fraction of homes discharging at single busiest step
    dispatch = result["dispatch_series"]
    max_simultaneous = int(np.max(np.sum(dispatch == 1, axis=0)))
    synchrony_ratio = max_simultaneous / result["n_homes"]

    # Battery-window demand metrics
    bat_demand = demand[BAT_WIN_START:BAT_WIN_END]
    bat_peak_demand = float(np.max(bat_demand))
    bat_min_demand = float(np.min(bat_demand))
    # Demand range = max - min. Captures both the export spike and demand cliff.
    # Naive herding: large swing (e.g. 350 kW). Gossip: small swing (e.g. 80 kW).
    bat_demand_range = bat_peak_demand - bat_min_demand

    # Peak demand step (overall)
    peak_step = int(np.argmax(demand))

    return {
        "peak_demand_kw": round(peak_demand, 2),
        "bat_peak_demand_kw": round(bat_peak_demand, 2),
        "bat_min_demand_kw": round(bat_min_demand, 2),
        "bat_demand_range_kw": round(bat_demand_range, 2),
        "mean_demand_kw": round(mean_demand, 2),
        "violation_steps_total": violation_steps,
        "violation_hours_total": round(violation_hours, 2),
        "bat_violation_steps": bat_violation_steps,
        "bat_violation_hours": bat_violation_hours,
        "bat_overvolt_steps": bat_overvolt_steps,
        "bat_undervolt_steps": bat_undervolt_steps,
        "pv_overvolt_steps": pv_overvolt_steps,
        "max_simultaneous_discharge": max_simultaneous,
        "synchrony_ratio": round(synchrony_ratio, 3),
        "peak_step": peak_step,
        "peak_time_hhmm": f"{(peak_step * 5) // 60:02d}:{(peak_step * 5) % 60:02d}",
        "any_breach": bool(np.any(breach_flags)),
        "any_bat_breach": bool(bat_violation_steps > 0),
        "total_breach_home_steps": int(np.sum(result["voltage_violations"])),
    }
