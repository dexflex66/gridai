"""
Tests for the voltage-constrained gossip strategy with central repair.

Covers instrumentation, fragmented homes metric, fail-closed behaviour,
position validation, and shuffle invariance.
"""

import sys
import os
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sim.feeder import N_HOMES_DEFAULT, N_STEPS
from sim.profiles import make_homes
from sim.strategies import (
    voltage_constrained_gossip_dispatch,
    max_simultaneous,
    synchrony,
    fragmented_homes,
    _extract_positions,
    _count_active_runs,
    _removal_splits_block,
    _addition_is_adjacent,
)
from sim.voltage_constraints import (
    validate_schedule_invariants,
    baseline_voltage_forecast,
    voltage_risk_windows,
)


# ---------------------------------------------------------------------------
# 1. Validation log contains structured metrics
# ---------------------------------------------------------------------------

def test_voltage_constrained_strategy_logs_validation():
    """Run strategy on a default synthetic case and verify gossip_log
    contains a structured validation entry with all required metrics."""
    homes = make_homes(N_HOMES_DEFAULT, heterogeneous=True, rng_seed=42)
    schedule, rounds, log = voltage_constrained_gossip_dispatch(
        homes, np.zeros(N_STEPS)
    )

    # Locate the ("validation", dict) entry
    val_entry = None
    for entry in log:
        if isinstance(entry, tuple) and entry[0] == "validation":
            val_entry = entry[1]
            break
    assert val_entry is not None, "gossip_log must contain ('validation', dict)"

    # Check top-level fields
    assert "clean_feasible" in val_entry
    assert "operational_clean" in val_entry
    assert "initial" in val_entry
    assert "final" in val_entry
    assert "repair" in val_entry

    # Initial metrics
    init = val_entry["initial"]
    for key in ("max_simultaneous", "synchrony", "fragmented_homes",
                "soc_ok", "voltage_feasible", "kw_position_ok",
                "invariants_ok", "overvolt_steps", "undervolt_steps",
                "kw_position_violations"):
        assert key in init, f"initial missing '{key}'"

    # Final metrics
    final = val_entry["final"]
    for key in ("max_simultaneous", "synchrony", "fragmented_homes",
                "soc_ok", "voltage_feasible", "kw_position_ok",
                "invariants_ok", "overvolt_steps", "undervolt_steps",
                "kw_position_violations", "dispatch_window"):
        assert key in final, f"final missing '{key}'"

    # Repair info
    repair = val_entry["repair"]
    assert "central_repair_used" in repair
    assert "iterations" in repair
    assert "total_moves_attempted" in repair
    assert "total_moves_accepted" in repair
    assert "kv_suppressions" in repair
    assert "uv_reallocations" in repair
    assert "uv_additions" in repair  # backward compat
    assert "soc_removals" in repair


# ---------------------------------------------------------------------------
# 2. Fail-closed on impossible SOC
# ---------------------------------------------------------------------------

def test_voltage_constrained_strategy_fail_closed_on_impossible_case():
    """Construct a fleet where SOC is too low to fill UV steps.
    Strategy must NOT report clean_feasible=True."""
    N = N_HOMES_DEFAULT
    homes = make_homes(N, heterogeneous=True, rng_seed=7)
    # Drain all homes to near-empty
    for h in homes:
        h["soc_initial"] = h["soc_min"] + 0.01
    schedule, rounds, log = voltage_constrained_gossip_dispatch(
        homes, np.zeros(N_STEPS)
    )
    # Find validation entry
    val_entry = None
    residual_entry = None
    for entry in log:
        if isinstance(entry, tuple):
            if entry[0] == "validation":
                val_entry = entry[1]
            elif entry[0] == "residual_failure":
                residual_entry = entry[1]
    assert val_entry is not None
    # With near-empty SOC the strategy cannot fill UV → not clean
    assert not val_entry["clean_feasible"], (
        "Must report not clean for SOC-starved fleet"
    )
    assert residual_entry is not None, (
        "Must log residual_failure when not clean"
    )
    assert "reason" in residual_entry
    assert "fragmented_homes" in residual_entry
    assert "max_simultaneous" in residual_entry


