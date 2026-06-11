"""
Tests for AEMO data loading and AEMO-driven scenario integrity.

These tests verify:
  1. AEMO data loads at exactly 17,568 rows
  2. Representative day profile resamples to 288 steps
  3. AEMO-driven naive scenario produces battery-window voltage violations
  4. AEMO-driven gossip scenario eliminates those violations
  5. Breach-cause separation (pv_export vs battery_herding) is consistent
  6. AEMO and synthetic scenarios agree on the structural herding story
"""

import sys
import os
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sim.aemo import load_aemo_raw, load_aemo_profile, EXPECTED_ROWS
from sim.simulator import run_scenario, compute_metrics
from sim.feeder import V_MAX_PU, V_MIN_PU

# ---------------------------------------------------------------------------
# Fixtures: load AEMO data and AEMO-driven scenarios once per module
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def aemo_rows():
    return load_aemo_raw()

@pytest.fixture(scope="module")
def aemo_profile_and_meta():
    return load_aemo_profile(verbose=False)

@pytest.fixture(scope="module")
def aemo_profile(aemo_profile_and_meta):
    profile, _ = aemo_profile_and_meta
    return profile

@pytest.fixture(scope="module")
def aemo_naive_hom(aemo_profile):
    return run_scenario("naive", heterogeneous=False, aemo_profile=aemo_profile, load_source="aemo")

@pytest.fixture(scope="module")
def aemo_gossip_het(aemo_profile):
    return run_scenario("gossip", heterogeneous=True, aemo_profile=aemo_profile, load_source="aemo")

@pytest.fixture(scope="module")
def aemo_gossip_hom(aemo_profile):
    return run_scenario("gossip", heterogeneous=False, aemo_profile=aemo_profile, load_source="aemo")

@pytest.fixture(scope="module")
def aemo_naive_het(aemo_profile):
    return run_scenario("naive", heterogeneous=True, aemo_profile=aemo_profile, load_source="aemo")


# ---------------------------------------------------------------------------
# Test A1: AEMO data loads at exactly 17,568 rows
# ---------------------------------------------------------------------------

def test_aemo_row_count(aemo_rows):
    """
    2012 is a leap year: 366 days × 48 half-hours = 17,568 rows.
    This assertion is the data integrity check — if it fails, a file is missing
    or truncated.
    """
    assert len(aemo_rows) == EXPECTED_ROWS, (
        f"Expected {EXPECTED_ROWS} AEMO rows (2012 leap year), got {len(aemo_rows)}."
    )


def test_aemo_date_range(aemo_rows):
    """Date range should span all of 2012."""
    dates = [r["date"] for r in aemo_rows]
    assert dates[0].year == 2012, f"First date should be 2012, got {dates[0]}"
    assert dates[-1].year in (2012, 2013), f"Last date should be 2012/early 2013, got {dates[-1]}"
    # First entry should be 2012-01-01 00:30 (first half-hour end)
    assert dates[0].month == 1 and dates[0].day == 1, (
        f"First entry should be Jan 1 2012, got {dates[0]}"
    )


def test_aemo_demand_plausible(aemo_rows):
    """Victorian demand should be plausibly in the 3,000-10,000 MW range."""
    demands = [r["demand_mw"] for r in aemo_rows]
    assert min(demands) > 2000, f"Min demand suspiciously low: {min(demands)} MW"
    assert max(demands) < 15000, f"Max demand suspiciously high: {max(demands)} MW"


# ---------------------------------------------------------------------------
# Test A2: Profile resamples to 288 steps with correct range
# ---------------------------------------------------------------------------

def test_aemo_profile_shape(aemo_profile):
    """Profile must be 288 steps (24h at 5-min resolution)."""
    assert aemo_profile.shape == (288,), (
        f"AEMO profile should have shape (288,), got {aemo_profile.shape}"
    )


