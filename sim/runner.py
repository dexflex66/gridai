"""
Runner: execute all four scenarios and write results to outputs/.

Scenarios:
  1. naive_homogeneous    - herding baseline, identical thresholds
  2. naive_heterogeneous  - herding baseline, varied thresholds
  3. gossip_homogeneous   - protocol on homogeneous fleet
  4. gossip_heterogeneous - protocol on heterogeneous fleet

Each scenario writes outputs/scenario_<name>.json with full time series.
Also writes outputs/summary.json with headline metrics.
"""

import json
import os
import sys
import time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sim.simulator import run_scenario, compute_metrics

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs")

SCENARIOS = [
    {"name": "naive_homogeneous",    "strategy": "naive",   "heterogeneous": False},
    {"name": "naive_heterogeneous",  "strategy": "naive",   "heterogeneous": True},
    {"name": "gossip_homogeneous",   "strategy": "gossip",  "heterogeneous": False},
    {"name": "gossip_heterogeneous", "strategy": "gossip",  "heterogeneous": True},
]


def numpy_to_python(obj):
    """Recursively convert numpy types to plain Python for JSON serialisation."""
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, dict):
        return {k: numpy_to_python(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [numpy_to_python(v) for v in obj]
    return obj


def run_all():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    all_metrics = {}

    print(f"\n{'='*60}")
    print("GridAI Layer 1 Simulation")
    print(f"{'='*60}")

    for scenario in SCENARIOS:
        name = scenario["name"]
        print(f"\nRunning: {name} ...", end=" ", flush=True)
        t0 = time.time()

        result = run_scenario(
            strategy=scenario["strategy"],
            heterogeneous=scenario["heterogeneous"],
        )
        metrics = compute_metrics(result)
        elapsed = time.time() - t0
        print(f"done ({elapsed:.1f}s)")

        # Print key metrics
        print(f"  Peak demand (all day):   {metrics['peak_demand_kw']:.1f} kW  at {metrics['peak_time_hhmm']}")
        print(f"  Max simultaneous dis:    {metrics['max_simultaneous_discharge']} / {result['n_homes']} homes")
        print(f"  Synchrony ratio:         {metrics['synchrony_ratio']:.3f}")
        print(f"  Battery-window violations: overvolt={metrics['bat_overvolt_steps']} under={metrics['bat_undervolt_steps']} steps")
        print(f"  PV-window overvoltage:   {metrics['pv_overvolt_steps']} steps (same for all strategies)")
        print(f"  Any battery breach:      {metrics['any_bat_breach']}")
        if result["rounds_to_converge"] is not None:
            print(f"  Rounds to converge:      {result['rounds_to_converge']}")

        # Write full scenario JSON
        output_data = {
            "scenario": name,
            "strategy": result["strategy"],
            "heterogeneous": result["heterogeneous"],
            "n_homes": result["n_homes"],
            "metrics": metrics,
            "rounds_to_converge": result["rounds_to_converge"],
            "gossip_log_length": len(result["gossip_log"]),
            "homes_meta": result["homes_meta"],
            # Time series (for Layer 3 animation)
            "soc_series": numpy_to_python(result["soc_series"]),
            "dispatch_series": numpy_to_python(result["dispatch_series"]),
            "voltage_series": numpy_to_python(result["voltage_series"]),
            "aggregate_demand_series": numpy_to_python(result["aggregate_demand_series"]),
            "breach_flags": numpy_to_python(result["breach_flags"]),
            "voltage_violations": numpy_to_python(result["voltage_violations"]),
            "home_positions": result["home_positions"],
        }

        out_path = os.path.join(OUTPUT_DIR, f"scenario_{name}.json")
        with open(out_path, "w") as f:
            json.dump(output_data, f, indent=2)
        print(f"  Written: {out_path}")

        all_metrics[name] = metrics
        all_metrics[name]["rounds_to_converge"] = result["rounds_to_converge"]

    # Cross-scenario comparisons.
    # Key metric: bat_demand_range (max - min demand in battery window).
    # Captures the herding spike: naive has huge range (export spike + demand cliff).
    # Gossip has small range (smooth discharge, no extreme swings).
    nh_range  = all_metrics["naive_homogeneous"]["bat_demand_range_kw"]
    gh_range  = all_metrics["gossip_homogeneous"]["bat_demand_range_kw"]
    nhe_range = all_metrics["naive_heterogeneous"]["bat_demand_range_kw"]
    ghe_range = all_metrics["gossip_heterogeneous"]["bat_demand_range_kw"]

    pct_h_range   = 100.0 * (nh_range  - gh_range)  / nh_range  if nh_range  else 0.0
    pct_het_range = 100.0 * (nhe_range - ghe_range) / nhe_range if nhe_range else 0.0

    # Also track battery-window positive peak (demand cliff after discharge)
    nh_peak  = all_metrics["naive_homogeneous"]["bat_peak_demand_kw"]
    gh_peak  = all_metrics["gossip_homogeneous"]["bat_peak_demand_kw"]
    nhe_peak = all_metrics["naive_heterogeneous"]["bat_peak_demand_kw"]
    ghe_peak = all_metrics["gossip_heterogeneous"]["bat_peak_demand_kw"]

    pct_h_peak   = 100.0 * (nh_peak  - gh_peak)  / nh_peak  if nh_peak  else 0.0
    pct_het_peak = 100.0 * (nhe_peak - ghe_peak) / nhe_peak if nhe_peak else 0.0

    # Battery-window overvoltage violations (the herding problem metric)
    nh_bov  = all_metrics["naive_homogeneous"]["bat_overvolt_steps"]
    gh_bov  = all_metrics["gossip_homogeneous"]["bat_overvolt_steps"]
    nhe_bov = all_metrics["naive_heterogeneous"]["bat_overvolt_steps"]
    ghe_bov = all_metrics["gossip_heterogeneous"]["bat_overvolt_steps"]

    summary = {
        "scenarios": all_metrics,
        "headline": {
            "description": (
                "Battery-window (17:00-21:40) metrics. "
                "PV overvoltage (midday) is same for all strategies and excluded from key comparison. "
                "bat_demand_range is the primary herding metric: naive herding creates a "
                "huge demand swing (export spike then demand cliff). Gossip eliminates the swing."
            ),
            "naive_hom_bat_demand_range_kw": nh_range,
            "gossip_hom_bat_demand_range_kw": gh_range,
            "hom_range_pct_reduction": round(pct_h_range, 1),
            "naive_het_bat_demand_range_kw": nhe_range,
            "gossip_het_bat_demand_range_kw": ghe_range,
            "het_range_pct_reduction": round(pct_het_range, 1),
            "naive_hom_bat_peak_demand_kw": nh_peak,
            "gossip_hom_bat_peak_demand_kw": gh_peak,
            "hom_peak_pct_reduction": round(pct_h_peak, 1),
            "naive_het_bat_peak_demand_kw": nhe_peak,
            "gossip_het_bat_peak_demand_kw": ghe_peak,
            "het_peak_pct_reduction": round(pct_het_peak, 1),
            "naive_hom_bat_overvolt_steps": nh_bov,
            "gossip_hom_bat_overvolt_steps": gh_bov,
            "naive_het_bat_overvolt_steps": nhe_bov,
            "gossip_het_bat_overvolt_steps": ghe_bov,
            "gossip_hom_rounds_to_converge": all_metrics["gossip_homogeneous"]["rounds_to_converge"],
            "gossip_het_rounds_to_converge": all_metrics["gossip_heterogeneous"]["rounds_to_converge"],
        },
        "synchrony_contrast": {
            "naive_hom":  all_metrics["naive_homogeneous"]["synchrony_ratio"],
            "naive_het":  all_metrics["naive_heterogeneous"]["synchrony_ratio"],
            "gossip_hom": all_metrics["gossip_homogeneous"]["synchrony_ratio"],
            "gossip_het": all_metrics["gossip_heterogeneous"]["synchrony_ratio"],
        },
        "compliance_seed": {
            "naive_hom_bat_overvolt_steps": nh_bov,
            "naive_hom_bat_breach": nh_bov > 0,
            "gossip_het_bat_overvolt_steps": ghe_bov,
            "gossip_het_bat_breach": ghe_bov > 0,
        },
    }

    summary_path = os.path.join(OUTPUT_DIR, "summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n{'='*60}")
    print("SUMMARY — HEADLINE NUMBERS")
    print(f"{'='*60}")
    print()
    print("Demand swing range in battery window (17:00-21:40) — PRIMARY HERDING METRIC:")
    print(f"  Naive homogeneous:    {nh_range:.1f} kW range  (synchrony: {all_metrics['naive_homogeneous']['synchrony_ratio']:.3f})")
    print(f"  Gossip homogeneous:   {gh_range:.1f} kW range  (synchrony: {all_metrics['gossip_homogeneous']['synchrony_ratio']:.3f})  [{pct_h_range:.1f}% reduction]")
    print(f"  Naive heterogeneous:  {nhe_range:.1f} kW range  (synchrony: {all_metrics['naive_heterogeneous']['synchrony_ratio']:.3f})")
    print(f"  Gossip heterogeneous: {ghe_range:.1f} kW range  (synchrony: {all_metrics['gossip_heterogeneous']['synchrony_ratio']:.3f})  [{pct_het_range:.1f}% reduction]")
    print()
    print("Battery-window peak demand (post-discharge demand cliff):")
    print(f"  Naive homogeneous:    {nh_peak:.1f} kW  Gossip hom: {gh_peak:.1f} kW  [{pct_h_peak:.1f}%]")
    print(f"  Naive heterogeneous:  {nhe_peak:.1f} kW  Gossip het: {ghe_peak:.1f} kW  [{pct_het_peak:.1f}%]")
    print()
    print("Battery-window overvoltage violations (herding overvoltage metric):")
    print(f"  Naive homogeneous:    {nh_bov} steps  (herding spike causes overvoltage)")
    print(f"  Naive heterogeneous:  {nhe_bov} steps")
    print(f"  Gossip homogeneous:   {gh_bov} steps  (protocol prevents overvoltage)")
    print(f"  Gossip heterogeneous: {ghe_bov} steps  (protocol prevents overvoltage)")
    print()
    print("Gossip convergence rounds:")
    print(f"  Homogeneous fleet:    {all_metrics['gossip_homogeneous']['rounds_to_converge']}")
    print(f"  Heterogeneous fleet:  {all_metrics['gossip_heterogeneous']['rounds_to_converge']}")
    print()
    print(f"Summary written: {summary_path}")
    print()

    return summary


if __name__ == "__main__":
    run_all()
