const pptxgen = require("pptxgenjs");

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.author = "GridAI";
pres.title = "GridAI — Anti-Herding Compliance for Distributed Energy Resources";

const BG = "0F1923";
const AMBER = "F4A623";
const WHITE = "FFFFFF";
const STEEL = "B8C8D8";
const DARK_CARD = "162535";
const RED = "E74C3C";
const GREEN = "27AE60";
const FONT = "Calibri";

function bg(slide) {
  slide.background = { color: BG };
}

function titleBar(slide, text) {
  slide.addText(text, {
    x: 0.6, y: 0.25, w: 8.8, h: 0.55,
    fontSize: 26, fontFace: FONT, bold: true, color: STEEL,
    margin: 0,
  });
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.6, y: 0.85, w: 1.2, h: 0.03,
    fill: { color: AMBER },
  });
}

function bigNumber(slide, x, y, number, label) {
  slide.addText(String(number), {
    x, y, w: 3, h: 0.6,
    fontSize: 36, fontFace: FONT, bold: true, color: AMBER,
    margin: 0,
  });
  slide.addText(label, {
    x, y: y + 0.6, w: 3, h: 0.35,
    fontSize: 11, fontFace: FONT, color: STEEL,
    margin: 0,
  });
}

function metricBar(slide, x, y, w, label, value, color) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w, h: 0.04,
    fill: { color: color || AMBER },
  });
  slide.addText(label, {
    x, y: y + 0.08, w, h: 0.25,
    fontSize: 9, fontFace: FONT, color: STEEL, margin: 0,
  });
  slide.addText(String(value), {
    x, y: y + 0.08, w, h: 0.25,
    fontSize: 11, fontFace: FONT, bold: true, color: color || AMBER,
    align: "right", margin: 0,
  });
}

// ============================================================
// SLIDE 1 — Title
// ============================================================
(() => {
  const s = pres.addSlide();
  bg(s);

  s.addImage({
    path: "/Users/mayank/gridai/viz/audit_screenshots/07b_side_by_side_TRUE_peak_step211.png",
    x: 5.2, y: 0, w: 4.8, h: 5.625,
    sizing: { type: "cover", w: 4.8, h: 5.625 },
  });

  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.2, y: 0, w: 4.8, h: 5.625,
    fill: { color: BG, transparency: 50 },
  });

  s.addText("GridAI", {
    x: 0.8, y: 1.0, w: 4.5, h: 0.8,
    fontSize: 48, fontFace: FONT, bold: true, color: WHITE, margin: 0,
  });

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 1.9, w: 0.6, h: 0.04,
    fill: { color: AMBER },
  });

  s.addText("Anti-Herding Compliance for Distributed Energy Resources", {
    x: 0.8, y: 2.15, w: 4.5, h: 0.5,
    fontSize: 18, fontFace: FONT, color: STEEL, margin: 0,
  });

  s.addText("Four agents on Band · Regulated & High-Stakes Workflows", {
    x: 0.8, y: 2.75, w: 4.5, h: 0.4,
    fontSize: 13, fontFace: FONT, color: AMBER, margin: 0,
  });

  s.addText("lablab.ai Band of Agents Hackathon · June 2026", {
    x: 0.8, y: 4.8, w: 4.5, h: 0.35,
    fontSize: 10, fontFace: FONT, color: STEEL, italic: true, margin: 0,
  });
})();

