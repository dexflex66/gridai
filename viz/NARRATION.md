# GridAI — 90-Second Demo Narration

Timed to `viz/gridai_demo.html`. Designed as a **single take** driven by the scrubber +
the view toggle (Side-by-side / Naive only / Gossip only). Demo runs at 5-min steps
(288 steps = 24h); `step N` = `N × 5 min`. The scrubber input is `#stepSlider` (0–287);
"Jump to Evening Peak" goes to step 204 (17:00). The herding breach peaks around step 211 (17:35).

All numbers below are the verified AEMO-driven results. Keep sentences short; pauses are baked into the timings.

| Time | Demo action (set this) | Spoken line |
|------|------------------------|-------------|
| **0–10s** | **Side-by-side**, scrubber at **step 144 (12:00)**. Calm grids. | "Australia has fifteen gigawatt-hours of home batteries, and it's growing fast — all reacting to one electricity price signal." |
| **10–25s** | Switch to **Naive only**, scrub to **step 211 (17:35)**. Hold ~2s on the full amber flash + red breaches + the demand rebound spike. | "When they all follow that signal, they synchronise. The fleet creates a *new* evening peak instead of smoothing the old one. Four hundred seventy-one voltage breaches at the network edge. This is the herding problem." |
| **25–40s** | Stay at step 211. Point to the **Naive BAND Audit Trail** card — the blue audit entry + the red ESCALATE. | "Our Compliance agent catches it live and escalates. Full Band audit trail — traceable to the agent, the interval, and the cause: battery herding." |
| **40–60s** | Toggle to **Gossip only**, hold at **step 211**. Let the staggered ripple read. | "GridAI is a gossip-based decentralised protocol. Each battery negotiates with local neighbours only — using its state of charge and the owner's preference. No central controller. It converges in one to two rounds, on the inverter hardware that already exists." |
| **60–75s** | Stay on Gossip. Point to **APPROVED** + the voltage panel (no red), then **pause on the purple undervoltage annotation**. | "Herding eliminated — four hundred seventy-one breaches to zero. The Compliance agent approves. And honestly: desynchronising surfaces a *second* effect at the far edge of the feeder — undervoltage. It's distinct from herding, it's traceable, and it's the next problem to solve." |
| **75–90s** | Scroll to the **3-Way Heterogeneity Contrast** panel. | "Here's why it works. A realistic, varied fleet desynchronises hard — synchrony one-point-zero down to zero-point-one-seven. An identical fleet barely moves. The mechanism is diversity in what each battery wants, not the negotiation itself. The protocol works because the fleet is real." |

## One-take recording checklist
1. Open `viz/gridai_demo.html` (double-click — it's self-contained, no server needed).
2. Set view **Side-by-side**, scrubber to **144**. Begin speaking.
3. **Naive only**, scrubber to **211**. (Tip: "Jump to Evening Peak" lands at 204; nudge to 211.)
4. Keep at 211; the camera moves to the naive audit card (no demo change needed).
5. **Gossip only** (still step 211).
6. Pan down to the gossip APPROVED card + undervoltage annotation.
7. Scroll to the 3-way panel to close.

## Honest-framing guardrails (do not drift in the recording)
- Lead with **voltage-violation elimination** (overvoltage herding 471 → 0) and **synchrony collapse** (1.000 → 0.167). These are the headline.
- **Never** call peak shaving the win — it is secondary and modest (−0.9% realistic to +11.6% stress case). Don't say it on camera unless asked.
- Name the **undervoltage** tradeoff out loud — it's real (435 battery-herding undervolt events) and naming it is what earns trust.
