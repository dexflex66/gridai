"""
AEMO 2012 Victorian load profile loader.

Reads 12 monthly CSV files (PRICE_AND_DEMAND_2012MM_VIC1.csv) from DATA_DIR,
concatenates them, asserts exactly 17,568 half-hourly rows (2012 is a leap year:
366 days × 48 half-hours), and resamples a representative high-demand summer day
to 5-minute resolution (288 steps) for use as the feeder base-load shape.

Representative day selection: pick the day with the highest evening peak
(17:00-20:00 window) TOTALDEMAND across January and February 2012.
Victorian summer — the evening peak is when air-conditioners, cooking, and
returning commuters all load the grid simultaneously, which is the same scenario
our battery herding story plays out over.

The resampled 288-step profile is normalised to mean per-home demand (kW) by
dividing by a residential scaling factor that maps AEMO MW aggregate to a 60-home
LV feeder at a realistic penetration.
"""

import os
import csv
from datetime import datetime
import numpy as np

# Path to monthly CSV files
DATA_DIR = "/Users/mayank/Downloads/Data"

# Expected total row count: 2012 leap year, 48 half-hours/day, 366 days
EXPECTED_ROWS = 17568

# AEMO total Victorian demand is ~5000-9000 MW.
# We map this to a 60-home LV feeder whose typical peak per-home is ~2.5 kW.
# Scale: 60 homes × 2.5 kW = 150 kW feeder peak.
# Typical AEMO evening peak ~7000 MW = 7,000,000 kW.
# We want the mean per-home shape (not the absolute MW number).
# Approach: normalise the day's demand curve to unit range, then rescale to
# the feeder's typical base-load range (0.3-2.5 kW per home).
# The shape (relative variation) is real; the absolute level is feeder-appropriate.
FEEDER_BASE_MIN_KW = 0.30   # overnight valley
FEEDER_BASE_MAX_KW = 2.50   # evening peak


def load_aemo_raw() -> list:
    """
    Load and concatenate all 12 monthly AEMO CSV files.
    Returns list of dicts: [{date: datetime, demand_mw: float, price: float}, ...]
    Asserts exactly EXPECTED_ROWS rows.
    """
    months = [f"{m:02d}" for m in range(1, 13)]
    rows = []

    for mm in months:
        path = os.path.join(DATA_DIR, f"PRICE_AND_DEMAND_2012{mm}_VIC1.csv")
        if not os.path.exists(path):
            raise FileNotFoundError(f"Missing AEMO file: {path}")
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                dt = datetime.strptime(row["SETTLEMENTDATE"].strip('"'), "%Y/%m/%d %H:%M:%S")
                rows.append({
                    "date": dt,
                    "demand_mw": float(row["TOTALDEMAND"]),
                    "price": float(row["RRP"]),
                })

    n = len(rows)
    assert n == EXPECTED_ROWS, (
        f"AEMO data row count mismatch: expected {EXPECTED_ROWS}, got {n}. "
        f"Check that all 12 CSV files are present and complete."
    )

    # Sort by date (files should already be sorted but be safe)
    rows.sort(key=lambda r: r["date"])
    return rows