// ============================================================
// SLIDE 2 — The Problem
// ============================================================
(() => {
  const s = pres.addSlide();
  bg(s);
  titleBar(s, "THE PROBLEM");

  s.addText([
    { text: "Australia has 15 GWh of home batteries reading the same price signal.", options: { fontSize: 20, bold: true, color: WHITE, breakLine: true } },
  ], { x: 0.6, y: 1.2, w: 8.8, h: 0.5, fontFace: FONT, margin: 0 });

  s.addText([
    { text: "When they all respond at once, they synchronise.", options: { breakLine: true } },
    { text: "The fleet creates a new evening demand spike instead of smoothing the old one.", options: { breakLine: true } },
    { text: "", options: { breakLine: true, fontSize: 8 } },
    { text: "471 voltage breaches at the network edge.", options: { color: AMBER, bold: true } },
  ], { x: 0.6, y: 1.85, w: 4.5, h: 2.0, fontSize: 14, fontFace: FONT, color: WHITE, margin: 0 });

  // right side visual: simple battery→signal→spike diagram
  const cx = 7.5, cy = 3.0;
  // batteries
  for (let i = 0; i < 3; i++) {
    const bx = 6.0 + i * 0.5;
    s.addShape(pres.shapes.RECTANGLE, { x: bx, y: 2.4, w: 0.35, h: 0.5, fill: { color: AMBER }, rectRadius: 0.05 });
  }
  s.addText("batteries", { x: 6.0, y: 2.95, w: 1.8, h: 0.25, fontSize: 9, fontFace: FONT, color: STEEL, align: "center", margin: 0 });

  // arrow
  s.addShape(pres.shapes.LINE, { x: 7.8, y: 2.65, w: 0.7, h: 0, line: { color: STEEL, width: 1.5 } });
  // arrowhead
  s.addShape(pres.shapes.LINE, { x: 8.4, y: 2.65, w: 0, h: 0, line: { color: STEEL, width: 0 } });
  s.addText("→", { x: 8.25, y: 2.35, w: 0.6, h: 0.6, fontSize: 24, fontFace: FONT, color: STEEL, align: "center", margin: 0 });

  // "same signal" box
  s.addShape(pres.shapes.RECTANGLE, { x: 6.5, y: 1.95, w: 2.0, h: 0.3, fill: { color: DARK_CARD } });
  s.addText("same price signal", { x: 6.5, y: 1.95, w: 2.0, h: 0.3, fontSize: 9, fontFace: FONT, color: WHITE, align: "center", margin: 0 });

  // sync spike
  s.addShape(pres.shapes.RECTANGLE, { x: 8.7, y: 1.8, w: 0.7, h: 1.7, fill: { color: RED, transparency: 60 } });

  s.addText("synchronised\nspike", { x: 8.7, y: 3.55, w: 0.7, h: 0.5, fontSize: 8, fontFace: FONT, color: RED, align: "center", margin: 0 });

  s.addText("This is the herding problem — and it gets worse as VPPs scale.", {
    x: 0.6, y: 4.3, w: 8.8, h: 0.35,
    fontSize: 12, fontFace: FONT, italic: true, color: STEEL, margin: 0,
  });
})();

// ============================================================
// SLIDE 3 — Why It's Hard
// ============================================================
(() => {
  const s = pres.addSlide();
  bg(s);
  titleBar(s, "WHY IT'S HARD");

  s.addText([
    { text: "The problem is second-order: it appears precisely when VPP coordination succeeds.", options: { fontSize: 15, bold: true, color: WHITE, breakLine: true } },
    { text: "Each aggregator's fleet looks fine in isolation. The failure is at the system level.", options: { fontSize: 12, color: STEEL, breakLine: true } },
  ], { x: 0.6, y: 1.2, w: 8.8, h: 0.9, fontFace: FONT, margin: 0 });

  // Two-column table
  const tableX = 0.6, tableY = 2.4, colW = 4.3;
  const headerH = 0.4, rowH = 0.55;

  // "What exists" column
  s.addShape(pres.shapes.RECTANGLE, { x: tableX, y: tableY, w: colW, h: headerH, fill: { color: DARK_CARD } });
  s.addText("WHAT EXISTS", { x: tableX, y: tableY, w: colW, h: headerH, fontSize: 11, fontFace: FONT, bold: true, color: GREEN, align: "center", margin: 0 });

  const exists = [
    "DERMS platforms (EnergyHub, Kraken, AutoGrid) coordinate DERs well",
    "Voltage constraint management is table stakes",
    "Real-time dispatch of storage fleets at scale",
  ];
  exists.forEach((line, i) => {
    s.addShape(pres.shapes.RECTANGLE, { x: tableX, y: tableY + headerH + i * rowH, w: colW, h: rowH, fill: { color: DARK_CARD }, line: { color: "1A2A3C", width: 0.5 } });
    s.addText(line, { x: tableX + 0.15, y: tableY + headerH + i * rowH, w: colW - 0.3, h: rowH, fontSize: 10, fontFace: FONT, color: STEEL, valign: "middle", margin: 0 });
  });

  // "What's missing" column
  const missingX = tableX + colW + 0.2;
  s.addShape(pres.shapes.RECTANGLE, { x: missingX, y: tableY, w: colW, h: headerH, fill: { color: DARK_CARD } });
  s.addText("WHAT'S MISSING", { x: missingX, y: tableY, w: colW, h: headerH, fontSize: 11, fontFace: FONT, bold: true, color: RED, align: "center", margin: 0 });

  const missing = [
    "Anti-herding assurance before dispatch",
    "Cause-attributed breach compliance (pv_export vs battery_herding)",
    "Regulator-ready audit trails that trace decisions to agents",
  ];
  missing.forEach((line, i) => {
    s.addShape(pres.shapes.RECTANGLE, { x: missingX, y: tableY + headerH + i * rowH, w: colW, h: rowH, fill: { color: DARK_CARD }, line: { color: "1A2A3C", width: 0.5 } });
    s.addText(line, { x: missingX + 0.15, y: tableY + headerH + i * rowH, w: colW - 0.3, h: rowH, fontSize: 10, fontFace: FONT, color: WHITE, valign: "middle", margin: 0 });
  });

  s.addText("Commercial DERMS expose coordination. None expose anti-herding compliance as a primary artifact.", {
    x: 0.6, y: 4.6, w: 8.8, h: 0.4,
    fontSize: 12, fontFace: FONT, italic: true, color: STEEL, margin: 0,
  });
})();

