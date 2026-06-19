"""
Dispatch strategies for GridAI.

STRATEGY A: Naive price-following (herding baseline)
  Every battery uses the SAME price threshold. When price crosses threshold,
  discharge. The homogeneous fleet fires all at once -> synchronised mass export
  -> overvoltage spike during discharge, then demand cliff after batteries stop.

STRATEGY B: Gossip-based decentralised coordination
  Each agent holds a planned dispatch slot. Agents exchange intents with K
  nearest neighbours. Conflict resolution: lower-priority agent shifts slot.
  Result: batteries discharge in a staggered pattern -> no overvoltage spike,
  demand cliff is smoothed.

STRATEGY C: Voltage-aware gossip (experimental, backward-compat)
  Extended window, SOC-based steps, interval-aware gossip.
  Contains tuned constants — see voltage_constrained_gossip_dispatch for
  the generalised version.

STRATEGY D: Voltage-constrained gossip with central repair (hybrid)
  Phases 1-5: Gossip/desynchronisation-style interval scheduling with
    kW-weighted position-aware constraints.
  Phase 6: Schedule construction from planned intervals.
  Phase 7: Central bounded validation/repair — not decentralised gossip.
    Validates the full schedule, then applies centralised repairs:
    suppress overvoltage-contributing steps, add homes to undervoltage
    steps, trim SOC-over-extended homes, revalidate.
  The final system is a hybrid: gossip initialisation plus central
  fail-closed validation/repair.  It is NOT purely decentralised gossip.

Heterogeneity:
  Homogeneous fleet: all agents have identical priority score ->
    tiebreaker (hash) forces some spread but weakly (~20-25 per slot peak)
  Heterogeneous fleet: clear priority ordering ->
    agents sort themselves neatly (~10-14 per slot peak, cleaner spread)
"""

import numpy as np
import hashlib

from sim.profiles import (
    N_STEPS,
    BATTERY_CAPACITY_KWH,
    BATTERY_MAX_RATE_KW,
    BATTERY_SOC_MIN,
    BATTERY_SOC_MAX,
    BATTERY_EFFICIENCY,
    PRICE_PEAK_START_STEP,
    PRICE_PEAK_END_STEP,
)
from sim.feeder import (
    V_SOURCE_PU,
    V_MAX_PU,
    V_MIN_PU,
    FEEDER_IMPEDANCE_PU,
)
from sim.voltage_constraints import (
    baseline_voltage_forecast,
    voltage_risk_windows,
    available_discharge_steps,
    home_voltage_sensitivity,
    slot_support_bounds,
    active_interval_counts,
    validate_schedule_invariants,
    overvoltage_kw_capacity_per_node,
    _extract_positions,
)

MAX_REPAIR_ITERATIONS = 20


# --- Metrics helpers ---

def max_simultaneous(schedule: np.ndarray) -> int:
    """Maximum number of homes discharging in any single step."""
    return int(np.max(np.sum(schedule == 1, axis=0))) if schedule.size > 0 else 0


def synchrony(schedule: np.ndarray, N: int) -> float:
    """Synchrony = max_simultaneous / N."""
    return max_simultaneous(schedule) / N if N > 0 else 0.0


def fragmented_homes(schedule: np.ndarray) -> int:
    """Number of homes whose active schedule has more than one contiguous run."""
    count = 0
    for row in schedule:
        active = np.where(row == 1)[0]
        if len(active) <= 1:
            continue
        gaps = np.diff(active)
        if np.any(gaps > 1):
            count += 1
    return count


def _count_active_runs(row: np.ndarray) -> int:
    """Number of contiguous 1-runs in a single home's schedule row."""
    active = np.where(row == 1)[0]
    if len(active) <= 1:
        return len(active)
    return int(np.sum(np.diff(active) > 1)) + 1


def _removal_splits_block(row: np.ndarray, step: int) -> bool:
    """True if removing step from an active home splits a contiguous block."""
    if row[step] != 1:
        return False
    left = step > 0 and row[step - 1] == 1
    right = step < len(row) - 1 and row[step + 1] == 1
    return left and right


def _addition_is_adjacent(row: np.ndarray, step: int) -> bool:
    """True if adding at step touches an existing active block."""
    if row[step] == 1:
        return True
    left = step > 0 and row[step - 1] == 1
    right = step < len(row) - 1 and row[step + 1] == 1
    return left or right


# Gossip protocol constants
GOSSIP_NEIGHBOURS = 6        # each agent talks to K nearest neighbours (±3 on feeder)
GOSSIP_MAX_ROUNDS = 100      # convergence safety limit

# Voltage-physics-derived slot capacity limit (used by standard gossip).
# With Z=0.001, N=60, battery 5kW, base 2.0kW, PV 0.2kW at 18:30:
#   V[59] = 1.02 + 0.001 * (K*3.2 - (60-K)*2.0)
#         = 1.02 + 0.001 * (5.2K - 120)
# For V < 1.10: K < 38.5
# For V > 0.94: K > 7.7
# Ideal range: 8 <= K <= 38. We target K=20 as the gossip slot capacity.
# This gives V[59] = 1.02 + 0.001*(5.2*20 - 120) = 1.02 + 0.001*(-16) = 1.004 ✓ comfortable
MAX_CONCURRENT_DISCHARGE = 20   # target slot capacity -> comfortable voltage range

# Evening peak window: agents target discharge within this range
DISPATCH_WINDOW_START = PRICE_PEAK_START_STEP   # step 204 = 17:00
DISPATCH_WINDOW_END = PRICE_PEAK_END_STEP + 12   # step 252 = 21:00
DISPATCH_WINDOW_LEN = DISPATCH_WINDOW_END - DISPATCH_WINDOW_START  # 48 slots