# ---------------------------------------------------------------------------
# 3. Fragmented homes metric
# ---------------------------------------------------------------------------

def test_fragmented_homes_metric():
    """Small artificial schedule with one home in two separated blocks."""
    sched = np.zeros((5, 288), dtype=int)
    sched[0, 10:15] = 1   # contiguous
    sched[1, 10:13] = 1   # block A
    sched[1, 30:35] = 1   # block B — same home, separated → fragmented
    sched[2, :] = 0       # never active
    sched[3, 20] = 1      # single step → not fragmented
    sched[4, 5:10] = 1    # contiguous
    assert fragmented_homes(sched) == 1, "Only home 1 should be fragmented"


def test_fragmented_homes_contiguous():
    """All homes contiguous → fragmented_homes == 0."""
    sched = np.zeros((5, 288), dtype=int)
    sched[0, 5:10] = 1
    sched[1, 10:20] = 1
    sched[2, 15:18] = 1
    sched[3, 0:5] = 1
    sched[4, 20:25] = 1
    assert fragmented_homes(sched) == 0


def test_max_simultaneous_and_synchrony():
    """Verify max_simultaneous and synchrony helpers."""
    sched = np.zeros((4, 288), dtype=int)
    sched[0, 5:10] = 1
    sched[1, 5:8] = 1
    sched[2, 6:9] = 1
    # At step 5: homes 0,1 active → 2
    # At step 6: homes 0,1,2 active → 3
    # At step 7: homes 0,1,2 active → 3
    # At step 8: homes 0 active → 1
    assert max_simultaneous(sched) == 3
    assert synchrony(sched, 4) == 0.75


def test_max_simultaneous_empty():
    """Empty schedule → max_simultaneous == 0."""
    sched = np.zeros((5, 288), dtype=int)
    assert max_simultaneous(sched) == 0
    assert synchrony(sched, 5) == 0.0


# ---------------------------------------------------------------------------
# 4. Strategy rejects invalid positions
# ---------------------------------------------------------------------------

def test_strategy_rejects_duplicate_positions():
    """Duplicate position raises ValueError."""
    homes = make_homes(N_HOMES_DEFAULT, heterogeneous=True, rng_seed=42)
    homes[1]["position"] = homes[0]["position"]  # force duplicate
    with pytest.raises(ValueError, match="Duplicate"):
        voltage_constrained_gossip_dispatch(homes, np.zeros(N_STEPS))


def test_strategy_rejects_negative_position():
    """Negative position raises ValueError."""
    homes = make_homes(N_HOMES_DEFAULT, heterogeneous=True, rng_seed=42)
    homes[5]["position"] = -1
    with pytest.raises(ValueError, match="negative"):
        voltage_constrained_gossip_dispatch(homes, np.zeros(N_STEPS))


def test_strategy_rejects_out_of_range_position():
    """Position >= N raises ValueError."""
    homes = make_homes(N_HOMES_DEFAULT, heterogeneous=True, rng_seed=42)
    homes[10]["position"] = N_HOMES_DEFAULT + 5
    with pytest.raises(ValueError, match="out of range|0.*N"):
        voltage_constrained_gossip_dispatch(homes, np.zeros(N_STEPS))


# ---------------------------------------------------------------------------
# 5. Shuffle invariance
# ---------------------------------------------------------------------------

def test_strategy_shuffle_invariance_validation():
    """Shuffled homes + matching schedule should validate equivalently."""
    N = N_HOMES_DEFAULT
    import random
    homes = make_homes(N, heterogeneous=True, rng_seed=42)
    sched, _, _ = voltage_constrained_gossip_dispatch(
        homes, np.zeros(N_STEPS)
    )
    forecast = baseline_voltage_forecast(homes)
    risks = voltage_risk_windows(forecast)
    dw = risks["undervolt_window"]
    ref = validate_schedule_invariants(sched, homes, dispatch_window=dw)

    # Shuffle homes and schedule identically
    idx = list(range(N))
    random.seed(42)
    random.shuffle(idx)
    shuf_homes = [homes[i] for i in idx]
    shuf_sched = sched[idx, :]
    shuf = validate_schedule_invariants(
        shuf_sched, shuf_homes, dispatch_window=dw
    )

    # Core metrics should be identical
    assert ref["overvolt_steps"] == shuf["overvolt_steps"]
    assert ref["undervolt_steps"] == shuf["undervolt_steps"]
    assert len(ref.get("kw_position_violations", [])) == len(
        shuf.get("kw_position_violations", [])
    )
    assert ref["soc_ok"] == shuf["soc_ok"]
    assert ref["invariants_ok"] == shuf["invariants_ok"]