// ============================================================
// SLIDE 4 — The Mechanism Insight
// ============================================================
(() => {
  const s = pres.addSlide();
  bg(s);
  titleBar(s, "THE MECHANISM INSIGHT");

  s.addText([
    { text: "Desynchronisation is not just a protocol problem.", options: { fontSize: 15, bold: true, color: WHITE, breakLine: true } },
    { text: "It depends on fleet-level value heterogeneity. The market design matters as much as the protocol.", options: { fontSize: 12, color: STEEL, breakLine: true } },
  ], { x: 0.6, y: 1.2, w: 8.8, h: 0.9, fontFace: FONT, margin: 0 });

  // Three card layout at top
  const cardW = 2.7, cardH = 1.6, cardY = 2.5, gap = 0.25;
  const cards = [
    { label: "NAIVE", value: "1.000", sub: "60/60 homes\nsimultaneous", color: RED },
    { label: "GOSSIP\nHOMOGENEOUS", value: "0.367", sub: "22/60 homes\nidentical fleet", color: AMBER },
    { label: "GOSSIP\nHETEROGENEOUS", value: "0.167", sub: "10/60 homes\nrealistic fleet", color: GREEN },
  ];

  cards.forEach((card, i) => {
    const cx = 0.6 + i * (cardW + gap);
    s.addShape(pres.shapes.RECTANGLE, { x: cx, y: cardY, w: cardW, h: cardH, fill: { color: DARK_CARD }, rectRadius: 0.08 });
    // color accent top
    s.addShape(pres.shapes.RECTANGLE, { x: cx, y: cardY, w: cardW, h: 0.04, fill: { color: card.color } });
    s.addText(card.label, { x: cx, y: cardY + 0.15, w: cardW, h: 0.4, fontSize: 10, fontFace: FONT, color: STEEL, align: "center", margin: 0 });
    s.addText(card.value, { x: cx, y: cardY + 0.55, w: cardW, h: 0.5, fontSize: 34, fontFace: FONT, bold: true, color: card.color, align: "center", margin: 0 });
    s.addText(card.sub, { x: cx, y: cardY + 1.05, w: cardW, h: 0.4, fontSize: 9, fontFace: FONT, color: STEEL, align: "center", margin: 0 });
  });

  s.addText("Heterogeneous fleet synchrony is 55% lower than homogeneous. The market incentives shape the outcome.", {
    x: 0.6, y: 4.4, w: 8.8, h: 0.35,
    fontSize: 12, fontFace: FONT, italic: true, color: STEEL, margin: 0,
  });

  // also embed the threeway contrast image bottom-right
  s.addImage({
    path: "/Users/mayank/gridai/viz/audit_screenshots/08_threeway_contrast.png",
    x: 8.15, y: 4.65, w: 1.65, h: 0.8,
  });
})();