def test_aemo_profile_range(aemo_profile):
    """Profile values should be within the feeder base-load range."""
    from sim.aemo import FEEDER_BASE_MIN_KW, FEEDER_BASE_MAX_KW
    assert float(np.min(aemo_profile)) >= FEEDER_BASE_MIN_KW - 0.01, (
        f"Profile min {np.min(aemo_profile):.3f} below FEEDER_BASE_MIN_KW {FEEDER_BASE_MIN_KW}"
    )
    assert float(np.max(aemo_profile)) <= FEEDER_BASE_MAX_KW + 0.01, (
        f"Profile max {np.max(aemo_profile):.3f} above FEEDER_BASE_MAX_KW {FEEDER_BASE_MAX_KW}"
    )


def test_aemo_representative_date(aemo_profile_and_meta):
    """Representative date should be in January or February 2012 (Victorian summer)."""
    _, meta = aemo_profile_and_meta
    from datetime import date
    rep_date = date.fromisoformat(meta["representative_date"])
    assert rep_date.year == 2012, f"Representative date year should be 2012, got {rep_date}"
    assert rep_date.month in (1, 2), (
        f"Representative date should be Jan or Feb (summer), got month {rep_date.month}"
    )


# ---------------------------------------------------------------------------
# Test A3: AEMO-driven naive scenario causes battery-window violations
# ---------------------------------------------------------------------------

def test_aemo_naive_causes_battery_overvoltage(aemo_naive_hom):
    """
    With real AEMO evening peak shape and all 60 batteries discharging simultaneously,
    overvoltage should still occur in the battery window (17:00-21:40).
    """
    voltages = aemo_naive_hom["voltage_series"]
    BAT_WIN_START = 204
    BAT_WIN_END = 260
    v_bat = voltages[:, BAT_WIN_START:BAT_WIN_END]
    overvolt_steps = int(np.sum(np.any(v_bat > V_MAX_PU, axis=0)))

    assert overvolt_steps > 0, (
        f"AEMO-driven naive homogeneous scenario should still produce battery-window "
        f"overvoltage. Got 0 steps. The herding story must hold with real data."
    )


def test_aemo_naive_full_synchrony(aemo_naive_hom):
    """Naive homogeneous should still achieve synchrony=1.0 with AEMO load."""
    n = aemo_naive_hom["n_homes"]
    dispatch = aemo_naive_hom["dispatch_series"]
    max_sim = int(np.max(np.sum(dispatch == 1, axis=0)))
    assert max_sim == n, (
        f"AEMO naive hom: expected max simultaneous = {n}, got {max_sim}"
    )


# ---------------------------------------------------------------------------
# Test A4: AEMO-driven gossip eliminates battery violations
# ---------------------------------------------------------------------------

def test_aemo_gossip_eliminates_battery_overvoltage_hom(aemo_gossip_hom):
    """Gossip on homogeneous AEMO fleet: zero battery-window overvoltage."""
    voltages = aemo_gossip_hom["voltage_series"]
    BAT_WIN_START = 204
    BAT_WIN_END = 260
    v_bat = voltages[:, BAT_WIN_START:BAT_WIN_END]
    overvolt_steps = int(np.sum(np.any(v_bat > V_MAX_PU, axis=0)))

    assert overvolt_steps == 0, (
        f"AEMO gossip (hom) should eliminate battery-window overvoltage. "
        f"Got {overvolt_steps} steps."
    )


def test_aemo_gossip_eliminates_battery_overvoltage_het(aemo_gossip_het):
    """Gossip on heterogeneous AEMO fleet: zero battery-window overvoltage."""
    voltages = aemo_gossip_het["voltage_series"]
    BAT_WIN_START = 204
    BAT_WIN_END = 260
    v_bat = voltages[:, BAT_WIN_START:BAT_WIN_END]
    overvolt_steps = int(np.sum(np.any(v_bat > V_MAX_PU, axis=0)))

    assert overvolt_steps == 0, (
        f"AEMO gossip (het) should eliminate battery-window overvoltage. "
        f"Got {overvolt_steps} steps."
    )


