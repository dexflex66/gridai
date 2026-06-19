# GridAI — lablab.ai Submission

Submission package for the **Band of Agents Hackathon** · Track: **Regulated and High-Stakes Workflows**.
Fields below map to the lablab.ai submission form. All numbers are exactly as verified by the
simulation + test suite; nothing is inflated.

---

## Submission title (≤ 50 chars)
`GridAI — Decentralised DER Coordination`

## Short description (≤ 255 chars)
Home-battery fleets that follow one price signal synchronise and create a new evening peak and voltage breaches. GridAI is a four-agent protocol on Band where batteries desynchronise via local gossip — herding overvoltage breaches 471→0, with a full compliance audit trail.

## Main track
Regulated and High-Stakes Workflows

## Technologies
Band SDK (multi-agent collaboration layer) · Python · NumPy · gossip-based decentralised coordination ·
multi-agent systems · HTML5 Canvas (standalone visualisation) · AEMO 2012 Victorian NEM data ·
pytest (89 tests) · AS IEC 60038:2022 / CSIP-AUS context

---

## Long description

### Problem
Australia has roughly **15 GWh of home batteries and the number is climbing fast**. They mostly see the
same thing: the National Electricity Market price signal. When price drops in the evening they all
discharge at once. Following one shared signal makes a fleet **synchronise** — and a synchronised fleet
builds a *new* evening demand peak instead of smoothing the old one, while pushing voltage outside legal
limits at the edge of the distribution network. The grid already spills **about 7.2 TWh a year to
curtailment** as a crude workaround. This failure mode gets *worse* as virtual-power-plant deployment
scales, because it appears precisely when fleets start coordinating against shared signals. It is a
second-order problem that today's market design walks straight into.

### Solution
GridAI is a **decentralised multi-agent coordination protocol**. Four agents — **Forecaster,
Coordinator, Compliance, Operator** — collaborate through **Band as the actual collaboration layer**,
not a notification wrapper. The Coordinator runs a **gossip protocol**: each battery negotiates its
dispatch slot with a handful of local neighbours using its state of charge and the owner's
willingness-to-discharge. The fleet desynchronises through **heterogeneity** — diversity in what each
battery wants — not through symmetric negotiation. The **Compliance agent** reviews every plan against
**AS IEC 60038:2022** voltage limits, flags **battery-herding** breaches (kept distinct from midday
PV-export breaches), and escalates to a human **Operator** with a full Band-native audit trail.
Convergence takes **1–2 rounds**, runs on existing inverter hardware, and fits the **CSIP-AUS** standard
already mandated in Australia.

### How Band was used
All four agents are registered as **remote agents on Band**, each with its own API key and identity.
They coordinate through a **shared room with @mention routing**: the Forecaster hands a structured
risk-window to the Coordinator, the Coordinator hands the dispatch plan and voltage trajectory to
Compliance, Compliance escalates or approves to the Operator. The room is the backbone — each handoff is
an @mention in a permanent thread, so the full chain is recoverable without external logging. Band provides
**identity, structured context handoff, and a native unified audit trail** across the chain. **Removing
any one agent breaks the workflow — verified by tests.** The audit trail is the regulatory artifact: a
judge can trace any compliance decision back to the planning agent, the data it saw, and the human's
response. Verified live against `app.band.ai`; the four-agent chain reproduces the mock results
field-for-field.

### Evidence (verified, honest)
- **Headline — voltage violations eliminated:** battery-herding **overvoltage 471 → 0**. This counts 471
  discrete node×step overvoltage events when 60 batteries follow the shared price signal naively — each
  event is one home pushing voltage above the AS 60038 limit at one timestep (naive vs gossip, AEMO evening
  peak). Per-step: 14 overvoltage steps → 0.
- **Headline — synchrony collapse:** max simultaneous discharge **1.000 → 0.167** (60/60 homes → 10/60).
- **Convergence:** gossip converges in **1–2 rounds** (heterogeneous 1, homogeneous 2).
- **Three-way heterogeneity contrast** (proves the mechanism): synchrony — naive 1.000, gossip-homogeneous
  0.367, gossip-heterogeneous 0.167. The realistic varied fleet desynchronises *harder* than the identical
  control fleet, so the effect comes from fleet diversity, not the negotiation alone.
- **Peak aggregate demand reduction — secondary and modest, reported honestly:** −0.9% in the realistic
  heterogeneous case (gossip slightly *raised* peak) up to +11.6% in a homogeneous stress case. We do not
  lead with this.
- **Residual far-feeder undervoltage** (435 battery-herding undervolt events) is noted honestly as a
  second-order phenomenon the protocol *surfaces* — distinct from herding, traceable, and the next problem.
- **89 automated tests** covering provenance coherence, PV-vs-battery cause separation, causal-link steering, and agent interdependence.

### What we don't claim
We do **not** claim peak shaving as the primary outcome. We do **not** claim to replace dynamic operating
envelopes — we are complementary to them. We do **not** claim effectiveness in a flat-rate VPP contract
regime where value functions are homogenised at the contract layer; the protocol's benefit scales with
whatever heterogeneity the market design permits. We do **not** claim production readiness.

### What's next
The residual far-feeder undervoltage is the next tractable problem and points directly at integration with
**dynamic operating envelopes**. Beyond that: larger-fleet scale tests, adversarial-device robustness, and
pilot conversations with **Amber Electric** and **SA Power Networks** given the market-design fit. Next
showing: **RAISE Summit, Paris, July 4–5**.

---

## Required deliverables (lablab)
- **Working prototype (URL):** https://dexflex66.github.io/gridai/ — single self-contained file, no server,
  no build; runs offline in any browser. Hosted on GitHub Pages.
- **Pitch video (≤ 5 min, MP4):** `final/gridai_submission_video_FINAL.mp4` — 90s, 1920×1080, 28.7 MB, −17.9 LUFS. Recorded per `viz/NARRATION.md`.
- **Slide deck (PDF):** `assets/gridai_pitch_deck.pdf` — 10 slides, 410 KB.
- **Public GitHub repo:** this repository.
- **Cover image (16:9):** `viz/screenshots/03_naive_synchronised_flash.png` (the synchronised amber flash)
  or `02_evening_peak_sidebyside.png`.