// ============================================================
// SLIDE 5 — The Solution
// ============================================================
(() => {
  const s = pres.addSlide();
  bg(s);
  titleBar(s, "THE SOLUTION");

  // Left text column
  s.addText("GridAI: gossip-based decentralised protocol with a Band-native compliance layer.", {
    x: 0.6, y: 1.2, w: 5.0, h: 0.55,
    fontSize: 15, fontFace: FONT, bold: true, color: WHITE, margin: 0,
  });

  s.addText([
    { text: "Each battery negotiates with local neighbours only using SOC and owner preference.", options: { bullet: true, breakLine: true } },
    { text: "No central controller. Converges in 1 round.", options: { bullet: true, breakLine: true } },
    { text: "", options: { breakLine: true, fontSize: 6 } },
    { text: "Battery-herding overvoltage:  ", options: { breakLine: false, color: WHITE } },
    { text: "471 → 0", options: { breakLine: true, color: AMBER, bold: true, fontSize: 16 } },
    { text: "Honest tradeoff: mild far-feeder undervoltage (distinct from herding)", options: { color: STEEL, italic: true } },
  ], { x: 0.6, y: 1.9, w: 5.0, h: 2.2, fontSize: 12, fontFace: FONT, color: WHITE, margin: 0 });

  // Right side: HERO screenshot
  s.addImage({
    path: "/Users/mayank/gridai/viz/audit_screenshots/03_naive_peak_HERO.png",
    x: 5.9, y: 1.2, w: 3.7, h: 3.7,
    sizing: { type: "contain", w: 3.7, h: 3.7 },
  });
})();

// ============================================================
// SLIDE 6 — The Band Architecture
// ============================================================
(() => {
  const s = pres.addSlide();
  bg(s);
  titleBar(s, "THE BAND ARCHITECTURE");

  s.addText("Four agents coordinating through Band as the actual collaboration layer.", {
    x: 0.6, y: 1.15, w: 8.8, h: 0.4,
    fontSize: 14, fontFace: FONT, color: WHITE, margin: 0,
  });

  const agents = [
    { id: "FORECASTER", role: "Identifies risk windows, hands off to Coordinator", color: "4A90D9" },
    { id: "COORDINATOR", role: "Runs gossip protocol, hands dispatch plan to Compliance", color: "50B87D" },
    { id: "COMPLIANCE", role: "Checks AS IEC 60038:2022, attributes breach cause, escalates", color: "F4A623" },
    { id: "OPERATOR", role: "Human-in-the-loop, receives escalation, records decision", color: "E74C3C" },
  ];

  const boxW = 1.9, boxH = 1.4, startX = 0.6, startY = 1.8, boxGap = 0.35;

  agents.forEach((a, i) => {
    const ax = startX + i * (boxW + boxGap);

    s.addShape(pres.shapes.RECTANGLE, {
      x: ax, y: startY, w: boxW, h: boxH,
      fill: { color: DARK_CARD },
    });

    // color accent top bar
    s.addShape(pres.shapes.RECTANGLE, {
      x: ax, y: startY, w: boxW, h: 0.04,
      fill: { color: a.color },
    });

    s.addText(a.id, {
      x: ax, y: startY + 0.12, w: boxW, h: 0.35,
      fontSize: 11, fontFace: FONT, bold: true, color: a.color, align: "center", margin: 0,
    });

    s.addText(a.role, {
      x: ax + 0.1, y: startY + 0.5, w: boxW - 0.2, h: 0.8,
      fontSize: 9, fontFace: FONT, color: STEEL, margin: 0,
    });

    // arrow between boxes
    if (i < agents.length - 1) {
      const arrowX = ax + boxW;
      s.addText("→", {
        x: arrowX + 0.02, y: startY + 0.3, w: boxGap - 0.04, h: 0.4,
        fontSize: 20, fontFace: FONT, color: AMBER, align: "center", margin: 0,
      });
    }
  });

  // Band layer below
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.6, y: 3.6, w: 8.8, h: 0.35,
    fill: { color: DARK_CARD },
  });
  s.addText("BAND: shared room  ·  @mention routing  ·  append-only audit log  ·  identity & handoff", {
    x: 0.6, y: 3.6, w: 8.8, h: 0.35,
    fontSize: 10, fontFace: FONT, color: AMBER, align: "center", margin: 0,
  });

  // Every handoff is traceable
  s.addShape(pres.shapes.RECTANGLE, {
    x: 1.5, y: 4.2, w: 7.0, h: 0.45,
    fill: { color: DARK_CARD },
  });
  s.addText("Every handoff is traceable. Removing any agent breaks the chain (verified).", {
    x: 1.5, y: 4.2, w: 7.0, h: 0.45,
    fontSize: 11, fontFace: FONT, color: GREEN, align: "center", margin: 0,
  });

  // Agent identity line
  s.addText("Band agents:  @s4142972/gridai-forecaster  ·  coordinator  ·  compliance  ·  operator", {
    x: 0.6, y: 4.95, w: 8.8, h: 0.35,
    fontSize: 9, fontFace: FONT, color: STEEL, italic: true, align: "center", margin: 0,
  });
})();

