"""
Oracle feasibility experiment.

Answers: Is full voltage compliance (zero overvolt AND zero undervolt) physically
achievable given the current battery constraints on the given demand/PV traces?

The oracle has perfect foresight: it knows every home's SOC, base load, PV
generation, and the feeder voltage model. It constructs a contiguous-interval
greedy constructive feasibility heuristic that minimises undervoltage while
keeping overvoltage = 0.

This is NOT a deployable protocol — it is a constructive greedy feasibility
heuristic compatible with contiguous-interval dispatch strategies. It does NOT
solve a global optimisation (no back-tracking), so it may miss feasible
configurations that a full optimiser would find.

This module depends on sim.voltage_constraints for all physics functions,
and does NOT import any constants from sim.strategies.
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
from sim.voltage_constraints import (
    _extract_positions,
    compute_base_net_power,
    baseline_voltage_forecast,
    voltage_risk_windows,
    available_discharge_steps,
    home_voltage_sensitivity,
    slot_support_bounds,
    overvoltage_kw_capacity_per_node,
    validate_schedule_invariants,
)


def compute_k_min_k_max(homes, risk_window):
    """Compute per-slot K_min and K_max within the risk window.

    Delegates to slot_support_bounds (voltage_constraints.py) which
    computes bounds from ALL nodes (not just V[N-1]).
    """
    forecast = baseline_voltage_forecast(homes)
    k_min_all, k_max_all = slot_support_bounds(homes, forecast)
    rs, re = risk_window
    return k_min_all[rs:re], k_max_all[rs:re]


def _can_place_contiguous_interval(active_kw_by_position, cap_kw_slice,
                                   home_pos, home_rate_kw,
                                   start, duration, risk_start, N):
    """True if adding home at home_pos respects per-node kW capacity.

    Checks: for each node i >= home_pos,
      cumulative_kw_up_to[i] + home_rate_kw <= cap_kw_slice[i]
    """
    for t in range(start, start + duration):
        idx = t - risk_start
        cum_kw = 0.0
        for i in range(N):
            cum_kw += float(active_kw_by_position[i, idx])
            if i >= home_pos and cum_kw + home_rate_kw > float(cap_kw_slice[i, idx]):
                return False
    return True


def _contiguous_interval_score(active_kw_sum, start, duration, k_min_slice,
                               base_nets, risk_start):
    """Higher = more useful placement (K_min shortfall + voltage pressure).

    active_kw_sum : (window_len,) — total discharge kW across all positions.
    """
    score = 0.0
    for t in range(start, start + duration):
        idx = t - risk_start
        count_estimate = int(np.round(active_kw_sum[idx] / BATTERY_MAX_RATE_KW))
        shortfall = max(0, int(k_min_slice[idx]) - count_estimate)
        net = float(base_nets[idx]) + float(active_kw_sum[idx])
        v = V_SOURCE_PU + FEEDER_IMPEDANCE_PU * net
        pressure = max(0.0, V_MIN_PU - v)
        score += shortfall * 10.0 + pressure
    return score


def _schedule_is_contiguous(schedule):
    """True when every home's discharge steps form one contiguous block."""
    for i in range(schedule.shape[0]):
        row = schedule[i, :]
        ones = np.where(row == 1)[0]
        if len(ones) <= 1:
            continue
        if int(ones[-1]) - int(ones[0]) + 1 != len(ones):
            return False
    return True