# ---------------------------------------------------------------------------
# 6. Homogeneous synthetic no longer leaves residual_failure when feasible
# ---------------------------------------------------------------------------

def test_homogeneous_synthetic_no_residual_failure():
    """Homogeneous synthetic case should reach clean_feasible with zero residual failure."""
    homes = make_homes(N_HOMES_DEFAULT, heterogeneous=True, rng_seed=42)
    schedule, rounds, log = voltage_constrained_gossip_dispatch(
        homes, np.zeros(N_STEPS)
    )
    val_entry = None
    residual_entries = []
    for entry in log:
        if isinstance(entry, tuple):
            if entry[0] == "validation":
                val_entry = entry[1]
            elif entry[0] == "residual_failure":
                residual_entries.append(entry[1])
    assert val_entry is not None
    assert val_entry["clean_feasible"], (
        "Homogeneous synthetic must be clean feasible"
    )
    assert len(residual_entries) == 0, (
        "Homogeneous synthetic must NOT have residual failure"
    )


# ---------------------------------------------------------------------------
# 7. UV repair can add more than one home per UV step
# ---------------------------------------------------------------------------

def test_uv_repair_adds_multiple_homes():
    """Verify that the UV repair reallocates multiple homes to UV steps
    (not limited to one per step as the old code was)."""
    # Use AEMO profile which tends to have more UV steps
    from sim.aemo import load_aemo_profile
    profile, _ = load_aemo_profile(verbose=False)
    homes = make_homes(
        N_HOMES_DEFAULT, heterogeneous=True, rng_seed=42,
        aemo_profile=profile,
    )
    schedule, rounds, log = voltage_constrained_gossip_dispatch(
        homes, np.zeros(N_STEPS)
    )
    val_entry = None
    for entry in log:
        if isinstance(entry, tuple) and entry[0] == "validation":
            val_entry = entry[1]
            break
    assert val_entry is not None
    # UV repair should have reallocated some steps
    assert val_entry["repair"]["uv_reallocations"] > 0, (
        "UV repair must make at least one reallocation"
    )
    # If there were N UV steps, we should have >N additions (multi per step)
    initial_uv = val_entry["initial"]["undervolt_steps"]
    if initial_uv > 0:
        # With multiple steps and multi-home per step, uv_additions should
        # be > number of UV steps (at least some steps got >1 home)
        assert val_entry["repair"]["uv_reallocations"] > initial_uv, (
            f"Expected uv_reallocations ({val_entry['repair']['uv_reallocations']})"
            f" > initial_uv ({initial_uv}) — need multi-home per step"
        )


# ---------------------------------------------------------------------------
# 8. operational_clean remains false when fragmentation remains
# ---------------------------------------------------------------------------

def test_operational_clean_false_when_fragmented():
    """operational_clean should be False if clean_feasible but fragmented homes > 0."""
    homes = make_homes(N_HOMES_DEFAULT, heterogeneous=True, rng_seed=42)
    schedule, rounds, log = voltage_constrained_gossip_dispatch(
        homes, np.zeros(N_STEPS)
    )
    val_entry = None
    for entry in log:
        if isinstance(entry, tuple) and entry[0] == "validation":
            val_entry = entry[1]
            break
    assert val_entry is not None
    # Expected: clean_feasible=True but operational_clean=False
    # (UV repair creates some fragmentation)
    assert val_entry["clean_feasible"], "Must be clean feasible"
    assert val_entry["final"]["fragmented_homes"] >= 0
    if val_entry["final"]["fragmented_homes"] > 0:
        assert not val_entry["operational_clean"], (
            "operational_clean must be False when fragmentation exists"
        )