// ============================================================
// SLIDE 7 — The Evidence
// ============================================================
(() => {
  const s = pres.addSlide();
  bg(s);
  titleBar(s, "THE EVIDENCE");

  // Clean table
  const tx = 0.7, ty = 1.3, col1W = 4.0, col2W = 2.3, col3W = 2.3;
  const theight = 0.38;

  const rows = [
    { hdr: false, cells: [
      { text: "Metric", options: { bold: true, color: STEEL } },
      { text: "Naive", options: { bold: true, color: STEEL } },
      { text: "GridAI", options: { bold: true, color: STEEL } },
    ]},
    { cells: [
      { text: "Battery-herding overvoltage", options: { color: WHITE } },
      { text: "471 steps", options: { color: RED, bold: true } },
      { text: "0 (eliminated)", options: { color: GREEN, bold: true } },
    ]},
    { cells: [
      { text: "Synchrony", options: { color: WHITE } },
      { text: "1.000", options: { color: RED } },
      { text: "0.167", options: { color: GREEN } },
    ]},
    { cells: [
      { text: "Max simultaneous discharge", options: { color: WHITE } },
      { text: "60/60", options: { color: RED } },
      { text: "10/60", options: { color: GREEN } },
    ]},
    { cells: [
      { text: "Convergence", options: { color: WHITE } },
      { text: "—", options: { color: STEEL } },
      { text: "1 round", options: { color: WHITE } },
    ]},
    { cells: [
      { text: "Peak demand reduction", options: { color: WHITE } },
      { text: "—", options: { color: STEEL } },
      { text: "−0.9% (honest)", options: { color: STEEL } },
    ]},
  ];

  rows.forEach((row, ri) => {
    const rowY = ty + ri * (theight + 0.02);
    [col1W, col2W, col3W].forEach((cw, ci) => {
      const cellX = tx + ci * (ci === 0 ? 0 : col1W + 0.05);
      if (ri === 0) {
        s.addShape(pres.shapes.RECTANGLE, { x: cellX, y: rowY, w: cw, h: theight, fill: { color: DARK_CARD } });
      } else if (ri % 2 === 0) {
        s.addShape(pres.shapes.RECTANGLE, { x: cellX, y: rowY, w: cw, h: theight, fill: { color: "122030" } });
      }
      s.addText(row.cells[ci].text, {
        x: cellX + 0.15, y: rowY, w: cw - 0.3, h: theight,
        fontSize: 11, fontFace: FONT, color: row.cells[ci].options && row.cells[ci].options.color || WHITE,
        bold: row.cells[ci].options && row.cells[ci].options.bold,
        valign: "middle", margin: 0,
      });
    });
  });

  // Bottom context
  s.addText([
    { text: "89 tests passing", options: { bold: true, color: AMBER } },
    { text: "  ·  including provenance coherence & agent interdependence", options: { color: STEEL } },
  ], { x: 0.7, y: 3.8, w: 8.6, h: 0.3, fontSize: 11, fontFace: FONT, margin: 0 });

  s.addText("AEMO 2012 Victorian data, 17,568 rows. Representative day: 2012-01-24 (highest evening peak, 8,864 MW).", {
    x: 0.7, y: 4.2, w: 8.6, h: 0.3,
    fontSize: 10, fontFace: FONT, color: STEEL, italic: true, margin: 0,
  });

  // Side-by-side screenshot bottom-right
  s.addImage({
    path: "/Users/mayank/gridai/viz/audit_screenshots/07_side_by_side_peak.png",
    x: 5.8, y: 4.55, w: 4.0, h: 0.9,
  });
})();

