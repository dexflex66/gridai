"""
Oracle feasibility experiment.

Answers: Is full voltage compliance (zero overvolt AND zero undervolt) physically
achievable given the current battery constraints (60 homes × 10 kWh, 5 kW rate,
3-step max discharge) on the given demand/PV traces?

The oracle has perfect foresight: it knows every home's SOC, base load, PV
generation, and the feeder voltage model. It computes an optimal dispatch
schedule that minimises undervoltage while keeping overvoltage = 0.

This is NOT a deployable protocol — it is a feasibility bound.
"""

import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sim.feeder import V_SOURCE_PU, V_MIN_PU, V_MAX_PU, FEEDER_IMPEDANCE_PU
from sim.profiles import (
    N_STEPS, BATTERY_CAPACITY_KWH, BATTERY_MAX_RATE_KW,
    BATTERY_SOC_MIN, BATTERY_SOC_MAX, BATTERY_EFFICIENCY,
    PRICE_PEAK_START_STEP, PRICE_PEAK_END_STEP,
)
from sim.strategies import (
    MAX_CONCURRENT_DISCHARGE, DISPATCH_WINDOW_START, DISPATCH_WINDOW_END,
    DISPATCH_WINDOW_LEN,
)


def compute_base_net_power(homes, step):
    """
    Net power at a step assuming NO battery action.
    Positive = export (PV > load), negative = import (load > PV).
    Returns: (N,) array of net power in kW.
    """
    N = len(homes)
    net = np.zeros(N)
    for i, h in enumerate(homes):
        net[i] = h["pv_gen"][step] - h["base_load"][step]
    return net


def voltage_at_node(net_power):
    """Compute voltage at the far end (node N-1)."""
    prefix_sum = np.cumsum(net_power)
    return V_SOURCE_PU + FEEDER_IMPEDANCE_PU * prefix_sum[-1]


def compute_voltages_all(net_power):
    """Compute voltage at all nodes."""
    prefix_sum = np.cumsum(net_power)
    return V_SOURCE_PU + FEEDER_IMPEDANCE_PU * prefix_sum


def minimum_homes_to_prevent_uv(homes, step):
    """
    Minimum number of homes that must discharge at this step
    to prevent V[N-1] from dropping below V_MIN_PU.
    
    Assumes discharging home contributes a fixed +delta_kW swing
    (from its current net without battery to its net with battery export).
    """
    N = len(homes)
    base_net = compute_base_net_power(homes, step)
    
    # Net power contribution of a discharging home at this step:
    # Without battery: base_net[i] = PV - load (negative in evening)
    # With battery:    base_net[i] + battery_rate (battery adds export)
    discharge_swing = BATTERY_MAX_RATE_KW  # a discharging home adds +5 kW export
    
    # Starting voltage with zero discharge
    v0 = voltage_at_node(base_net)
    if v0 >= V_MIN_PU:
        return 0
    
    # How many discharging homes needed to lift V to V_MIN?
    v_gap = V_MIN_PU - v0
    # Each discharging home adds FEEDER_IMPEDANCE_PU * discharge_swing to V[N-1]
    k_needed = int(np.ceil(v_gap / (FEEDER_IMPEDANCE_PU * discharge_swing)))
    return min(k_needed, N)


def maximum_homes_without_ov(homes, step):
    """
    Maximum number of homes that can discharge at this step
    without causing V[N-1] to exceed V_MAX_PU.
    """
    N = len(homes)
    base_net = compute_base_net_power(homes, step)
    discharge_swing = BATTERY_MAX_RATE_KW
    
    # Starting voltage with zero discharge (could be negative base net in evening)
    v0 = voltage_at_node(base_net)
    
    # Headroom to V_MAX
    v_headroom = V_MAX_PU - v0
    if v_headroom <= 0:
        return 0
    
    k_max = int(np.floor(v_headroom / (FEEDER_IMPEDANCE_PU * discharge_swing)))
    return min(k_max, MAX_CONCURRENT_DISCHARGE)