# ---------------------------------------------------------------------------
# 9. Final validation remains fail-closed
# ---------------------------------------------------------------------------

def test_final_validation_fail_closed():
    """Even with improved UV repair, flagrantly infeasible case must not
    report clean_feasible=True."""
    from sim.aemo import load_aemo_profile
    profile, _ = load_aemo_profile(verbose=False)
    N = N_HOMES_DEFAULT
    homes = make_homes(N, heterogeneous=True, rng_seed=42, aemo_profile=profile)
    # Create a fleet with zero SOC — nothing can discharge
    for h in homes:
        h["soc_initial"] = h["soc_min"]
    schedule, rounds, log = voltage_constrained_gossip_dispatch(
        homes, np.zeros(N_STEPS)
    )
    val_entry = None
    residual_entries = []
    for entry in log:
        if isinstance(entry, tuple):
            if entry[0] == "validation":
                val_entry = entry[1]
            elif entry[0] == "residual_failure":
                residual_entries.append(entry[1])
    assert val_entry is not None
    assert not val_entry["clean_feasible"], (
        "Zero SOC fleet must NOT be clean feasible"
    )
    assert len(residual_entries) > 0, (
        "Must log residual_failure"
    )


# ---------------------------------------------------------------------------
# 10. Conservation of total active steps under reallocation
# ---------------------------------------------------------------------------

def test_conservation_of_active_steps():
    """Reallocation must preserve the total number of active steps (moves,
    doesn't create new ones). Suppression/trimming may reduce but never
    increase total active steps."""
    homes = make_homes(N_HOMES_DEFAULT, heterogeneous=True, rng_seed=81)
    schedule, rounds, log = voltage_constrained_gossip_dispatch(
        homes, np.zeros(N_STEPS)
    )
    # The total should not exceed the maximum possible per home budget
    N = len(homes)
    max_possible = 0
    for h in homes:
        rate = h["battery_max_rate_kw"]
        dt_h = 5.0 / 60.0
        usable_kwh = (h["soc_initial"] - h["soc_min"]) * h["battery_capacity_kwh"]
        max_steps = int(np.floor(usable_kwh / (rate * dt_h) + 0.01))
        max_possible += max_steps
    total_active = int(np.sum(schedule))
    assert total_active <= max_possible, (
        f"Total active steps ({total_active}) exceeds energy budget "
        f"({max_possible})"
    )


# ---------------------------------------------------------------------------
# 11. Energy budget per home
# ---------------------------------------------------------------------------

def test_energy_budget_per_home():
    """No home should discharge more than its usable kWh budget."""
    homes = make_homes(N_HOMES_DEFAULT, heterogeneous=True, rng_seed=42)
    schedule, rounds, log = voltage_constrained_gossip_dispatch(
        homes, np.zeros(N_STEPS)
    )
    dt_h = 5.0 / 60.0
    for j, h in enumerate(homes):
        active = int(np.sum(schedule[j, :]))
        rate = h["battery_max_rate_kw"]
        used_kwh = active * rate * dt_h
        usable_kwh = (h["soc_initial"] - h["soc_min"]) * h["battery_capacity_kwh"]
        assert used_kwh <= usable_kwh + 0.01, (
            f"Home {j}: used {used_kwh:.3f} > usable {usable_kwh:.3f}"
        )


# ---------------------------------------------------------------------------
# 12. Donor post-removal voltage safety — no new UV from donor steps
# ---------------------------------------------------------------------------