// ============================================================
// SLIDE 8 — The Compliance Artifact
// ============================================================
(() => {
  const s = pres.addSlide();
  bg(s);
  titleBar(s, "THE COMPLIANCE ARTIFACT");

  // Left: screenshot
  s.addImage({
    path: "/Users/mayank/gridai/viz/audit_screenshots/06_gossip_compliance_card.png",
    x: 0.6, y: 1.2, w: 5.0, h: 3.6,
    sizing: { type: "contain", w: 5.0, h: 3.6 },
  });

  // Right: text
  s.addText("The Band audit trail is the regulated-workflows deliverable.", {
    x: 5.9, y: 1.2, w: 3.8, h: 0.5,
    fontSize: 15, fontFace: FONT, bold: true, color: WHITE, margin: 0,
  });

  s.addText("Every compliance decision is traceable to:", {
    x: 5.9, y: 1.8, w: 3.8, h: 0.3,
    fontSize: 11, fontFace: FONT, color: STEEL, margin: 0,
  });

  const traceItems = [
    "The agent that made it",
    "The data it saw",
    "The moment it happened",
    "The cause category (pv_export vs battery_herding)",
  ];
  traceItems.forEach((item, i) => {
    s.addText(item, {
      x: 6.1, y: 2.2 + i * 0.32, w: 3.5, h: 0.28,
      fontSize: 11, fontFace: FONT, color: WHITE, bullet: true, margin: 0,
    });
  });

  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.9, y: 3.8, w: 3.8, h: 0.04,
    fill: { color: AMBER },
  });

  s.addText("This is what a network operator or regulator can actually use.", {
    x: 5.9, y: 4.0, w: 3.8, h: 0.5,
    fontSize: 12, fontFace: FONT, italic: true, color: STEEL, margin: 0,
  });

  // Standards ref at bottom
  s.addText("AS IEC 60038:2022  ·  CSIP-AUS compliant  ·  8-step Band audit trail per scenario", {
    x: 0.6, y: 5.0, w: 8.8, h: 0.3,
    fontSize: 9, fontFace: FONT, color: STEEL, align: "center", margin: 0,
  });
})();

// ============================================================
// SLIDE 9 — Wedge Positioning
// ============================================================
(() => {
  const s = pres.addSlide();
  bg(s);
  titleBar(s, "WEDGE POSITIONING");

  s.addText([
    { text: "GridAI is not a replacement for DERMS or VPP platforms.", options: { fontSize: 15, bold: true, color: WHITE, breakLine: true } },
    { text: "It is an assurance and attribution layer that sits between fleets and the network.", options: { fontSize: 13, color: STEEL, breakLine: true } },
  ], { x: 0.6, y: 1.2, w: 8.8, h: 0.75, fontFace: FONT, margin: 0 });

  // Three-layer diagram
  const layerW = 3.8, layerH = 0.5, lx = 3.1, lgap = 0.12;
  const layers = [
    { label: "VPP / DERMS PLATFORMS", sub: "EnergyHub · Kraken · AutoGrid · Tesla VPP", y: 2.3, color: "4A90D9" },
    { label: "GRIDAI  ←  assurance & attribution", sub: "Anti-herding + cause-attributed compliance", y: 2.95, color: AMBER },
    { label: "DISTRIBUTION NETWORK / REGULATOR", sub: "AEMO · SA Power Networks · AER", y: 3.6, color: "27AE60" },
  ];

  layers.forEach((l) => {
    s.addShape(pres.shapes.RECTANGLE, {
      x: lx, y: l.y, w: layerW, h: layerH,
      fill: { color: DARK_CARD },
    });
    // left accent
    s.addShape(pres.shapes.RECTANGLE, {
      x: lx, y: l.y, w: 0.05, h: layerH,
      fill: { color: l.color },
    });
    s.addText(l.label, {
      x: lx + 0.2, y: l.y + 0.04, w: layerW - 0.3, h: 0.25,
      fontSize: 11, fontFace: FONT, bold: true, color: l.color, margin: 0,
    });
    s.addText(l.sub, {
      x: lx + 0.2, y: l.y + 0.28, w: layerW - 0.3, h: 0.2,
      fontSize: 8, fontFace: FONT, color: STEEL, margin: 0,
    });
  });

  // arrows between layers
  s.addText("↓", { x: lx + layerW / 2 - 0.15, y: 2.82, w: 0.3, h: 0.2, fontSize: 14, fontFace: FONT, color: STEEL, align: "center", margin: 0 });
  s.addText("↓", { x: lx + layerW / 2 - 0.15, y: 3.47, w: 0.3, h: 0.2, fontSize: 14, fontFace: FONT, color: STEEL, align: "center", margin: 0 });

  // Next steps
  s.addText("NEXT STEPS", {
    x: 0.6, y: 4.4, w: 2, h: 0.3,
    fontSize: 10, fontFace: FONT, bold: true, color: STEEL, margin: 0,
  });

  s.addText([
    { text: "OpenDSS validation", options: { bullet: true, breakLine: true } },
    { text: "Multi-aggregator scenarios", options: { bullet: true, breakLine: true } },
    { text: "CSIP-AUS live interface", options: { bullet: true, breakLine: true } },
    { text: "RAISE Summit Paris, July 2026", options: { bullet: true, color: AMBER } },
  ], { x: 0.6, y: 4.7, w: 8.8, h: 0.8, fontSize: 10, fontFace: FONT, color: STEEL, margin: 0 });
})();