def naive_dispatch(homes: list, price: np.ndarray) -> np.ndarray:
    """
    Strategy A: Naive price-following.

    Each home discharges whenever price >= its willingness_threshold.
    In a homogeneous fleet all thresholds are equal -> synchronous discharge.
    Returns schedule: shape (N, N_STEPS), values 0 or 1.
    """
    N = len(homes)
    schedule = np.zeros((N, N_STEPS), dtype=int)
    dt_h = 5.0 / 60.0

    for i, home in enumerate(homes):
        soc = home["soc_initial"]
        threshold = home["willingness_threshold"]
        cap = home["battery_capacity_kwh"]
        rate = home["battery_max_rate_kw"]

        for t in range(N_STEPS):
            if price[t] >= threshold and soc > home["soc_min"] + 0.01:
                discharge_kwh = min(rate * dt_h, (soc - home["soc_min"]) * cap)
                if discharge_kwh > 0.01:
                    schedule[i, t] = 1
                    soc -= discharge_kwh / cap

    return schedule


def _priority_score(home: dict) -> float:
    """
    Priority score: higher = more urgent = gets earlier/preferred slot.
    score = soc_initial * (1 - willingness_threshold)
    """
    return home["soc_initial"] * (1.0 - home["willingness_threshold"])


def _device_hash(agent_id: int) -> int:
    """Deterministic tiebreaker based on device id. Returns 0-9999."""
    return int(hashlib.md5(f"gridai_agent_{agent_id:04d}".encode()).hexdigest(), 16) % 10000


def gossip_dispatch(homes: list, price: np.ndarray,
                    feeder_impedance: float = FEEDER_IMPEDANCE_PU,
                    priority_intervals: list | None = None) -> tuple:
    """
    Strategy B: Gossip-based decentralised coordination.

    Phase 1: Initial slot assignment. Each agent maps its priority score
      to a slot in the dispatch window. High priority = early slot.

    Phase 2: Gossip rounds. Each agent checks:
      a) Is my slot overcrowded (> MAX_CONCURRENT_DISCHARGE)?
      b) If yes: am I in the lowest-priority group at this slot?
      c) If yes: shift to the least-crowded available slot.
    Stop when no agent changed, or GOSSIP_MAX_ROUNDS reached.

    Phase 3: Build schedule. Each agent discharges for up to 3 steps from its slot.

    Returns (schedule, rounds_to_converge, gossip_log).
    """
    N = len(homes)
    dt_h = 5.0 / 60.0

    avoid_slots = {int(s) for s in (priority_intervals or [])}

    # Phase 1: initial slot assignment
    priority_scores = np.array([_priority_score(h) for h in homes])
    device_hashes = np.array([_device_hash(h["id"]) for h in homes])

    p_min = float(np.min(priority_scores))
    p_max = float(np.max(priority_scores))
    if p_max > p_min:
        p_norm = (priority_scores - p_min) / (p_max - p_min)
    else:
        p_norm = np.full(N, 0.5)

    planned_slots = np.zeros(N, dtype=int)
    for i in range(N):
        slot_offset = int((1.0 - p_norm[i]) * (DISPATCH_WINDOW_LEN - 1))
        slot_offset = max(0, min(DISPATCH_WINDOW_LEN - 1, slot_offset))
        planned_slots[i] = DISPATCH_WINDOW_START + slot_offset

    # Phase 2: gossip rounds
    gossip_log = []
    rounds_to_converge = GOSSIP_MAX_ROUNDS

    for round_num in range(GOSSIP_MAX_ROUNDS):
        any_changed = False

        slot_counts = {}
        for s in planned_slots:
            slot_counts[int(s)] = slot_counts.get(int(s), 0) + 1

        rng = np.random.RandomState(round_num * 7919 + 42)
        agent_order = rng.permutation(N)

        for i in agent_order:
            my_slot = int(planned_slots[i])
            my_count = slot_counts.get(my_slot, 0)

            if my_count <= MAX_CONCURRENT_DISCHARGE:
                continue

            slot_agents = [j for j in range(N) if int(planned_slots[j]) == my_slot]
            slot_agents.sort(
                key=lambda j: (priority_scores[j], device_hashes[j]),
                reverse=True
            )
            my_rank = slot_agents.index(i)

            if my_rank < MAX_CONCURRENT_DISCHARGE:
                continue

            old_slot = my_slot
            new_slot = _find_least_crowded_slot(
                my_slot, slot_counts, DISPATCH_WINDOW_START, DISPATCH_WINDOW_END,
                avoid_slots=avoid_slots,
            )

            if new_slot != old_slot:
                slot_counts[old_slot] -= 1
                slot_counts[new_slot] = slot_counts.get(new_slot, 0) + 1
                planned_slots[i] = new_slot
                any_changed = True
                gossip_log.append((round_num, i, old_slot, new_slot))

        if not any_changed:
            rounds_to_converge = round_num + 1
            break

    # Phase 3: build schedule
    schedule = np.zeros((N, N_STEPS), dtype=int)
    for i, home in enumerate(homes):
        soc = home["soc_initial"]
        cap = home["battery_capacity_kwh"]
        slot = int(planned_slots[i])

        for step_offset in range(3):
            t = slot + step_offset
            if t >= N_STEPS:
                break
            if soc <= home["soc_min"] + 0.01:
                break
            discharge_kwh = min(BATTERY_MAX_RATE_KW * dt_h, (soc - home["soc_min"]) * cap)
            if discharge_kwh > 0.01:
                schedule[i, t] = 1
                soc -= discharge_kwh / cap

    return schedule, rounds_to_converge, gossip_log