def oracle_best_dispatch(homes, verbose=True):
    """
    Compute the optimal dispatch schedule using perfect foresight.
    
    Returns:
      schedule: (N, N_STEPS) int, 1=discharge
      metrics: dict with overvolt, undervolt, synchrony, etc.
      feasible: bool — whether full compliance (overvolt=0 AND undervolt=0) was achieved
    """
    N = len(homes)
    dt_h = 5.0 / 60.0
    
    # Per-home available energy (how many steps each home can discharge)
    # Each home can discharge at most ~3 steps (limited by SOC, rate)
    max_steps_per_home = np.zeros(N, dtype=int)
    for i, h in enumerate(homes):
        usable_energy_kwh = (h["soc_initial"] - h["soc_min"]) * h["battery_capacity_kwh"]
        energy_per_step_kwh = h["battery_max_rate_kw"] * dt_h
        max_steps = int(np.floor(usable_energy_kwh / energy_per_step_kwh))
        # Physical limit only: SOC determines max steps. No artificial protocol cap.
        max_steps_per_home[i] = max_steps
    
    total_available = int(np.sum(max_steps_per_home))
    
    if verbose:
        print(f"Oracle: {N} homes, {total_available} total discharge steps available")
        print(f"Oracle: per-home steps: min={int(np.min(max_steps_per_home))}, "
              f"max={int(np.max(max_steps_per_home))}, "
              f"mean={float(np.mean(max_steps_per_home)):.1f}")
    
    # Use the full battery window (204-259) as the dispatch window.
    # The protocol window (DISPATCH_WINDOW_END=252) is too short for late-battery
    # coverage. The oracle is not bound by protocol conventions.
    window_start = DISPATCH_WINDOW_START
    window_end = 260  # extend to end of battery window
    window_len = window_end - window_start
    
    k_min = np.zeros(window_len, dtype=int)
    k_max = np.zeros(window_len, dtype=int)
    
    for offset in range(window_len):
        t = window_start + offset
        k_min[offset] = minimum_homes_to_prevent_uv(homes, t)
        k_max[offset] = maximum_homes_without_ov(homes, t)
    
    if verbose:
        print(f"Oracle: K_min per slot: min={int(np.min(k_min))}, "
              f"max={int(np.max(k_min))}, mean={float(np.mean(k_min)):.1f}")
        print(f"Oracle: K_max per slot: min={int(np.min(k_max))}, "
              f"max={int(np.max(k_max))}, mean={float(np.mean(k_max)):.1f}")
    
    # Total minimum required to avoid undervoltage
    total_k_min = int(np.sum(k_min))
    total_k_max = int(np.sum(k_max))
    
    if verbose:
        print(f"Oracle: Total K_min = {total_k_min} (available = {total_available})")
        print(f"Oracle: Total K_max = {total_k_max}")
    
    if total_available < total_k_min:
        if verbose:
            print(f"Oracle: INFEASIBLE — need {total_k_min} discharge steps "
                  f"but only have {total_available}")
        feasible = False
    else:
        feasible = True
        if verbose:
            print(f"Oracle: FEASIBLE — {total_available} >= {total_k_min}")
    
    # Build the oracle schedule: for each available home-step, assign it to
    # the slot with the highest voltage pressure (distance below V_MIN_PU).
    # This is a priority-queue: the worst-off slot gets the best available home.
    schedule = np.zeros((N, N_STEPS), dtype=int)
    home_steps_remaining = max_steps_per_home.copy()
    total_remaining = int(np.sum(home_steps_remaining))
    
    # Precompute base net power (no battery) for each slot
    base_nets = np.zeros(window_len)
    for offset in range(window_len):
        t = window_start + offset
        pw = compute_base_net_power(homes, t)
        base_nets[offset] = float(np.sum(pw))
    
    # Current net power per slot (starts at base, grows as we add discharging homes)
    current_nets = base_nets.copy()
    
    # Track per-slot discharge count for K_max limit
    current_k = np.zeros(window_len, dtype=int)
    
    homes_sorted = sorted(range(N), key=lambda i: -homes[i]["position"])
    
    assigned = 0
    iteration = 0
    while total_remaining > 0 and iteration < total_available * 2:
        iteration += 1
        
        # Find the slot with the highest voltage pressure
        # pressure = max(0, V_MIN - V[59] with current net)
        # V[59] = V_SOURCE + Z * current_net
        best_offset = -1
        best_pressure = -1e6
        
        for offset in range(window_len):
            if current_k[offset] >= k_max[offset]:
                continue  # slot already at capacity
            v59 = V_SOURCE_PU + FEEDER_IMPEDANCE_PU * current_nets[offset]
            # Pressure: how far below V_MIN? Or how close? Negative if above V_MIN.
            pressure = V_MIN_PU - v59
            # Prefer slots below V_MIN (positive pressure), otherwise fill the
            # ones closest to V_MIN (least negative) to prevent future violations.
            if pressure > best_pressure:
                best_pressure = pressure
                best_offset = offset
        
        if best_offset < 0:
            break  # no slot needs more homes
        
        # Find the best home for this slot: far-feeder first
        best_home = -1
        for i in homes_sorted:
            if home_steps_remaining[i] > 0 and schedule[i, window_start + best_offset] == 0:
                best_home = i
                break
        
        if best_home < 0:
            # All homes already assigned to this slot or out of steps
            # Force-assign by breaking K_max if needed (but this shouldn't happen
            # with proper planning; mark slot as full to avoid infinite loops)
            if current_k[best_offset] >= k_max[best_offset]:
                k_max[best_offset] += 1  # relax constraint minimally
            continue
        
        # Assign
        t = window_start + best_offset
        schedule[best_home, t] = 1
        home_steps_remaining[best_home] -= 1
        total_remaining -= 1
        assigned += 1
        
        # Update net: this home adds BATTERY_MAX_RATE_KW to net at this slot
        # (discharging: goes from (pv-load) to (pv-load+5))
        current_nets[best_offset] += 5.0  # approximate: discharging adds +5kW export
        current_k[best_offset] += 1
    
    if verbose:
        print(f"Oracle: Assigned {assigned} home-steps ({total_available - assigned} left in homes)")
    
    # Check if we still have homes with leftover steps (shouldn't if we calculated right)
    leftover = int(np.sum(home_steps_remaining))
    if leftover > 0 and verbose:
        print(f"Oracle: {leftover} unused discharge steps remaining")
    
    # Now simulate to check results
    from sim.simulator import simulate
    result = simulate(homes, schedule)
    
    # Compute voltage_breach_events (simulate() doesn't do this)
    from sim.feeder import check_voltage_violations
    vs = result["voltage_series"]
    vv = result["voltage_violations"]
    PV_WIN_START = 120
    PV_WIN_END = 180
    BAT_WIN_START = 204
    BAT_WIN_END = 260
    voltage_breach_events = []
    for t in range(N_STEPS):
        homes_breaching = np.where(vv[:, t])[0]
        if len(homes_breaching) == 0:
            continue
        if PV_WIN_START <= t < PV_WIN_END:
            cause = "pv_export"
        elif BAT_WIN_START <= t < BAT_WIN_END:
            cause = "battery_herding"
        else:
            cause = "other"
        for node_id in homes_breaching:
            v_val = float(vs[node_id, t])
            band_exceeded = "upper" if v_val > V_MAX_PU else "lower"
            voltage_breach_events.append({
                "step": int(t), "node_id": int(node_id),
                "voltage_pu": round(v_val, 4),
                "band_limit_crossed": band_exceeded, "cause": cause,
            })
    
    v_bat = result["voltage_series"][:, BAT_WIN_START:BAT_WIN_END]
    overvolt_steps = int(np.sum(np.any(v_bat > V_MAX_PU, axis=0)))
    undervolt_steps = int(np.sum(np.any(v_bat < V_MIN_PU, axis=0)))
    
    herding_ov = len([e for e in voltage_breach_events
                      if e["band_limit_crossed"]=="upper" and e["cause"]=="battery_herding"])
    herding_uv = len([e for e in voltage_breach_events
                      if e["band_limit_crossed"]=="lower" and e["cause"]=="battery_herding"])
    
    dispatch = schedule
    max_sim = int(np.max(np.sum(dispatch == 1, axis=0))) if dispatch.size > 1 else 0
    sync = max_sim / N
    
    metrics = {
        "overvolt_bat_steps": overvolt_steps,
        "undervolt_bat_steps": undervolt_steps,
        "overvolt_events": herding_ov,
        "undervolt_events": herding_uv,
        "synchrony": round(sync, 3),
        "max_simultaneous": max_sim,
        "feasible": herding_ov == 0 and herding_uv == 0,
    }
    
    return schedule, metrics, home_steps_remaining


