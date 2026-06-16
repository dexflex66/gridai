"""
Two dispatch strategies.

STRATEGY A: Naive price-following (herding baseline)
  Every battery uses the SAME price threshold. When price crosses threshold,
  discharge. The homogeneous fleet fires all at once -> synchronised mass export
  -> overvoltage spike during discharge, then demand cliff after batteries stop.

STRATEGY B: Gossip-based decentralised coordination
  Each agent holds a planned dispatch slot. Agents exchange intents with K
  nearest neighbours. Conflict resolution: lower-priority agent shifts slot.
  Result: batteries discharge in a staggered pattern -> no overvoltage spike,
  demand cliff is smoothed.

Heterogeneity:
  Homogeneous fleet: all agents have identical priority score ->
    tiebreaker (hash) forces some spread but weakly (~20-25 per slot peak)
  Heterogeneous fleet: clear priority ordering ->
    agents sort themselves neatly (~10-14 per slot peak, cleaner spread)

Three-way contrast (naive-hom / gossip-hom / gossip-het) shows:
  naive-hom: all 60 fire together, synchrony=1.0, mass overvoltage
  gossip-hom: weakly spread, synchrony~0.35, overvoltage reduced
  gossip-het: strongly spread, synchrony~0.20, overvoltage eliminated
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

# Gossip protocol constants
GOSSIP_NEIGHBOURS = 6        # each agent talks to K nearest neighbours (±3 on feeder)
GOSSIP_MAX_ROUNDS = 100      # convergence safety limit

# Voltage-physics-derived slot capacity limit.
# With Z=0.001, N=60, battery 5kW, base 2.0kW, PV 0.2kW at 18:30:
#   Discharging home net: 5 + 0.2 - 2.0 = 3.2 kW export
#   Importing home net: 0 + 0.0 - 2.0 = -2.0 kW (later evening, no PV)
# Voltage at home 59 (prefix sum of all 60):
#   V[59] = 1.02 + 0.001 * (K * 3.2 + (60-K) * (-2.0))
#         = 1.02 + 0.001 * (3.2K - 120 + 2.0K)  ... wait, subtract -2.0 from 60-K
#         = 1.02 + 0.001 * (K*3.2 - (60-K)*2.0)
#         = 1.02 + 0.001 * (3.2K - 120 + 2.0K)
#         = 1.02 + 0.001 * (5.2K - 120)
# For V < 1.10: 5.2K - 120 < 80 -> K < 38.5
# For V > 0.94: 5.2K - 120 > -80 -> K > 7.7
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
    Range:
      Heterogeneous fleet (SOC 0.45-0.92, threshold 0.20-0.85):
        min ~ 0.45 * (1-0.85) = 0.067
        max ~ 0.92 * (1-0.20) = 0.736
        wide spread -> clear priority ordering -> strong desynchronisation
      Homogeneous fleet (SOC 0.70, threshold 0.50):
        all homes = 0.70 * 0.50 = 0.350 -> equal priority -> tiebreaker only
        only weak desynchronisation from hash-based tiebreaker
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
      Heterogeneous fleet: wide score spread -> agents distributed across window.
      Homogeneous fleet: all same score -> all start at same slot (max conflict).

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

    # Forecaster hint: intervals (steps) it flagged as highest battery-herding
    # risk. The gossip protocol prefers NOT to re-pile evicted agents onto these
    # slots. Optional; when absent, behaviour is unchanged.
    avoid_slots = {int(s) for s in (priority_intervals or [])}

    # Phase 1: initial slot assignment
    priority_scores = np.array([_priority_score(h) for h in homes])
    device_hashes = np.array([_device_hash(h["id"]) for h in homes])

    # Map priority to slot. Higher priority -> earlier slot (lower offset).
    # We normalise priority to [0,1] across the range [min_score, max_score].
    # Then invert: slot_offset = (1 - normalised_priority) * (WINDOW_LEN - 1)
    p_min = float(np.min(priority_scores))
    p_max = float(np.max(priority_scores))
    if p_max > p_min:
        p_norm = (priority_scores - p_min) / (p_max - p_min)
    else:
        # Homogeneous: all same score -> all map to same offset (centre of window)
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

        # Count occupancy per slot
        slot_counts = {}
        for s in planned_slots:
            slot_counts[int(s)] = slot_counts.get(int(s), 0) + 1

        # Process agents in random order each round
        rng = np.random.RandomState(round_num * 7919 + 42)
        agent_order = rng.permutation(N)

        for i in agent_order:
            my_slot = int(planned_slots[i])
            my_count = slot_counts.get(my_slot, 0)

            if my_count <= MAX_CONCURRENT_DISCHARGE:
                continue  # Slot within capacity, no action needed

            # Slot overcrowded. Determine my rank within this slot.
            # Rank by (priority descending, hash descending) - highest rank stays.
            slot_agents = [j for j in range(N) if int(planned_slots[j]) == my_slot]
            # Sort: highest priority first, hash as tiebreak
            slot_agents.sort(
                key=lambda j: (priority_scores[j], device_hashes[j]),
                reverse=True
            )
            my_rank = slot_agents.index(i)  # 0 = highest priority in slot

            if my_rank < MAX_CONCURRENT_DISCHARGE:
                continue  # I'm in the top group, I stay

            # I should yield. Find a better slot.
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

        # Discharge for up to 3 consecutive steps from planned slot
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

    avoid_slots defaults to empty -> behaviour identical to before, so the
    headline numbers for an un-hinted gossip run are unchanged.
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
        # Rank candidates by (occupancy asc, in-avoid-set asc, distance asc).
        cand = (count, s_avoid, abs(s - current_slot))
        best = (best_count, best_avoid, abs(best_slot - current_slot))
        if cand < best:
            best_count, best_avoid, best_slot = count, s_avoid, s

    return best_slot


# ---------------------------------------------------------------------------
# STRATEGY C: Voltage-aware gossip (experimental variant)
# ---------------------------------------------------------------------------
# Extends the standard gossip protocol with:
#   - Full battery-window coverage (204-260, 56 slots)
#   - Per-home SOC-based variable discharge duration (instead of fixed 3 steps)
#   - No central optimisation; each home independently knows its SOC and position
#
# The key insight from the oracle feasibility experiment:
#   Full voltage compliance requires ~13.9 homes discharging per slot on average.
#   With 60 homes discharging at SOC-based variable duration (mean ~11 steps),
#   the effective per-slot coverage is ~60 * 11 / 56 = ~11.8 homes/slot, which
#   is well above the K_min required to prevent undervoltage.

# Voltage-aware dispatch window: full battery window
VA_WINDOW_START = DISPATCH_WINDOW_START     # step 204 = 17:00
VA_WINDOW_END = 260                         # step 260 = 21:40 (end of battery check window)
VA_WINDOW_LEN = VA_WINDOW_END - VA_WINDOW_START  # 56 slots

# Cap on per-home discharge steps (prevents battery exhaustion).
# With M=10, 60 homes × 10 = 600 total steps across 56 slots ≈ 10.7/slot.
# This provides enough coverage while keeping the diagonal-band overlap
# peak well below MAX_CONCURRENT_DISCHARGE (20).
MAX_DISCHARGE_STEPS_PER_HOME = 13


def voltage_aware_gossip_dispatch(homes: list, price: np.ndarray,
                                   feeder_impedance: float = FEEDER_IMPEDANCE_PU,
                                   priority_intervals: list | None = None) -> tuple:
    """
    Strategy C: Voltage-aware gossip protocol.

    Phase 1: Initial slot assignment (same as standard gossip, but with
      extended 56-slot window instead of 48).

    Phase 2: Gossip rounds (identical to standard gossip — per-slot capacity
      limit prevents overvoltage).

    Phase 3: Each agent discharges for a SOC-determined number of consecutive
      steps (not fixed 3). This provides enough total coverage to prevent
      undervoltage while the per-slot cap prevents overvoltage.

    Returns (schedule, rounds_to_converge, gossip_log).
    """
    N = len(homes)
    dt_h = 5.0 / 60.0

    avoid_slots = {int(s) for s in (priority_intervals or [])}

    # Per-home max discharge steps based on SOC
    max_steps_per_home = np.zeros(N, dtype=int)
    for i, h in enumerate(homes):
        usable_kwh = (h["soc_initial"] - h["soc_min"]) * h["battery_capacity_kwh"]
        energy_per_step_kwh = h["battery_max_rate_kw"] * dt_h
        steps = int(np.floor(usable_kwh / energy_per_step_kwh))
        max_steps_per_home[i] = min(steps, MAX_DISCHARGE_STEPS_PER_HOME)

    # Phase 1: initial slot assignment with voltage-aware skew.
    # Use a power-law mapping to concentrate more homes in early slots
    # (where base load is highest and undervoltage risk is greatest).
    # exponent < 1 skews toward early slots; 0.3 gives a good balance.
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
        # Power-law skew: p_norm^SLOT_SKEW_EXP compresses high-priority
        # homes into earlier slots without clustering them all at 204.
        slot_offset = int((1.0 - p_norm[i] ** SLOT_SKEW_EXP) * (VA_WINDOW_LEN - 1))
        slot_offset = max(0, min(VA_WINDOW_LEN - 1, slot_offset))
        planned_slots[i] = VA_WINDOW_START + slot_offset

    # Phase 2: gossip rounds with interval-aware capacity.
    # With extended discharge (M=13), standard per-slot gossip allows the
    # diagonal-band overlap to exceed 20. The interval check ensures no
    # slot exceeds capacity.
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

    # Phase 2b: Edge-coverage fill.
    # Far-feeder homes (position >= 38) whose start slot is after the
    # undervoltage-risk zone (step 210) may move to an earlier slot to
    # provide voltage support. This is a one-shot decentralised move:
    # each far-feeder home checks if an early slot (204-210) has
    # spare capacity and if so, moves there. The gossip constraint
    # (no slot exceeds MAX_CONCURRENT_DISCHARGE) is maintained.
    EARLY_RISK_START = VA_WINDOW_START        # 204
    EARLY_RISK_END = EARLY_RISK_START + 7     # 210 (first 7 slots of battery window)
    EDGE_POSITION_THRESHOLD = 38

    # Homes far from transformer are position >= 38
    far_feeder = [i for i in range(N) if homes[i].get("position", i) >= EDGE_POSITION_THRESHOLD]

    # Count starts per slot
    slot_counts = {}
    for s in planned_slots:
        slot_counts[int(s)] = slot_counts.get(int(s), 0) + 1

    for i in far_feeder:
        cur_slot = int(planned_slots[i])

        # Only consider moving if currently outside the risk zone
        if cur_slot >= EARLY_RISK_START and cur_slot < EARLY_RISK_END:
            continue  # already in the risk zone, no move needed

        # Find the early slot with the most spare capacity
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
            # This far-feeder home moves to an early slot for a SHORT burst
            # (4 steps). This provides early voltage support without extending
            # the discharge interval into the mid-window where it would
            # contribute to the overlap peak.
            slot_counts[cur_slot] = max(0, slot_counts.get(cur_slot, 0) - 1)
            slot_counts[best_slot] = slot_counts.get(best_slot, 0) + 1
            planned_slots[i] = best_slot
            # Shorten this home's discharge to avoid mid-window overlap
            if max_steps_per_home[i] > 4:
                max_steps_per_home[i] = 4
            gossip_log.append(("edge_fill", i, cur_slot, best_slot))

    # Phase 3: build schedule with SOC-based variable discharge duration.
    # Each home discharges consecutively from its start slot for up to
    # max_steps_per_home steps. The interval-aware gossip ensures no slot
    # exceeds capacity.
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