def test_aemo_naive_has_more_overvoltage_than_gossip(aemo_naive_hom, aemo_gossip_hom):
    """AEMO naive has more battery-window violations than AEMO gossip."""
    BAT_WIN_START = 204
    BAT_WIN_END = 260
    v_naive = aemo_naive_hom["voltage_series"][:, BAT_WIN_START:BAT_WIN_END]
    v_gossip = aemo_gossip_hom["voltage_series"][:, BAT_WIN_START:BAT_WIN_END]
    naive_ov = int(np.sum(np.any(v_naive > V_MAX_PU, axis=0)))
    gossip_ov = int(np.sum(np.any(v_gossip > V_MAX_PU, axis=0)))

    assert naive_ov > gossip_ov, (
        f"AEMO naive should have more battery overvoltage than gossip. "
        f"naive={naive_ov}, gossip={gossip_ov}"
    )


# ---------------------------------------------------------------------------
# Test A5: Breach-cause separation holds
# ---------------------------------------------------------------------------

def test_breach_cause_separation_synthetic():
    """
    In synthetic scenarios, battery_herding events must be in the evening window,
    pv_export events must be in the midday window. No confusion between causes.
    """
    result = run_scenario("naive", heterogeneous=False)
    events = result["voltage_breach_events"]

    PV_WIN_START  = 120
    PV_WIN_END    = 180
    BAT_WIN_START = 204
    BAT_WIN_END   = 260

    for e in events:
        if e["cause"] == "pv_export":
            assert PV_WIN_START <= e["step"] < PV_WIN_END, (
                f"pv_export event at step {e['step']} outside PV window [{PV_WIN_START},{PV_WIN_END})"
            )
        elif e["cause"] == "battery_herding":
            assert BAT_WIN_START <= e["step"] < BAT_WIN_END, (
                f"battery_herding event at step {e['step']} outside battery window [{BAT_WIN_START},{BAT_WIN_END})"
            )


def test_breach_cause_separation_aemo(aemo_naive_hom):
    """
    In AEMO scenarios, all battery_herding events must be in the evening window.
    (AEMO profile has no PV, so pv_export events should be zero.)
    """
    events = aemo_naive_hom["voltage_breach_events"]

    BAT_WIN_START = 204
    BAT_WIN_END   = 260

    for e in events:
        if e["cause"] == "battery_herding":
            assert BAT_WIN_START <= e["step"] < BAT_WIN_END, (
                f"battery_herding event at step {e['step']} outside battery window"
            )

    bat_count = sum(1 for e in events if e["cause"] == "battery_herding")
    assert bat_count > 0, (
        "AEMO naive hom should have battery_herding breach events."
    )


def test_gossip_has_zero_battery_herding_overvoltage_events():
    """
    After gossip, there must be zero battery_herding OVERVOLTAGE events.
    (Gossip may still have undervoltage in the battery window because staggered
    discharge means fewer batteries supplying the feeder at any moment —
    SESSION_STATE KNOWN_ISSUES. The demo story is overvoltage elimination,
    not undervoltage. Compliance agent watches for overvoltage specifically.)
    """
    for het in (False, True):
        result = run_scenario("gossip", heterogeneous=het)
        events = result["voltage_breach_events"]
        bat_ov_events = [
            e for e in events
            if e["cause"] == "battery_herding" and e["band_limit_crossed"] == "upper"
        ]
        assert len(bat_ov_events) == 0, (
            f"Gossip (het={het}) should produce zero battery_herding OVERVOLTAGE events. "
            f"Got {len(bat_ov_events)}: {bat_ov_events[:2]}"
        )


def test_breach_event_fields_complete():
    """Every breach event must have all required fields for the Compliance agent."""
    result = run_scenario("naive", heterogeneous=False)
    required_fields = {"step", "time_hhmm", "node_id", "voltage_pu",
                       "band_limit_crossed", "band_limit_value", "cause"}
    events = result["voltage_breach_events"]
    assert len(events) > 0, "naive_hom should have breach events"
    for e in events[:10]:
        missing = required_fields - set(e.keys())
        assert not missing, f"Breach event missing fields: {missing}. Event: {e}"
        assert e["band_limit_crossed"] in ("upper", "lower"), (
            f"band_limit_crossed must be 'upper' or 'lower', got {e['band_limit_crossed']}"
        )
        assert e["cause"] in ("pv_export", "battery_herding", "other"), (
            f"cause must be one of pv_export/battery_herding/other, got {e['cause']}"
        )
