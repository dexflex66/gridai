/**
 * GridAI demo video recording via Playwright built-in video capture.
 * Records ~96s visual track for Mayank to lay narration over.
 *
 * Output: submission/gridai_lablab_band_of_agents_2026/video/gridai_demo_v3.webm
 * Target viewport: 1920x1080 native (no letterbox needed)
 *
 * Usage:
 *   node /Users/mayank/gridai/viz/record_demo.js
 */
const path = require('path');
const fs = require('fs');
const { chromium } = require('/tmp/gridai-audit/node_modules/playwright');

const URL = 'https://dexflex66.github.io/gridai/';
const OUT = path.join(__dirname, '..', 'submission', 'gridai_lablab_band_of_agents_2026', 'video');
const VIEWPORT = { width: 1920, height: 1080 };

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  fs.mkdirSync(OUT, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: VIEWPORT,
    recordVideo: {
      dir: OUT,
      size: VIEWPORT,
    },
  });
  const page = await context.newPage();

  const consoleErrors = [];
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });

  await page.goto(URL, { waitUntil: 'networkidle', timeout: 45000 });
  await sleep(3000);
  await page.evaluate(() => { document.body.style.opacity = '0'; });
  await sleep(100);
  await page.evaluate(() => { document.body.style.opacity = '1'; });

  await page.evaluate(() => { setView('side'); jumpTo(144); });
  await sleep(1000);

  // ── [0–10s] Side-by-side, step 144 (12:00) · Calm grids ──
  await sleep(9000);

  // ── [10–25s] Naive only, step 211 (17:35) · Full amber flash + breaches ──
  await page.evaluate(() => { setView('naive'); jumpTo(211); });
  await sleep(1000);
  await sleep(14000);

  // ── [25–40s] Naive only, step 211 · Scroll to ESCALATE audit card ──
  await page.evaluate(() => {
    const el = document.querySelector('.bottom-row');
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  await sleep(2000);
  await sleep(13000);

  // ── [40–60s] Gossip only, step 211 · Staggered ripple ──
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
  await sleep(1500);
  await page.evaluate(() => { setView('gossip'); jumpTo(211); });
  await sleep(1000);
  await sleep(17500);

  // ── [60–75s] Gossip only, step 211 · Scroll to APPROVED + voltage panel (no red) ──
  await page.evaluate(() => {
    const el = document.querySelector('.bottom-row');
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  await sleep(2000);
  await sleep(13000);

  // ── [75–90s] Side-by-side · 3-way heterogeneity contrast panel ──
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
  await sleep(1500);
  await page.evaluate(() => { setView('side'); jumpTo(211); });
  await sleep(1000);
  await sleep(2500);
  await page.evaluate(() => {
    const el = document.querySelectorAll('.threeway-panel, .bottom-row')[1] ||
               document.querySelector('.threeway-panel');
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  await sleep(2000);
  await sleep(7500);

  // ── [90–96s] Title card · scroll to bottom ──
  await page.evaluate(() => {
    const el = document.getElementById('titleCard');
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });
  await sleep(2000);
  await sleep(4000);

  await context.close();
  await browser.close();

  await sleep(1000);

  const files = fs.readdirSync(OUT).filter((f) => f.endsWith('.webm'));
  if (files.length === 0) throw new Error('No .webm video file produced');
  const videoPath = path.join(OUT, files[0]);
  const destPath = path.join(OUT, 'gridai_demo_v3.webm');
  if (videoPath !== destPath) {
    fs.renameSync(videoPath, destPath);
  }

  const stat = fs.statSync(destPath);
  const sizeMB = (stat.size / 1024 / 1024).toFixed(2);

  console.log(`\n=== RECORDING COMPLETE ===`);
  console.log(`Video:  ${destPath}`);
  console.log(`Size:   ${sizeMB} MB`);
  console.log(`Errors: ${consoleErrors.length}`);
  if (consoleErrors.length) consoleErrors.forEach((e) => console.log(`  ! ${e}`));
  console.log(`===========================\n`);
}

main().catch((e) => { console.error('RECORDING FAILED:', e); process.exit(1); });