def run_oracle(load_source="synthetic", aemo_profile=None, verbose=True):
    """
    Run the oracle feasibility experiment end-to-end.
    """
    from sim.profiles import make_homes
    from sim.feeder import N_HOMES_DEFAULT
    
    homes = make_homes(
        N_HOMES_DEFAULT,
        heterogeneous=True,
        rng_seed=42,
        aemo_profile=aemo_profile,
    )
    
    if verbose:
        src = "synthetic" if load_source == "synthetic" else f"aemo ({aemo_profile.shape})"
        print(f"\n{'='*60}")
        print(f"ORACLE FEASIBILITY EXPERIMENT  [load_source={src}]")
        print(f"{'='*60}")
    
    schedule, metrics, remaining = oracle_best_dispatch(homes, verbose=verbose)
    
    if verbose:
        print(f"\n{'='*60}")
        print(f"ORACLE RESULTS")
        print(f"{'='*60}")
        print(f"  Overvolt steps (battery window):  {metrics['overvolt_bat_steps']}")
        print(f"  Undervolt steps (battery window): {metrics['undervolt_bat_steps']}")
        print(f"  Overvolt events:                  {metrics['overvolt_events']}")
        print(f"  Undervolt events:                 {metrics['undervolt_events']}")
        print(f"  Synchrony:                        {metrics['synchrony']}")
        print(f"  Max simultaneous:                 {metrics['max_simultaneous']}")
        print(f"  Full compliance feasible?          {'YES' if metrics['feasible'] else 'NO'}")
    
    return schedule, metrics


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    # Test both load sources
    run_oracle(load_source="synthetic")
    
    from sim.aemo import load_aemo_profile
    profile, meta = load_aemo_profile(verbose=False)
    run_oracle(load_source="aemo", aemo_profile=profile)