// ============================================================
// SLIDE 10 — Links and Repo
// ============================================================
(() => {
  const s = pres.addSlide();
  bg(s);

  s.addText("Links & Repository", {
    x: 0.6, y: 0.8, w: 8.8, h: 0.55,
    fontSize: 28, fontFace: FONT, bold: true, color: WHITE, margin: 0,
  });

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.6, y: 1.4, w: 1.2, h: 0.03,
    fill: { color: AMBER },
  });

  const links = [
    { label: "PUBLIC DEMO", value: "https://dexflex66.github.io/gridai/" },
    { label: "GITHUB", value: "https://github.com/dexflex66/gridai" },
    { label: "BAND AGENTS", value: "@s4142972/gridai-forecaster · coordinator · compliance · operator" },
  ];

  links.forEach((l, i) => {
    const ly = 1.8 + i * 0.55;
    s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: ly, w: 4.5, h: 0.45, fill: { color: DARK_CARD } });
    s.addText(l.label, { x: 0.8, y: ly, w: 1.5, h: 0.45, fontSize: 10, fontFace: FONT, bold: true, color: AMBER, valign: "middle", margin: 0 });
    s.addText(l.value, { x: 2.3, y: ly, w: 2.7, h: 0.45, fontSize: 11, fontFace: FONT, color: WHITE, valign: "middle", margin: 0 });
  });

  const metaBoxY = 3.6;
  s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: metaBoxY, w: 8.8, h: 1.2, fill: { color: DARK_CARD } });
  s.addText([
    { text: "89 tests", options: { bold: true, color: AMBER, breakLine: false } },
    { text: "  ·  82 original + 7 causal-link & regression additions", options: { color: STEEL, breakLine: true } },
    { text: "", options: { breakLine: true, fontSize: 6 } },
    { text: "Built with:  ", options: { breakLine: false, color: STEEL } },
    { text: "Python  ·  Band SDK  ·  AEMO open data  ·  AS IEC 60038:2022", options: { color: WHITE, breakLine: true } },
    { text: "Homogeneous gossip 0.367  →  Heterogeneous gossip 0.167  →  Naive 1.000 synchrony baseline", options: { color: STEEL, breakLine: true, italic: true, fontSize: 10 } },
  ], { x: 0.9, y: metaBoxY + 0.15, w: 8.2, h: 0.9, fontSize: 11, fontFace: FONT, margin: 0 });

  s.addText([
    { text: "lablab.ai Band of Agents Hackathon  ·  Track: Regulated & High-Stakes Workflows  ·  June 2026", options: {} },
  ], { x: 0.6, y: 5.1, w: 8.8, h: 0.3, fontSize: 9, fontFace: FONT, color: STEEL, align: "center", margin: 0 });
})();

// ============================================================
// SAVE
// ============================================================
const outPath = "/Users/mayank/gridai/submission/gridai_lablab_band_of_agents_2026/assets/gridai_pitch_deck.pptx";
pres.writeFile({ fileName: outPath })
  .then(() => console.log("DONE: " + outPath))
  .catch(err => console.error("ERROR:", err));