def oracle_best_dispatch(homes, verbose=True):
    """
    Contiguous-interval greedy constructive feasibility heuristic.

    Uses perfect foresight but does NOT solve a global optimisation problem.
    Each home receives at most one contiguous discharge block inside the
    undervoltage risk window — compatible with deployable strategies that
    use contiguous intervals.

    The algorithm:
      1. Compute per-home available discharge duration from SOC.
      2. Compute per-slot K_min / K_max from voltage physics.
      3. Greedily assign each home a contiguous block: prefer high-sensitivity
         homes and slots with the largest K_min shortfall / voltage pressure,
         respecting K_max across the full interval.
      4. Validate with validate_schedule_invariants and report honestly.

    Returns:
      schedule: (N, N_STEPS) int, 1=discharge
      metrics: dict with feasibility / violation summaries
      remaining: np.ndarray of unused per-home steps
    """
    N = len(homes)
    dt_h = 5.0 / 60.0

    # Per-home available steps from SOC (pure physics, no cap)
    max_steps_per_home = np.array([
        available_discharge_steps(h, dt_h, safety_cap=None)
        for h in homes
    ], dtype=int)

    total_available = int(np.sum(max_steps_per_home))

    if verbose:
        print(f"Oracle: contiguous greedy constructive feasibility heuristic")
        print(f"Oracle: {N} homes, {total_available} total discharge steps available")
        print(f"Oracle: per-home steps: min={int(np.min(max_steps_per_home))}, "
              f"max={int(np.max(max_steps_per_home))}, "
              f"mean={float(np.mean(max_steps_per_home)):.1f}")

    # Detect risk windows from baseline voltage forecast.
    # Use undervoltage-only window — battery discharge during overvoltage
    # makes it worse (more export).
    forecast = baseline_voltage_forecast(homes)
    risks = voltage_risk_windows(forecast)
    risk_start, risk_end = risks["undervolt_window"]

    if risk_start >= risk_end:
        if verbose:
            print("Oracle: No undervoltage risk detected — no dispatch needed.")
        return np.zeros((N, N_STEPS), dtype=int), {
            "fragmented": False,
            "homes_assigned": 0,
            "unused_steps": int(np.sum(max_steps_per_home)),
            "overvolt_bat_steps": 0, "undervolt_bat_steps": 0,
            "overvolt_events": 0, "undervolt_events": 0,
            "synchrony": 0.0, "max_simultaneous": 0,
            "feasible": True,
            "voltage_feasible": True,
            "invariants_ok": True,
            "clean_feasible": True,
            "k_max_violations": 0,
            "k_max_position_violations": 0,
            "kw_position_violations": 0,
            "k_min_shortfalls": 0,
        }, max_steps_per_home

    window_len = risk_end - risk_start
    k_min, k_max = compute_k_min_k_max(homes, (risk_start, risk_end))
    cap_kw_per_node = overvoltage_kw_capacity_per_node(homes, forecast)
    cap_kw_slice = cap_kw_per_node[:, risk_start:risk_end]  # (N, window_len)

    if verbose:
        print(f"Oracle: Risk window = [{risk_start}, {risk_end}) ({window_len} slots)")
        print(f"Oracle: K_min per slot: min={int(np.min(k_min))}, "
              f"max={int(np.max(k_min))}, mean={float(np.mean(k_min)):.1f}")
        print(f"Oracle: K_max per slot: min={int(np.min(k_max))}, "
              f"max={int(np.max(k_max))}, mean={float(np.mean(k_max)):.1f}")

    total_k_min = int(np.sum(k_min))
    total_k_max = int(np.sum(k_max))

    if verbose:
        print(f"Oracle: Total K_min = {total_k_min} (available = {total_available})")
        print(f"Oracle: Total K_max = {total_k_max}")

    feasible = total_available >= total_k_min
    if verbose:
        print(f"Oracle: Capacity check (necessary, not sufficient): "
              f"{'FEASIBLE' if feasible else 'INFEASIBLE'} "
              f"({total_available} >= {total_k_min})")

    # Contiguous-interval greedy assignment with kW-based position-aware capacity
    schedule = np.zeros((N, N_STEPS), dtype=int)
    positions = _extract_positions(homes)
    home_rates = np.array([h["battery_max_rate_kw"] for h in homes], dtype=float)
    active_kw_by_position = np.zeros((N, window_len), dtype=float)
    home_steps_remaining = max_steps_per_home.copy()
    sensitivity = home_voltage_sensitivity(homes)

    base_nets = np.zeros(window_len)
    for offset in range(window_len):
        t = risk_start + offset
        pw = compute_base_net_power(homes, t)
        base_nets[offset] = float(np.sum(pw))

    homes_sorted = sorted(
        range(N),
        key=lambda i: (-float(sensitivity[i]), -int(max_steps_per_home[i]), -int(positions[i])),
    )

    homes_assigned = 0
    assigned_steps = 0

    for i in homes_sorted:
        home_pos = int(positions[i])
        home_rate = float(home_rates[i])
        duration = int(max_steps_per_home[i])
        if duration <= 0:
            continue

        best_start = None
        best_score = -1.0
        latest_start = risk_end - duration
        if latest_start < risk_start:
            continue

        for start in range(risk_start, latest_start + 1):
            if not _can_place_contiguous_interval(
                active_kw_by_position, cap_kw_slice, home_pos, home_rate,
                start, duration, risk_start, N
            ):
                continue
            # For score computation, use total discharge kW (sum across positions)
            active_kw_sum = np.sum(active_kw_by_position, axis=0)
            score = _contiguous_interval_score(
                active_kw_sum, start, duration, k_min, base_nets, risk_start
            )
            if score > best_score:
                best_score = score
                best_start = start

        if best_start is None:
            continue

        for offset in range(duration):
            t = best_start + offset
            schedule[i, t] = 1
            active_kw_by_position[home_pos, t - risk_start] += home_rate

        home_steps_remaining[i] = 0
        homes_assigned += 1
        assigned_steps += duration

    unused_steps = int(np.sum(home_steps_remaining))
    fragmented = not _schedule_is_contiguous(schedule)

    if verbose:
        print(f"Oracle: Assigned {homes_assigned} homes "
              f"({assigned_steps} steps, {unused_steps} unused)")
        if fragmented:
            print("Oracle: WARNING — schedule is fragmented (unexpected)")

    # Validate invariants (scoped to dispatch window)
    inv = validate_schedule_invariants(
        schedule, homes,
        dispatch_window=(risk_start, risk_end),
    )

    if verbose:
        if not inv["voltage_feasible"]:
            print(f"Oracle: WARNING — dispatch-window voltage violations "
                  f"(OV steps={inv['overvolt_steps']}, UV steps={inv['undervolt_steps']})")
        if inv["k_max_violations"]:
            print(f"Oracle: NOTE — {len(inv['k_max_violations'])} K_max bounds exceeded")
            for t, act, kmax in inv["k_max_violations"][:5]:
                print(f"  Step {t}: active={act}, K_max={kmax}")
        if inv.get("kw_position_violations"):
            pv = inv["kw_position_violations"]
            print(f"Oracle: NOTE — {len(pv)} kW-position violations")
            for t, i, cum_kw, cap_kw in pv[:5]:
                print(f"  Step {t}: node {i}: cum_kw={cum_kw:.1f}, cap_kw={cap_kw:.1f}")
        if inv["k_min_shortfall"]:
            print(f"Oracle: NOTE — {len(inv['k_min_shortfall'])} K_min shortfalls")
            for t, act, kmin in inv["k_min_shortfall"][:5]:
                print(f"  Step {t}: active={act}, K_min={kmin}")
        clean = inv["soc_ok"] and inv["voltage_feasible"] and inv["invariants_ok"]
        print(f"Oracle: clean feasible? {'YES' if clean else 'NO'}")

    dispatch = schedule
    max_sim = int(np.max(np.sum(dispatch == 1, axis=0))) if dispatch.size > 1 else 0
    sync = max_sim / N if N > 0 else 0.0
    clean_feasible = bool(
        inv["soc_ok"] and inv["voltage_feasible"] and inv["invariants_ok"]
    )

    metrics = {
        "fragmented": fragmented,
        "homes_assigned": homes_assigned,
        "unused_steps": unused_steps,
        "overvolt_bat_steps": inv["overvolt_steps"],
        "undervolt_bat_steps": inv["undervolt_steps"],
        "overvolt_events": inv["overvolt_events"],
        "undervolt_events": inv["undervolt_events"],
        "synchrony": round(sync, 3),
        "max_simultaneous": max_sim,
        "feasible": feasible,
        "voltage_feasible": inv["voltage_feasible"],
        "invariants_ok": inv["invariants_ok"],
        "clean_feasible": clean_feasible,
        "k_max_violations": len(inv["k_max_violations"]),
        "k_max_position_violations": len(inv.get("k_max_position_violations", [])),
        "kw_position_violations": len(inv.get("kw_position_violations", [])),
        "k_min_shortfalls": len(inv["k_min_shortfall"]),
    }

    return schedule, metrics, home_steps_remaining