def _find_least_crowded_slot(current_slot: int, slot_counts: dict,
                              window_start: int, window_end: int,
                              avoid_slots: set | None = None) -> int:
    """
    Find the slot in [window_start, window_end) with lowest occupancy.
    Excludes current_slot. Prefers slots below MAX_CONCURRENT_DISCHARGE.
    Among equal-count slots, prefers ones the Forecaster did NOT flag as
    high-herding-risk (avoid_slots), then the closest to current_slot.

    avoid_slots defaults to empty -> behaviour identical to before.
    """
    avoid = avoid_slots or set()
    best_slot = current_slot
    best_count = slot_counts.get(current_slot, 0)
    best_avoid = 1 if current_slot in avoid else 0

    for s in range(window_start, window_end):
        if s == current_slot:
            continue
        count = slot_counts.get(s, 0)
        s_avoid = 1 if s in avoid else 0
        cand = (count, s_avoid, abs(s - current_slot))
        best = (best_count, best_avoid, abs(best_slot - current_slot))
        if cand < best:
            best_count, best_avoid, best_slot = count, s_avoid, s

    return best_slot


# ---------------------------------------------------------------------------
# STRATEGY C: Voltage-aware gossip (backward-compatible variant)
# ---------------------------------------------------------------------------
# Uses extended window, SOC-based steps, power-law skew, edge-fill.
# Contains tuned constants (0.35, 13, 38, 7) — kept for reproducibility.
# New development should use voltage_constrained_gossip_dispatch instead.

VA_WINDOW_START = DISPATCH_WINDOW_START     # step 204 = 17:00
VA_WINDOW_END = 260                         # step 260 = 21:40
VA_WINDOW_LEN = VA_WINDOW_END - VA_WINDOW_START  # 56 slots

MAX_DISCHARGE_STEPS_PER_HOME = 13


def voltage_aware_gossip_dispatch(homes: list, price: np.ndarray,
                                   feeder_impedance: float = FEEDER_IMPEDANCE_PU,
                                   priority_intervals: list | None = None) -> tuple:
    """
    Strategy C: Voltage-aware gossip protocol (backward-compatible).

    Same interface as voltage_constrained_gossip_dispatch but uses tuned
    constants (SLOT_SKEW_EXP=0.35, MAX_DISCHARGE_STEPS=13, etc.) and
    a hardcoded risk window.

    Kept for reproducibility of earlier benchmark results.
    Use voltage_constrained_gossip_dispatch for generalised behaviour.
    """
    N = len(homes)
    dt_h = 5.0 / 60.0

    avoid_slots = {int(s) for s in (priority_intervals or [])}

    max_steps_per_home = np.zeros(N, dtype=int)
    for i, h in enumerate(homes):
        usable_kwh = (h["soc_initial"] - h["soc_min"]) * h["battery_capacity_kwh"]
        energy_per_step_kwh = h["battery_max_rate_kw"] * dt_h
        steps = int(np.floor(usable_kwh / energy_per_step_kwh))
        max_steps_per_home[i] = min(steps, MAX_DISCHARGE_STEPS_PER_HOME)

    SLOT_SKEW_EXP = 0.35

    priority_scores = np.array([_priority_score(h) for h in homes])
    device_hashes = np.array([_device_hash(h["id"]) for h in homes])

    p_min = float(np.min(priority_scores))
    p_max = float(np.max(priority_scores))
    if p_max > p_min:
        p_norm = (priority_scores - p_min) / (p_max - p_min)
    else:
        p_norm = np.full(N, 0.5)

    planned_slots = np.zeros(N, dtype=int)
    for i in range(N):
        slot_offset = int((1.0 - p_norm[i] ** SLOT_SKEW_EXP) * (VA_WINDOW_LEN - 1))
        slot_offset = max(0, min(VA_WINDOW_LEN - 1, slot_offset))
        planned_slots[i] = VA_WINDOW_START + slot_offset

    base_forecast = baseline_voltage_forecast(homes)
    _, k_max_phys = slot_support_bounds(homes, base_forecast)

    gossip_log = []
    rounds_to_converge = GOSSIP_MAX_ROUNDS
    DISCHARGE_STEPS = max_steps_per_home.copy()

    def _interval_peak(slots, intervals, step):
        count = 0
        for j in range(N):
            start = int(slots[j])
            end = start + int(intervals[j])
            if start <= step < end:
                count += 1
        return count

    for round_num in range(GOSSIP_MAX_ROUNDS):
        any_changed = False
        rng = np.random.RandomState(round_num * 7919 + 42)
        agent_order = rng.permutation(N)

        for i in agent_order:
            my_start = int(planned_slots[i])
            my_len = int(DISCHARGE_STEPS[i])
            my_peak = max(
                _interval_peak(planned_slots, DISCHARGE_STEPS, t)
                for t in range(my_start, min(my_start + my_len, VA_WINDOW_END + 5))
            )
            if my_peak <= MAX_CONCURRENT_DISCHARGE:
                continue

            best_slot = my_start
            best_peak = my_peak
            best_avoid = 1 if my_start in avoid_slots else 0

            for candidate in range(VA_WINDOW_START, VA_WINDOW_END):
                if candidate == my_start:
                    continue
                planned_slots[i] = candidate
                cand_peak = max(
                    _interval_peak(planned_slots, DISCHARGE_STEPS, t)
                    for t in range(candidate, min(candidate + my_len, VA_WINDOW_END + 5))
                )
                cand_avoid = 1 if candidate in avoid_slots else 0
                cand = (cand_peak, cand_avoid, abs(candidate - my_start))
                best = (best_peak, best_avoid, abs(best_slot - my_start))
                if cand < best:
                    best_peak, best_avoid, best_slot = cand_peak, cand_avoid, candidate
                planned_slots[i] = my_start

            if best_slot != my_start:
                planned_slots[i] = best_slot
                any_changed = True
                gossip_log.append((round_num, i, my_start, best_slot))

        if not any_changed:
            rounds_to_converge = round_num + 1
            break

    EARLY_RISK_START = VA_WINDOW_START
    EARLY_RISK_END = EARLY_RISK_START + 7
    EDGE_POSITION_THRESHOLD = 38

    far_feeder = [i for i in range(N) if homes[i].get("position", i) >= EDGE_POSITION_THRESHOLD]

    slot_counts = {}
    for s in planned_slots:
        slot_counts[int(s)] = slot_counts.get(int(s), 0) + 1

    for i in far_feeder:
        cur_slot = int(planned_slots[i])

        if cur_slot >= EARLY_RISK_START and cur_slot < EARLY_RISK_END:
            continue

        best_slot = cur_slot
        best_count = slot_counts.get(cur_slot, 0)
        best_early_count = 999

        for t in range(EARLY_RISK_START, EARLY_RISK_END):
            count = slot_counts.get(t, 0)
            if count < best_count and count < MAX_CONCURRENT_DISCHARGE:
                if count < best_early_count:
                    best_early_count = count
                    best_slot = t

        if best_slot != cur_slot:
            slot_counts[cur_slot] = max(0, slot_counts.get(cur_slot, 0) - 1)
            slot_counts[best_slot] = slot_counts.get(best_slot, 0) + 1
            planned_slots[i] = best_slot
            if max_steps_per_home[i] > 4:
                max_steps_per_home[i] = 4
            gossip_log.append(("edge_fill", i, cur_slot, best_slot))

    schedule = np.zeros((N, N_STEPS), dtype=int)
    for i, home in enumerate(homes):
        soc = home["soc_initial"]
        cap = home["battery_capacity_kwh"]
        slot = int(planned_slots[i])
        n_steps = int(max_steps_per_home[i])

        for step_offset in range(n_steps):
            t = slot + step_offset
            if t >= N_STEPS:
                break
            if soc <= home["soc_min"] + 0.01:
                break
            discharge_kwh = min(BATTERY_MAX_RATE_KW * dt_h, (soc - home["soc_min"]) * cap)
            if discharge_kwh > 0.01:
                schedule[i, t] = 1
                soc -= discharge_kwh / cap

    return schedule, rounds_to_converge, gossip_log