def load_aemo_profile(verbose: bool = True) -> tuple:
    """
    Load AEMO data, find the representative high-demand summer day, and
    return a 288-step (5-min) per-home base-load profile.

    Returns:
      profile: np.ndarray shape (288,) — mean per-home base load kW
      meta: dict with representative date, reason, stats
    """
    rows = load_aemo_raw()

    # Compute basic stats
    demands = [r["demand_mw"] for r in rows]
    prices  = [r["price"]     for r in rows]
    dates   = [r["date"]      for r in rows]

    stats = {
        "n_rows":       len(rows),
        "date_min":     str(dates[0]),
        "date_max":     str(dates[-1]),
        "demand_min_mw": round(min(demands), 2),
        "demand_max_mw": round(max(demands), 2),
        "demand_mean_mw": round(sum(demands) / len(demands), 2),
        "price_min":    round(min(prices), 2),
        "price_max":    round(max(prices), 2),
        "price_mean":   round(sum(prices) / len(prices), 2),
    }

    if verbose:
        print("\n--- AEMO data loaded ---")
        print(f"  Rows:          {stats['n_rows']}  (expected {EXPECTED_ROWS}) ✓")
        print(f"  Date range:    {stats['date_min']}  to  {stats['date_max']}")
        print(f"  Demand (MW):   min={stats['demand_min_mw']}  max={stats['demand_max_mw']}  mean={stats['demand_mean_mw']}")
        print(f"  Price ($/MWh): min={stats['price_min']}  max={stats['price_max']}  mean={stats['price_mean']}")

    # Group by calendar date (using the date portion only)
    from collections import defaultdict
    daily = defaultdict(list)
    for r in rows:
        day_key = r["date"].date()
        daily[day_key].append(r)

    # Select summer months: January and February 2012
    summer_days = {
        d: v for d, v in daily.items()
        if d.month in (1, 2)
    }

    # For each summer day, find max demand in the evening peak window (17:00-20:00).
    # AEMO SETTLEMENTDATE is the END of the half-hour, so 17:30 covers 17:00-17:30.
    # Evening peak window: half-hours with end times 17:30, 18:00, ..., 20:00 (7 slots).
    EVENING_PEAK_HOURS = {17, 18, 19, 20}

    best_day = None
    best_evening_peak = -1.0

    for day, day_rows in summer_days.items():
        evening_demands = [
            r["demand_mw"]
            for r in day_rows
            if r["date"].hour in EVENING_PEAK_HOURS
        ]
        if not evening_demands:
            continue
        peak = max(evening_demands)
        if peak > best_evening_peak:
            best_evening_peak = peak
            best_day = day

    if best_day is None:
        raise RuntimeError("Could not find a representative summer day in AEMO data.")

    if verbose:
        print(f"\n  Representative day: {best_day}  (evening peak demand: {best_evening_peak:.1f} MW)")
        print(f"  Reason: highest evening (17:00-20:00) peak across Jan-Feb 2012 (Victorian summer).")

    # Extract the 48 half-hourly demand values for the representative day.
    day_rows = sorted(daily[best_day], key=lambda r: r["date"])
    day_demands_mw = np.array([r["demand_mw"] for r in day_rows], dtype=float)

    assert len(day_demands_mw) == 48, (
        f"Representative day {best_day} has {len(day_demands_mw)} half-hours, expected 48."
    )

    # Resample 48 half-hourly steps -> 288 five-minute steps via linear interpolation.
    # Each half-hour value is treated as the midpoint of that half-hour.
    # Upsample factor: 288 / 48 = 6 (each half-hour -> 6 five-minute steps).
    x_half = np.linspace(0, 1, 48)
    x_fivemin = np.linspace(0, 1, 288)
    day_5min_mw = np.interp(x_fivemin, x_half, day_demands_mw)

    # Normalise to mean per-home base load kW.
    # Scale so that the shape min->max maps to FEEDER_BASE_MIN_KW->FEEDER_BASE_MAX_KW.
    d_min = float(np.min(day_5min_mw))
    d_max = float(np.max(day_5min_mw))
    d_range = d_max - d_min
    if d_range < 1e-6:
        raise RuntimeError("Representative day demand has zero range after interpolation.")

    profile = (
        (day_5min_mw - d_min) / d_range
        * (FEEDER_BASE_MAX_KW - FEEDER_BASE_MIN_KW)
        + FEEDER_BASE_MIN_KW
    )

    meta = {
        "representative_date": str(best_day),
        "reason": "highest evening peak (17:00-20:00) across Jan-Feb 2012 (Victorian summer)",
        "evening_peak_mw": round(best_evening_peak, 2),
        "n_half_hours": 48,
        "n_steps_5min": 288,
        "profile_min_kw": round(float(np.min(profile)), 3),
        "profile_max_kw": round(float(np.max(profile)), 3),
        "profile_mean_kw": round(float(np.mean(profile)), 3),
        "stats": stats,
    }

    return profile, meta


if __name__ == "__main__":
    profile, meta = load_aemo_profile(verbose=True)
    print(f"\nProfile ready:")
    print(f"  Representative date: {meta['representative_date']}")
    print(f"  Reason: {meta['reason']}")
    print(f"  5-min profile shape: {profile.shape}")
    print(f"  kW range: {meta['profile_min_kw']} – {meta['profile_max_kw']}")
    print(f"  kW mean:  {meta['profile_mean_kw']}")