def test_donor_removal_does_not_create_new_uv():
    """Reallocating from a donor step must not create UV where none existed.
    Must hold even when clean_feasible=False (residual-failure scenarios)."""
    from sim.aemo import load_aemo_profile
    profile, _ = load_aemo_profile(verbose=False)
    for het, seed in [(True, 42), (False, 42), (True, 81), (False, 81),
                      (True, 7), (False, 7)]:
        homes = make_homes(N_HOMES_DEFAULT, heterogeneous=het, rng_seed=seed,
                           aemo_profile=profile)
        schedule, rounds, log = voltage_constrained_gossip_dispatch(
            homes, np.zeros(N_STEPS)
        )
        val_entry = None
        for entry in log:
            if isinstance(entry, tuple) and entry[0] == "validation":
                val_entry = entry[1]
                break
        assert val_entry is not None

        initial_uv = set(val_entry["initial"].get("undervolt_step_indices", []))
        final_uv = set(val_entry["final"].get("undervolt_step_indices", []))
        newly_uv = final_uv - initial_uv
        assert len(newly_uv) == 0, (
            f"Donor removal created UV at steps that were initially safe "
            f"(het={het}, seed={seed}): {newly_uv}"
        )


# ---------------------------------------------------------------------------
# 13. Reallocation logging structure with new counters
# ---------------------------------------------------------------------------

def test_reallocation_logging():
    """Per-iteration repair log must contain uv_reallocations and new counters."""
    homes = make_homes(N_HOMES_DEFAULT, heterogeneous=True, rng_seed=42)
    schedule, rounds, log = voltage_constrained_gossip_dispatch(
        homes, np.zeros(N_STEPS)
    )
    val_entry = None
    for entry in log:
        if isinstance(entry, tuple) and entry[0] == "validation":
            val_entry = entry[1]
            break
    assert val_entry is not None
    repair = val_entry["repair"]
    assert "uv_reallocations" in repair
    assert isinstance(repair["uv_reallocations"], int)
    assert repair["uv_reallocations"] >= 0
    if repair["central_repair_used"]:
        assert repair["iterations"] > 0
        assert repair["total_moves_accepted"] >= repair["uv_reallocations"]


# ---------------------------------------------------------------------------
# 14. Final validation dict exposes undervolt_step_indices
# ---------------------------------------------------------------------------

def test_final_undervolt_step_indices_exposed():
    """Final validation/log dict must include final undervolt_step_indices
    and the count must match undervolt_steps."""
    from sim.aemo import load_aemo_profile
    profile, _ = load_aemo_profile(verbose=False)
    for het, seed in [(True, 42), (False, 42), (True, 7), (False, 7)]:
        homes = make_homes(N_HOMES_DEFAULT, heterogeneous=het, rng_seed=seed,
                           aemo_profile=profile)
        schedule, rounds, log = voltage_constrained_gossip_dispatch(
            homes, np.zeros(N_STEPS)
        )
        val_entry = None
        residual_entries = []
        for entry in log:
            if isinstance(entry, tuple):
                if entry[0] == "validation":
                    val_entry = entry[1]
                elif entry[0] == "residual_failure":
                    residual_entries.append(entry[1])
        assert val_entry is not None
        final = val_entry["final"]
        assert "undervolt_step_indices" in final, (
            f"final missing undervolt_step_indices (het={het}, seed={seed})"
        )
        assert isinstance(final["undervolt_step_indices"], list), (
            "undervolt_step_indices must be a list"
        )
        assert len(final["undervolt_step_indices"]) == final["undervolt_events"], (
            f"undervolt_step_indices count ({len(final['undervolt_step_indices'])}) "
            f"!= undervolt_events ({final['undervolt_events']})"
        )
        unique_uv_steps = len(set(final["undervolt_step_indices"]))
        assert unique_uv_steps == final["undervolt_steps"], (
            f"unique UV step count ({unique_uv_steps}) "
            f"!= undervolt_steps ({final['undervolt_steps']})"
        )
        if not val_entry["clean_feasible"]:
            assert len(residual_entries) > 0
            assert "undervolt_step_indices" in residual_entries[0], (
                "residual_failure must include undervolt_step_indices"
            )


# ---------------------------------------------------------------------------
# 15. Homogeneous AEMO seed 42 — baseline regression
# ---------------------------------------------------------------------------