# ---------------------------------------------------------------------------
# STRATEGY D: Voltage-constrained gossip (generalised)
# ---------------------------------------------------------------------------
# Replaces tuned constants with physics-derived values:
#   - Risk windows detected from baseline voltage forecast (not hardcoded)
#   - Per-home steps from SOC (no cap unless caller provides safety_cap)
#   - Risk-weighted slot allocation (no SLOT_SKEW_EXP)
#   - Per-slot K_max[t] bounds (no global MAX_CONCURRENT_DISCHARGE only)
#   - Sensitivity-aware fill with active-interval validation
#
# This strategy is designed to generalise across feeder sizes, impedances,
# battery sizes, and load profiles.

def _risk_weighted_slot_allocation(p_norm, risk_cdf, window_start, window_len):
    """Map normalised priority [0,1] to slots using a risk-weighted CDF.

    High-priority homes (p_norm near 1) map to early slots where risk
    is concentrated. If risk is uniform (risk_cdf is linear), this is
    identical to standard linear assignment.
    """
    N = len(p_norm)
    planned_slots = np.zeros(N, dtype=int)
    for i in range(N):
        # Invert: target = 1 - p_norm -> find corresponding CDF position
        target = 1.0 - float(p_norm[i])
        slot_offset = int(np.searchsorted(risk_cdf, target))
        slot_offset = max(0, min(window_len - 1, slot_offset))
        planned_slots[i] = window_start + slot_offset
    return planned_slots


