const path = require('path');
const fs = require('fs');
const { chromium } = require('/tmp/node_modules/playwright');
const { execSync } = require('child_process');

const VIEWPORT = { width: 1920, height: 1080 };
const OUT = path.join(__dirname, '..', 'submission', 'gridai_lablab_band_of_agents_2026', 'video');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function pause(page) {
  await page.evaluate(() => { if (typeof playing !== 'undefined' && playing) togglePlay(); });
}

async function play(page) {
  await page.evaluate(() => { if (typeof playing !== 'undefined' && !playing) togglePlay(); });
}

async function setViewAndStep(page, view, step) {
  await pause(page);
  await page.evaluate((v) => setView(v), view);
  await page.evaluate((s) => jumpTo(s), step);
  await play(page);
}

async function getTime(page) {
  return await page.evaluate(() => document.getElementById('timeDisplay').textContent.trim());
}

async function getStep(page) {
  return await page.evaluate(() => parseInt(document.getElementById('stepSlider').value));
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: VIEWPORT, recordVideo: { dir: OUT, size: VIEWPORT } });
  const page = await context.newPage();
  await page.setViewportSize(VIEWPORT);

  const localPath = 'file://' + path.join(__dirname, 'gridai_demo.html');
  await page.goto(localPath, { waitUntil: 'networkidle', timeout: 30000 });
  await sleep(2000);

  // Slowest speed
  await page.evaluate(() => { stepsPerFrame = 64; document.getElementById('speedSelect').value = '64'; });

  // Verify initial state
  let s = await getStep(page);
  let t = await getTime(page);
  console.log(`INIT  step=${s} time=${t}`);

  // === [0s] Side-by-side, play from step 0 ===
  await page.evaluate(() => { setView('side'); jumpTo(0); });
  await play(page);
  await sleep(4000);

  s = await getStep(page); t = await getTime(page);
  console.log(`+4s   step=${s} time=${t}`);

  if (s < 10 || t === '00:00') {
    console.error('ANIMATION STUCK — step barely moved. Fallback: manual drive.');
    await pause(page);
    for (let st = 0; st <= 287; st++) {
      await page.evaluate((x) => jumpTo(x), st);
      await sleep(16);
    }
    s = await getStep(page); t = await getTime(page);
    console.log(`MANUAL_DONE step=${s} time=${t}`);
  }

  // Continue playing through midday
  await sleep(8000);
  s = await getStep(page); t = await getTime(page);
  console.log(`+12s  step=${s} time=${t}`);

  // === [~15s] Naive-only, evening peak ===
  await setViewAndStep(page, 'naive', 144);
  await sleep(10000);
  s = await getStep(page); t = await getTime(page);
  console.log(`+22s  step=${s} time=${t}  naive`);

  // === [~25s] Scroll to ESCALATE card ===
  await page.evaluate(() => { const el = document.querySelector('.bottom-row'); if (el) el.scrollIntoView({ block: 'start' }); });
  await sleep(12000);
  s = await getStep(page); t = await getTime(page);
  console.log(`+34s  step=${s} time=${t}  escalate`);

  // === [~38s] GridAI-only, evening peak ===
  await page.evaluate(() => window.scrollTo({ top: 0 }));
  await setViewAndStep(page, 'gossip', 180);
  await sleep(12000);
  s = await getStep(page); t = await getTime(page);
  console.log(`+46s  step=${s} time=${t}  gridai`);

  // === [~50s] Scroll to APPROVED card ===
  await page.evaluate(() => { const el = document.querySelector('.bottom-row'); if (el) el.scrollIntoView({ block: 'start' }); });
  await sleep(12000);
  s = await getStep(page); t = await getTime(page);
  console.log(`+58s  step=${s} time=${t}  approved`);

  // === [~62s] Side-by-side at peak ===
  await page.evaluate(() => window.scrollTo({ top: 0 }));
  await setViewAndStep(page, 'side', 204);
  await sleep(14000);
  s = await getStep(page); t = await getTime(page);
  console.log(`+72s  step=${s} time=${t}  side`);

  // === [~78s] 3-way panel ===
  await page.evaluate(() => { const el = document.querySelector('.threeway-panel'); if (el) el.scrollIntoView({ block: 'center' }); });
  await sleep(14000);
  s = await getStep(page); t = await getTime(page);
  console.log(`+86s  step=${s} time=${t}  3way`);

  // === [~92s] Result summary panel (honest tradeoff) ===
  await page.evaluate(() => {
    const el = document.querySelector('.threeway-panel:last-of-type');
    if (el) el.scrollIntoView({ block: 'center' });
  });
  await sleep(15000);
  s = await getStep(page); t = await getTime(page);
  console.log(`+101s step=${s} time=${t}  summary`);

  // === [~107s] Final: top view ===
  await page.evaluate(() => window.scrollTo({ top: 0 }));
  await sleep(15000);
  s = await getStep(page); t = await getTime(page);
  console.log(`+116s step=${s} time=${t}  final`);

  await context.close();
  await browser.close();
  await sleep(1000);

  // === Post-process ===
  const files = fs.readdirSync(OUT)
    .filter((f) => f.endsWith('.webm'))
    .sort((a, b) => fs.statSync(path.join(OUT, b)).mtimeMs - fs.statSync(path.join(OUT, a)).mtimeMs);
  if (files.length === 0) throw new Error('No .webm produced');
  const rawPath = path.join(OUT, files[0]);
  const mp4Path = path.join(OUT, 'gridai_demo_v5.mp4');

  const rawDur = parseFloat(execSync(`ffprobe -v error -show_entries format=duration -of csv=p=0 "${rawPath}"`, { encoding: 'utf8' }).trim());
  console.log(`\nRaw webm: ${files[0]}  (${rawDur.toFixed(2)}s)`);

  execSync(`ffmpeg -i "${rawPath}" -ss 0.5 -c:v libx264 -preset fast -crf 18 -pix_fmt yuv420p -y "${mp4Path}" 2>/dev/null`, { timeout: 120000 });

  const stat = fs.statSync(mp4Path);
  const sizeMB = (stat.size / 1024 / 1024).toFixed(2);
  const mp4Dur = parseFloat(execSync(`ffprobe -v error -show_entries format=duration -of csv=p=0 "${mp4Path}"`, { encoding: 'utf8' }).trim());
  console.log(`MP4: ${mp4Path}  (${sizeMB} MB, ${mp4Dur.toFixed(2)}s)`);

  if (fs.existsSync(rawPath)) fs.unlinkSync(rawPath);
  console.log('=== RECORDING COMPLETE ===');
}

main().catch((e) => { console.error('FAILED:', e); process.exit(1); });