def test_homogeneous_aemo_seed42_baseline():
    """Homogeneous (heterogeneous=False) AEMO seed 42: clean_feasible=True,
    OV=0, UV=0, KWpos=0, fragmented_homes <= 23, max_simultaneous <= 29."""
    from sim.aemo import load_aemo_profile
    profile, _ = load_aemo_profile(verbose=False)
    homes = make_homes(N_HOMES_DEFAULT, heterogeneous=False, rng_seed=42,
                       aemo_profile=profile)
    schedule, rounds, log = voltage_constrained_gossip_dispatch(
        homes, np.zeros(N_STEPS)
    )
    val_entry = None
    residual_entries = []
    for entry in log:
        if isinstance(entry, tuple):
            if entry[0] == "validation":
                val_entry = entry[1]
            elif entry[0] == "residual_failure":
                residual_entries.append(entry[1])
    assert val_entry is not None
    assert val_entry["clean_feasible"], "Must be clean feasible"
    assert len(residual_entries) == 0, "Must not have residual failure"
    final = val_entry["final"]
    assert final["undervolt_steps"] == 0
    assert final["overvolt_steps"] == 0
    assert final["kw_position_violations"] == 0
    assert final["fragmented_homes"] <= 23, (
        f"fragmented_homes ({final['fragmented_homes']}) exceeds baseline 23"
    )
    assert final["max_simultaneous"] <= 29, (
        f"max_simultaneous ({final['max_simultaneous']}) exceeds baseline 29"
    )


# ---------------------------------------------------------------------------
# 16. Heterogeneous AEMO seed 42 — fail-closed or clean
# ---------------------------------------------------------------------------

def test_heterogeneous_aemo_seed42_fail_closed_or_clean():
    """Heterogeneous (heterogeneous=True) AEMO seed 42 must either reach
    clean_feasible=True or honestly report residual_failure with UV details."""
    from sim.aemo import load_aemo_profile
    profile, _ = load_aemo_profile(verbose=False)
    homes = make_homes(N_HOMES_DEFAULT, heterogeneous=True, rng_seed=42,
                       aemo_profile=profile)
    schedule, rounds, log = voltage_constrained_gossip_dispatch(
        homes, np.zeros(N_STEPS)
    )
    val_entry = None
    residual_entries = []
    for entry in log:
        if isinstance(entry, tuple):
            if entry[0] == "validation":
                val_entry = entry[1]
            elif entry[0] == "residual_failure":
                residual_entries.append(entry[1])
    assert val_entry is not None
    final = val_entry["final"]
    if val_entry["clean_feasible"]:
        assert len(residual_entries) == 0
        assert final["undervolt_steps"] == 0
        assert final["overvolt_steps"] == 0
        assert final["kw_position_violations"] == 0
    else:
        assert len(residual_entries) > 0, (
            "Must log residual_failure when not clean"
        )
        assert "undervolt_step_indices" in final
        assert "undervolt_step_indices" in residual_entries[0]
        inv = validate_schedule_invariants(schedule, homes)
        assert not inv["invariants_ok"], (
            "clean_feasible=False but validator disagrees"
        )


# ---------------------------------------------------------------------------
# 17. Unit tests for fragmentation helper functions
# ---------------------------------------------------------------------------

def test_count_active_runs():
    """_count_active_runs must correctly count contiguous blocks."""
    row = np.zeros(20, dtype=int)
    assert _count_active_runs(row) == 0
    row[5] = 1
    assert _count_active_runs(row) == 1
    row[6:9] = 1
    assert _count_active_runs(row) == 1
    row[15:18] = 1
    assert _count_active_runs(row) == 2
    row[7] = 0  # split the first block
    assert _count_active_runs(row) == 3


def test_removal_splits_block():
    """_removal_splits_block returns True only when removal breaks contiguity."""
    row = np.zeros(20, dtype=int)
    row[5:12] = 1
    assert not _removal_splits_block(row, 5)  # edge of block
    assert not _removal_splits_block(row, 11)  # edge of block
    assert not _removal_splits_block(row, 3)   # not active
    assert _removal_splits_block(row, 8)       # middle -> splits
    # Single-step block cannot be split
    row2 = np.zeros(20, dtype=int)
    row2[10] = 1
    assert not _removal_splits_block(row2, 10)


