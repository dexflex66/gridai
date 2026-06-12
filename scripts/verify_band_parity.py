"""
Live Band parity check (manual / not part of pytest).

Runs the full four-agent chain for the naive and gossip AEMO scenarios over the
REAL Band platform (USE_REAL_BAND=true) and diffs each resulting compliance
decision record against the MockBand record committed in outputs/. Writes
outputs/band_parity_report.md.

Run:  python3 scripts/verify_band_parity.py
Requires .env with the four BAND_*_API_KEY values.
"""

import json
import os
import sys
import time

from dotenv import load_dotenv

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(HERE, ".env"))
os.environ["USE_REAL_BAND"] = "true"
sys.path.insert(0, HERE)

from agents.band_interface import get_band
from agents.forecaster import ForecasterAgent
from agents.coordinator import CoordinatorAgent
from agents.compliance import ComplianceAgent
from agents.grid_operator import OperatorAgent
from sim.simulator import run_scenario
from sim.aemo import load_aemo_profile

COMPARE_FIELDS = [
    "scenario_name", "strategy", "coordinator_synchrony_ratio",
    "coordinator_rounds_to_converge", "herding_overvolt_event_count",
    "pv_export_event_count", "pv_export_flagged_as_protocol_failure",
    "compliance_decision",
]

SCENARIOS = [
    ("naive_homogeneous",   "naive",  False, "outputs/compliance_decision_naive_aemo.json"),
    ("gossip_heterogeneous", "gossip", True,  "outputs/compliance_decision_gossip_aemo.json"),
]


def run_live(name, strategy, het, aemo):
    res = run_scenario(strategy=strategy, heterogeneous=het, n_homes=60,
                       rng_seed=42, load_source="aemo", aemo_profile=aemo)
    band = get_band()
    f = ForecasterAgent(band); c = CoordinatorAgent(band)
    cp = ComplianceAgent(band); o = OperatorAgent(band)
    t0 = time.time()
    f.run(res, scenario_name=name, load_source="aemo")
    c.process_pending(); cp.process_pending(); o.process_pending()
    elapsed = time.time() - t0
    return band, cp.decision_records[-1], o.decisions[-1], elapsed


def main():
    aemo, _ = load_aemo_profile()
    lines = ["# GridAI — Real Band Parity Report", ""]
    lines.append("Full four-agent chain run over the REAL Band platform "
                 "(`https://app.band.ai`), one shared room per scenario, compared "
                 "field-by-field against the committed MockBand records.")
    lines.append("")
    all_match = True

    for name, strategy, het, mock_path in SCENARIOS:
        band, live, op, elapsed = run_live(name, strategy, het, aemo)
        mock = json.load(open(os.path.join(HERE, mock_path)))
        lines.append(f"## {name} ({strategy})")
        lines.append("")
        lines.append(f"- Band room: `{band.room_id}`  ·  chain completed in {elapsed:.1f}s")
        lines.append(f"- Operator decision: **{op['operator_decision']}**")
        lines.append("")
        lines.append("| field | mock | real Band | match |")
        lines.append("|---|---|---|---|")
        for fld in COMPARE_FIELDS:
            mv, lv = mock.get(fld), live.get(fld)
            ok = (mv == lv)
            all_match = all_match and ok
            lines.append(f"| {fld} | `{mv}` | `{lv}` | {'✓' if ok else '✗ MISMATCH'} |")
        lines.append("")
        lines.append("Band native trail (Coordinator's view; @mention isolation means "
                     "each agent sees only messages it sent-to or was-mentioned-in):")
        lines.append("")
        for e in band.native_trail():
            lines.append(f"- `{e['sender_name']}` → {e['recipient']} : {e['message_type']}")
        lines.append("")
        print(f"{name}: {'PARITY OK' if all([mock.get(f)==live.get(f) for f in COMPARE_FIELDS]) else 'MISMATCH'} ({elapsed:.1f}s)")

    verdict = "ALL FIELDS MATCH — real Band run is identical to the mock." if all_match \
        else "MISMATCH DETECTED — see table above."
    lines.append(f"## Verdict\n\n{verdict}")
    out = os.path.join(HERE, "outputs/band_parity_report.md")
    with open(out, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("VERDICT:", verdict)
    print("wrote", out)


if __name__ == "__main__":
    main()