def voltage_constrained_gossip_dispatch(homes: list, price: np.ndarray,
                                         feeder_impedance: float = FEEDER_IMPEDANCE_PU,
                                         priority_intervals: list | None = None,
                                         steps_safety_cap: int | None = None) -> tuple:
    """
    Strategy D: Voltage-constrained gossip with central repair (hybrid).

    Phases 1-6 use gossip/desynchronisation-style interval scheduling with
    kW-weighted position-aware constraints.  Phase 7 is a central bounded
    validation/repair pass — NOT decentralised gossip.

    HONESTY NOTE: The final system is a hybrid.  Phases 1-6 are
    decentralised gossip heuristics; Phase 7 is a central repair loop
    that validates the full schedule and applies bounded centralised
    fixes (suppress OV-contributing steps, add UV fill, trim SOC-over-
    extended homes).  Product description should say
    "gossip initialisation plus central fail-closed validation/repair."

    Phase 1: Voltage risk detection.
      Computes 288-step baseline voltage forecast (no battery).
      Dynamic detection of undervoltage-risk windows from baseline V[N-1].
      Fallback to PRICE_PEAK window if no voltage risk detected.

    Phase 2: Per-home available steps.
      Derived from SOC, capacity, rate. Optional caller safety_cap
      for battery-health limits (not benchmark tuning).

    Phase 3: Risk-weighted slot allocation.
      Each slot's risk weight = max(0, V_MIN - V_base[t])^p where p=0.5.
      Normalised to CDF. High-priority homes fill high-risk slots first.

    Phase 4: Interval-aware gossip with kW-position constraints.
      Each agent checks its planned interval against cumulative kW
      per node (not just count-based K_max).  Homes move only when
      their kW contribution would not exceed per-node capacity.

    Phase 5: Sensitivity-aware UV fill.
      High-sensitivity homes moved into under-filled UV-risk steps,
      checked against kW-position capacity.

    Phase 6: Schedule building.
      Each home discharges consecutively from its start slot for its
      SOC-determined duration.

    Phase 7: Central bounded validation/repair.
      Not decentralised gossip.  Validates the full schedule; if not
      clean, applies up to MAX_REPAIR_ITERATIONS centralised repair
      passes: suppress OV-contributing steps by highest rate first,
      add kW-feasible homes to UV steps, trim SOC-over-extended homes.
      Revalidates after each pass.  Reports residual failure honestly.

    Returns (schedule, rounds_to_converge, gossip_log).
    """
    N = len(homes)
    dt_h = 5.0 / 60.0
    avoid_slots = {int(s) for s in (priority_intervals or [])}

    # Validate positions early — fail clearly before any work
    positions = _extract_positions(homes)

    # --- Phase 1: Voltage risk detection ---
    # Use undervoltage-only window — discharging during overvoltage makes it worse.
    forecast = baseline_voltage_forecast(homes)
    risks = voltage_risk_windows(forecast)
    risk_start, risk_end = risks["undervolt_window"]
    # If no undervoltage risk detected, fall back to price-peak window
    if risk_end <= risk_start:
        risk_start = PRICE_PEAK_START_STEP
        risk_end = max(risk_start + 1, PRICE_PEAK_END_STEP + 12)
    window_len = risk_end - risk_start

    # --- Phase 2: Per-home available steps from SOC ---
    max_steps_per_home = np.array([
        available_discharge_steps(h, dt_h, safety_cap=steps_safety_cap)
        for h in homes
    ], dtype=int)

    # --- Phase 3: Risk-weighted slot allocation ---
    priority_scores = np.array([_priority_score(h) for h in homes])
    device_hashes = np.array([_device_hash(h["id"]) for h in homes])

    p_min = float(np.min(priority_scores))
    p_max = float(np.max(priority_scores))
    if p_max > p_min:
        p_norm = (priority_scores - p_min) / (p_max - p_min)
    else:
        p_norm = np.full(N, 0.5)

    # Compute risk weights from baseline V at critical node
    critical = N - 1
    v_base = forecast[critical, :]  # (N_STEPS,)
    risk_weights = np.array([
        max(0.0, V_MIN_PU - v_base[t]) ** 0.5  # sqrt of undervoltage pressure
        for t in range(risk_start, risk_end)
    ], dtype=float)

    total_risk = float(np.sum(risk_weights))
    if total_risk > 1e-10:
        # Risk-weighted CDF
        risk_cdf = np.cumsum(risk_weights) / total_risk
    else:
        # Uniform fallback
        risk_cdf = np.linspace(0, 1, window_len)

    planned_slots = _risk_weighted_slot_allocation(p_norm, risk_cdf, risk_start, window_len)

    # --- Phase 4: Interval-aware gossip with kW-position constraints ---
    window_len = risk_end - risk_start
    home_rates = np.array([h.get("battery_max_rate_kw", BATTERY_MAX_RATE_KW) for h in homes], dtype=float)
    cap_kw_per_node = overvoltage_kw_capacity_per_node(homes, forecast)
    cap_kw_slice = cap_kw_per_node[:, risk_start:risk_end]

    gossip_log = []
    rounds_to_converge = GOSSIP_MAX_ROUNDS
    discharge_steps = max_steps_per_home.copy()

    # Build active kW by position from planned intervals
    active_kw = np.zeros((N, window_len), dtype=float)
    for i in range(N):
        pos = positions[i]
        rate = home_rates[i]
        s = int(planned_slots[i])
        d = int(discharge_steps[i])
        i_start = max(s - risk_start, 0)
        i_end = min(s + d - risk_start, window_len)
        if i_start < i_end:
            active_kw[pos, i_start:i_end] += rate
    cum_kw = np.cumsum(active_kw, axis=0, dtype=float)

    def _kw_feasible(pos, slot, duration):
        for t in range(slot, min(slot + duration, risk_end)):
            idx = t - risk_start
            if np.any(cum_kw[pos:, idx] > cap_kw_slice[pos:, idx] + 1e-4):
                return False
        return True

    def _remove_kw(pos, rate, slot, duration):
        ls = max(slot - risk_start, 0)
        le = min(slot + duration - risk_start, window_len)
        if ls < le:
            active_kw[pos, ls:le] -= rate
            cum_kw[pos:, ls:le] -= rate

    def _add_kw(pos, rate, slot, duration):
        ls = max(slot - risk_start, 0)
        le = min(slot + duration - risk_start, window_len)
        if ls < le:
            active_kw[pos, ls:le] += rate
            cum_kw[pos:, ls:le] += rate

    for round_num in range(GOSSIP_MAX_ROUNDS):
        any_changed = False
        rng = np.random.RandomState(round_num * 7919 + 42)
        agent_order = rng.permutation(N)

        for i in agent_order:
            my_start = int(planned_slots[i])
            my_len = int(discharge_steps[i])
            my_pos = positions[i]
            my_rate = home_rates[i]

            if _kw_feasible(my_pos, my_start, my_len):
                continue

            _remove_kw(my_pos, my_rate, my_start, my_len)

            best_slot = my_start
            best_feasible = False
            best_avoid = 1 if my_start in avoid_slots else 0

            for candidate in range(risk_start, risk_end):
                if candidate == my_start:
                    continue

                _add_kw(my_pos, my_rate, candidate, my_len)
                cand_feasible = _kw_feasible(my_pos, candidate, my_len)
                _remove_kw(my_pos, my_rate, candidate, my_len)

                cand_avoid = 1 if candidate in avoid_slots else 0
                cand = (0 if cand_feasible else 1, cand_avoid, abs(candidate - my_start))
                best = (0 if best_feasible else 1, best_avoid, abs(best_slot - my_start))
                if cand < best:
                    best_feasible = cand_feasible
                    best_avoid = cand_avoid
                    best_slot = candidate

            if best_slot != my_start:
                _add_kw(my_pos, my_rate, best_slot, my_len)
                planned_slots[i] = best_slot
                any_changed = True
                gossip_log.append((round_num, i, my_start, best_slot))
            else:
                _add_kw(my_pos, my_rate, my_start, my_len)

        if not any_changed:
            rounds_to_converge = round_num + 1
            break

    # --- Phase 5: Sensitivity-aware UV fill (kW-position constrained) ---
    uv_risk = risks["undervolt_window"]
    if uv_risk[1] > uv_risk[0]:
        uv_start, uv_end = uv_risk
        sensitivity = home_voltage_sensitivity(homes)
        # Active kw per step in UV risk window
        active_kw_uv = np.zeros(uv_end - uv_start, dtype=float)
        for i in range(N):
            pos = positions[i]
            rate = home_rates[i]
            s = int(planned_slots[i])
            d = int(discharge_steps[i])
            for t in range(max(s, uv_start), min(s + d, uv_end)):
                active_kw_uv[t - uv_start] += rate
        # Steps with least active kW -> most UV risk
        uv_fill_order = sorted(
            range(uv_start, uv_end), key=lambda t: active_kw_uv[t - uv_start]
        )
        for t in uv_fill_order:
            idx_t = t - uv_start
            threshold = float(cap_kw_per_node[N - 1, t]) * 0.5
            if active_kw_uv[idx_t] >= threshold:
                continue
            # Find candidates: homes not active at this step
            cand = [
                i for i in range(N)
                if not (int(planned_slots[i]) <= t < int(planned_slots[i]) + int(discharge_steps[i]))
            ]
            cand.sort(key=lambda i: -sensitivity[i])
            for i in cand:
                pos = positions[i]
                rate = home_rates[i]
                cur_s = int(planned_slots[i])
                cur_d = int(discharge_steps[i])
                _remove_kw(pos, rate, cur_s, cur_d)
                _add_kw(pos, rate, t, cur_d)
                if _kw_feasible(pos, t, cur_d):
                    planned_slots[i] = t
                    gossip_log.append(("sens_fill", i, cur_s, t))
                    active_kw_uv[idx_t] += rate
                    break
                else:
                    _remove_kw(pos, rate, t, cur_d)
                    _add_kw(pos, rate, cur_s, cur_d)

    # --- Phase 6: Build schedule ---
    schedule = np.zeros((N, N_STEPS), dtype=int)
    for i, home in enumerate(homes):
        soc = home["soc_initial"]
        cap = home["battery_capacity_kwh"]
        slot = int(planned_slots[i])
        n_steps = int(discharge_steps[i])
        rate = home_rates[i]

        for step_offset in range(n_steps):
            t = slot + step_offset
            if t >= N_STEPS:
                break
            if soc <= home["soc_min"] + 0.01:
                break
            discharge_kwh = min(rate * dt_h, (soc - home["soc_min"]) * cap)
            if discharge_kwh > 0.01:
                schedule[i, t] = 1
                soc -= discharge_kwh / cap

    # --- Phase 7: Bounded central repair loop ---
    # NOTE: This is NOT decentralised gossip.  It validates the full
    # schedule and applies centralised bounded repairs.
    repair_log = []
    total_kv = 0
    total_uv = 0
    total_soc = 0
    total_frag_preserving = 0
    total_frag_increasing = 0
    total_maxsim_preserving = 0
    total_maxsim_increasing = 0

    for iteration in range(MAX_REPAIR_ITERATIONS + 1):
        inv = validate_schedule_invariants(
            schedule, homes, dispatch_window=(risk_start, risk_end),
        )
        if iteration == 0:
            initial_val = {
                "soc_ok": bool(inv["soc_ok"]),
                "voltage_feasible": bool(inv["voltage_feasible"]),
                "kw_position_ok": bool(inv["kw_position_ok"]),
                "invariants_ok": bool(inv["invariants_ok"]),
                "overvolt_steps": int(inv["overvolt_steps"]),
                "undervolt_steps": int(inv["undervolt_steps"]),
                "overvolt_step_indices": [int(t) for t, _ in inv.get("overvolt_step_indices", [])],
                "undervolt_step_indices": [int(t) for t, _ in inv.get("undervolt_step_indices", [])],
                "kw_position_violations": len(inv.get("kw_position_violations", [])),
                "max_simultaneous": max_simultaneous(schedule),
                "synchrony": synchrony(schedule, N),
                "fragmented_homes": fragmented_homes(schedule),
            }

        if inv["invariants_ok"]:
            repair_log.append({"iteration": iteration, "outcome": "clean"})
            break

        if iteration == MAX_REPAIR_ITERATIONS:
            repair_log.append({"iteration": iteration, "outcome": "max_reached"})
            break

        moves_attempted = 0
        moves_accepted = 0
        kv_count = 0
        uv_count = 0
        soc_count = 0
        frag_preserving_count = 0
        frag_increasing_count = 0
        maxsim_preserving_count = 0
        maxsim_increasing_count = 0

        # Precompute cumulative kW matrix for current schedule
        active_kw_pos = np.zeros((N, N_STEPS), dtype=float)
        for j in range(N):
            active_kw_pos[positions[j], :] += schedule[j, :] * home_rates[j]
        cum_kw_by_node = np.cumsum(active_kw_pos, axis=0, dtype=float)

        # A. Fix kW-position overvoltage violations
        if not inv["kw_position_ok"]:
            kw_violations = inv.get("kw_position_violations", [])
            step_violations = {}
            for t, i_node, ckw, ccap in kw_violations:
                step_violations.setdefault(t, []).append((i_node, ckw, ccap))

            for step, violations in sorted(step_violations.items()):
                worst_node = max(violations, key=lambda v: v[1] - v[2])[0]
                offenders = [
                    (j, home_rates[j], positions[j])
                    for j in range(N)
                    if schedule[j, step] == 1 and positions[j] <= worst_node
                ]
                offenders.sort(key=lambda x: (-x[1], -x[2]))
                for j, rate, pos in offenders:
                    moves_attempted += 1
                    schedule[j, step] = 0
                    moves_accepted += 1
                    kv_count += 1

            # Recompute cum_kw_by_node after suppression for stale-state safety
            active_kw_pos = np.zeros((N, N_STEPS), dtype=float)
            for j in range(N):
                active_kw_pos[positions[j], :] += schedule[j, :] * home_rates[j]
            cum_kw_by_node = np.cumsum(active_kw_pos, axis=0, dtype=float)

        # B. Fix undervoltage — reallocation with post-removal voltage safety
        #
        # Phase 6 exhausts every home's SOC, so we REALLOCATE: move a
        # discharge step from a non-UV donor into the UV step, preserving
        # the per-home energy budget.
        #
        # Donor eligibility uses a PHYSICS GATE: after removing the home's
        # kW, every affected node must stay above V_MIN in the prefix-sum
        # model.  The cheaper filters (not in initial UV set, others >= 1)
        # are kept as early exits but are NOT treated as sufficient.
        #
        # Among eligible candidates, ranking favours moves that preserve
        # schedule contiguity, keep target-step active count low, and
        # avoid increasing global max_simultaneous.
        if inv["undervolt_steps"] > 0:
            uv_indices = inv.get("undervolt_step_indices", [])
            uv_step_set = sorted({t for t, _ in uv_indices})
            initial_uv_set = {t for t, _ in uv_indices}
            dw_set = set(range(risk_start, risk_end))

            def _donor_removal_safe(d_step, d_pos, d_rate):
                """Post-removal voltage check: no affected node falls below V_MIN."""
                v_after = (
                    forecast[d_pos:, d_step]
                    + feeder_impedance * (cum_kw_by_node[d_pos:, d_step] - d_rate)
                )
                return bool(np.all(v_after >= V_MIN_PU + 1e-4))

            def _step_voltage_safe(chk_step):
                """Check if a step is voltage-safe across all nodes."""
                v_now = (
                    forecast[:, chk_step]
                    + feeder_impedance * cum_kw_by_node[:, chk_step]
                )
                return bool(np.all(v_now >= V_MIN_PU + 1e-4))

            current_global_max = max_simultaneous(schedule)

            for step in uv_step_set:
                used_j = set()
                for _ in range(N):
                    if _step_voltage_safe(step):
                        break

                    candidates = []
                    for j, home in enumerate(homes):
                        if schedule[j, step] == 1 or j in used_j:
                            continue
                        pos = int(positions[j])
                        rate = float(home_rates[j])

                        # --- Cheap early filters ---
                        active_at = np.where(schedule[j, :] == 1)[0]
                        possible_donors = []
                        for t in active_at:
                            if t in initial_uv_set:
                                continue
                            if t not in dw_set:
                                continue
                            possible_donors.append(t)
                        if not possible_donors:
                            continue

                        # Post-removal voltage safety
                        voltage_safe_donors = []
                        for t in possible_donors:
                            if _donor_removal_safe(t, pos, rate):
                                voltage_safe_donors.append(t)
                        if not voltage_safe_donors:
                            continue

                        # Pick best voltage-safe donor: highest other-home count
                        best_donor = max(
                            voltage_safe_donors,
                            key=lambda t: int(np.sum(schedule[:, t])) - 1,
                        )

                        # kW-position constraint at the UV step
                        if np.any(cum_kw_by_node[pos:, step] + rate
                                   > cap_kw_per_node[pos:, step] + 1e-4):
                            continue

                        # --- Shape scoring ---
                        row = schedule[j, :]
                        adj = _addition_is_adjacent(row, step)
                        splits = _removal_splits_block(row, best_donor)
                        old_runs = _count_active_runs(row)
                        sim_row = row.copy()
                        sim_row[best_donor] = 0
                        sim_row[step] = 1
                        new_runs = _count_active_runs(sim_row)
                        frag_delta = new_runs - old_runs

                        current_count = int(np.sum(schedule[:, step]))
                        maxsim_ok = (current_count + 1 <= current_global_max)

                        candidates.append((
                            frag_delta,
                            0 if adj else 1,
                            0 if not splits else 1,
                            current_count,
                            0 if maxsim_ok else 1,
                            -rate * (N - pos),
                            j, rate, pos, best_donor,
                        ))

                    if not candidates:
                        break

                    candidates.sort()
                    j = candidates[0][6]
                    rate_v = candidates[0][7]
                    pos_v = candidates[0][8]
                    donor_step = candidates[0][9]
                    frag_delta_v = candidates[0][0]
                    maxsim_ok_v = (candidates[0][4] == 0)

                    moves_attempted += 1
                    schedule[j, donor_step] = 0
                    schedule[j, step] = 1
                    moves_accepted += 1
                    uv_count += 1
                    used_j.add(j)

                    cum_kw_by_node[pos_v:, donor_step] -= rate_v
                    cum_kw_by_node[pos_v:, step] += rate_v

                    if frag_delta_v <= 0:
                        frag_preserving_count += 1
                    else:
                        frag_increasing_count += 1
                    if maxsim_ok_v:
                        maxsim_preserving_count += 1
                    else:
                        maxsim_increasing_count += 1

                    current_global_max = max(max_simultaneous(schedule), current_count + 1)

        # C. Fix SOC violations
        if not inv["soc_ok"]:
            for j, home in enumerate(homes):
                active_steps = np.where(schedule[j, :] == 1)[0]
                if len(active_steps) == 0:
                    continue
                used_kwh = len(active_steps) * home_rates[j] * dt_h
                usable_kwh = (home["soc_initial"] - home["soc_min"]) * home["battery_capacity_kwh"]
                if used_kwh > usable_kwh + 0.01:
                    excess_kwh = used_kwh - usable_kwh
                    steps_to_remove = int(np.ceil(
                        excess_kwh / (home_rates[j] * dt_h)
                    ))
                    for k in range(min(steps_to_remove, len(active_steps))):
                        moves_attempted += 1
                        schedule[j, active_steps[-1 - k]] = 0
                        moves_accepted += 1
                        soc_count += 1

        total_kv += kv_count
        total_uv += uv_count
        total_soc += soc_count
        total_frag_preserving += frag_preserving_count
        total_frag_increasing += frag_increasing_count
        total_maxsim_preserving += maxsim_preserving_count
        total_maxsim_increasing += maxsim_increasing_count

        repair_log.append({
            "iteration": iteration,
            "moves_attempted": moves_attempted,
            "moves_accepted": moves_accepted,
            "kv_suppressions": kv_count,
            "uv_reallocations": uv_count,
            "uv_additions": uv_count,
            "soc_removals": soc_count,
            "frag_preserving": frag_preserving_count,
            "frag_increasing": frag_increasing_count,
            "maxsim_preserving": maxsim_preserving_count,
            "maxsim_increasing": maxsim_increasing_count,
        })

        if moves_accepted == 0:
            break

    # --- Final validation + structured log ---
    final_inv = validate_schedule_invariants(
        schedule, homes, dispatch_window=(risk_start, risk_end),
    )

    final_val = {
        "soc_ok": bool(final_inv["soc_ok"]),
        "voltage_feasible": bool(final_inv["voltage_feasible"]),
        "kw_position_ok": bool(final_inv["kw_position_ok"]),
        "invariants_ok": bool(final_inv["invariants_ok"]),
        "overvolt_steps": int(final_inv["overvolt_steps"]),
        "undervolt_steps": int(final_inv["undervolt_steps"]),
        "overvolt_events": int(final_inv["overvolt_events"]),
        "undervolt_events": int(final_inv["undervolt_events"]),
        "k_max_violations": len(final_inv["k_max_violations"]),
        "k_min_shortfalls": len(final_inv["k_min_shortfall"]),
        "kw_position_violations": len(final_inv.get("kw_position_violations", [])),
        "overvolt_step_indices": [int(t) for t, _ in final_inv.get("overvolt_step_indices", [])],
        "undervolt_step_indices": [int(t) for t, _ in final_inv.get("undervolt_step_indices", [])],
        "dispatch_window": (int(risk_start), int(risk_end)),
        "max_simultaneous": max_simultaneous(schedule),
        "synchrony": synchrony(schedule, N),
        "fragmented_homes": fragmented_homes(schedule),
    }
    clean_feasible = bool(final_val["invariants_ok"])
    operational_clean = bool(clean_feasible and final_val["fragmented_homes"] == 0)

    gossip_log.append(("validation", {
        "initial": initial_val,
        "final": final_val,
        "clean_feasible": clean_feasible,
        "operational_clean": operational_clean,
        "repair": {
            "central_repair_used": len(repair_log) > 0,
            "iterations": len(repair_log),
            "total_moves_attempted": sum(
                r.get("moves_attempted", 0) for r in repair_log
            ),
            "total_moves_accepted": sum(
                r.get("moves_accepted", 0) for r in repair_log
            ),
            "kv_suppressions": total_kv,
            "uv_reallocations": total_uv,
            "uv_additions": total_uv,
            "soc_removals": total_soc,
            "fragmentation_preserving_reallocations": total_frag_preserving,
            "fragmentation_increasing_reallocations": total_frag_increasing,
            "maxsim_preserving_reallocations": total_maxsim_preserving,
            "maxsim_increasing_reallocations": total_maxsim_increasing,
        },
    }))

    if not clean_feasible:
        reasons = [
            name for name, ok in
            [("SOC", final_val["soc_ok"]),
             ("VOLTAGE", final_val["voltage_feasible"]),
             ("KW_POSITION", final_val["kw_position_ok"])]
            if not ok
        ]
        fail_entry = {
            "reason": "+".join(reasons),
            "overvolt_steps": final_val["overvolt_steps"],
            "undervolt_steps": final_val["undervolt_steps"],
            "undervolt_step_indices": final_val["undervolt_step_indices"],
            "kw_position_violations": final_val["kw_position_violations"],
            "fragmented_homes": final_val["fragmented_homes"],
            "max_simultaneous": final_val["max_simultaneous"],
        }
        gossip_log.append(("residual_failure", fail_entry))

    return schedule, rounds_to_converge, gossip_log