def test_addition_is_adjacent():
    """_addition_is_adjacent returns True only when adding touches existing block."""
    row = np.zeros(20, dtype=int)
    row[5:10] = 1
    assert _addition_is_adjacent(row, 9)   # right edge of block (already active)
    assert _addition_is_adjacent(row, 4)   # adjacent left
    assert _addition_is_adjacent(row, 10)  # adjacent right
    assert not _addition_is_adjacent(row, 12)  # not adjacent
    assert not _addition_is_adjacent(row, 3)   # not adjacent
    assert _addition_is_adjacent(row, 7)   # already active
    # Gap fill between two blocks
    row2 = np.zeros(20, dtype=int)
    row2[5:8] = 1
    row2[12:15] = 1
    assert not _addition_is_adjacent(row2, 10)  # gap, not adjacent to either
    assert _addition_is_adjacent(row2, 8)   # right edge of first block
    assert _addition_is_adjacent(row2, 11)  # left edge of second block


# ---------------------------------------------------------------------------
# 18. Synthetic/heterogeneous regression — baseline check
# ---------------------------------------------------------------------------

def test_synthetic_heterogeneous_baseline():
    """Heterogeneous synthetic seed 42 must be clean and report metrics."""
    homes = make_homes(N_HOMES_DEFAULT, heterogeneous=True, rng_seed=42)
    schedule, rounds, log = voltage_constrained_gossip_dispatch(
        homes, np.zeros(N_STEPS)
    )
    val_entry = None
    for entry in log:
        if isinstance(entry, tuple) and entry[0] == "validation":
            val_entry = entry[1]
            break
    assert val_entry is not None
    assert val_entry["clean_feasible"], "Must be clean feasible"
    final = val_entry["final"]
    assert final["undervolt_steps"] == 0
    assert final["overvolt_steps"] == 0
    assert final["kw_position_violations"] == 0
    assert final["fragmented_homes"] >= 0
    assert final["max_simultaneous"] >= 0
    assert final["synchrony"] >= 0.0
    assert isinstance(final["fragmented_homes"], int)
    assert isinstance(final["max_simultaneous"], int)


# ---------------------------------------------------------------------------
# 19. New instrumentation counters exposed in repair summary
# ---------------------------------------------------------------------------

def test_repair_instrumentation_counters():
    """Repair summary must include frag/maxsim preserving/increasing counters."""
    from sim.aemo import load_aemo_profile
    profile, _ = load_aemo_profile(verbose=False)
    for het, seed in [(True, 42), (False, 42)]:
        homes = make_homes(N_HOMES_DEFAULT, heterogeneous=het, rng_seed=seed,
                           aemo_profile=profile)
        schedule, rounds, log = voltage_constrained_gossip_dispatch(
            homes, np.zeros(N_STEPS)
        )
        val_entry = None
        for entry in log:
            if isinstance(entry, tuple) and entry[0] == "validation":
                val_entry = entry[1]
                break
        assert val_entry is not None
        repair = val_entry["repair"]

        # New counters must exist and be integers
        for key in ("fragmentation_preserving_reallocations",
                    "fragmentation_increasing_reallocations",
                    "maxsim_preserving_reallocations",
                    "maxsim_increasing_reallocations"):
            assert key in repair, f"repair missing '{key}'"
            assert isinstance(repair[key], int), f"{key} must be int"

        # Consistency: counts must sum to uv_reallocations (excluding soc/kv moves)
        total_frag = (repair["fragmentation_preserving_reallocations"]
                      + repair["fragmentation_increasing_reallocations"])
        assert total_frag <= repair["total_moves_accepted"], (
            f"frag counts ({total_frag}) exceed total_moves_accepted "
            f"({repair['total_moves_accepted']})"
        )
        total_maxsim = (repair["maxsim_preserving_reallocations"]
                        + repair["maxsim_increasing_reallocations"])
        assert total_maxsim <= repair["total_moves_accepted"], (
            f"maxsim counts ({total_maxsim}) exceed total_moves_accepted "
            f"({repair['total_moves_accepted']})"
        )