def run_oracle(load_source="synthetic", aemo_profile=None, verbose=True):
    """Run the oracle feasibility experiment end-to-end."""
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
        print(f"ORACLE RESULTS (contiguous greedy constructive heuristic)")
        print(f"{'='*60}")
        print(f"  Fragmented schedule?               {'YES' if metrics['fragmented'] else 'NO'}")
        print(f"  Homes assigned:                    {metrics['homes_assigned']}")
        print(f"  Unused discharge steps:            {metrics['unused_steps']}")
        print(f"  Overvolt steps (dispatch window): {metrics['overvolt_bat_steps']}")
        print(f"  Undervolt steps (dispatch window): {metrics['undervolt_bat_steps']}")
        print(f"  Overvolt events:                  {metrics['overvolt_events']}")
        print(f"  Undervolt events:                 {metrics['undervolt_events']}")
        print(f"  Synchrony:                        {metrics['synchrony']}")
        print(f"  Max simultaneous:                 {metrics['max_simultaneous']}")
        print(f"  Voltage feasible (no violations)?  {'YES' if metrics['voltage_feasible'] else 'NO'}")
        print(f"  Invariants ok (K_min+K_max)?       {'YES' if metrics['invariants_ok'] else 'NO (' + str(metrics['k_max_violations']) + ' K_max, ' + str(metrics['k_min_shortfalls']) + ' K_min)'}")
        print(f"  Clean feasible (all checks)?       {'YES' if metrics['clean_feasible'] else 'NO'}")

    return schedule, metrics


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    run_oracle(load_source="synthetic")

    from sim.aemo import load_aemo_profile
    profile, meta = load_aemo_profile(verbose=False)
    run_oracle(load_source="aemo", aemo_profile=profile)
