// frontend/e2e/wx-templates-screenshot.cjs
// Focused screenshot of the wx-publisher templates page after the
// fetch+blob thumbnail refactor. Just this one page, not the full sweep.
const { chromium } = require('playwright');
const path = require('path');

const CHROMIUM_PATH =
  'C:/Users/wma19/AppData/Local/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-win64/chrome-headless-shell.exe';

const FRONTEND = 'http://localhost:11334';
const BACKEND = 'http://127.0.0.1:11335';
const OUT_DIR = path.resolve(__dirname, '../../imgs/upgrade-review');
const TARGET = '/dashboard/wx-publisher/templates';

async function main() {
  console.log('[1/3] login...');
  const loginBody = new URLSearchParams({ username: 'admin', password: 'admin123' });
  const loginRes = await fetch(`${BACKEND}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: loginBody,
  });
  if (!loginRes.ok) throw new Error(`login failed: ${loginRes.status}`);
  const loginData = await loginRes.json();
  const token = loginData.data?.access_token || loginData.access_token;
  if (!token) throw new Error('no token');
  console.log(`  ✓ token (len ${token.length})`);

  console.log('[2/3] browser launch...');
  const browser = await chromium.launch({ executablePath: CHROMIUM_PATH, headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();

  const networkErrors = [];
  const imageResponses = [];
  page.on('response', (r) => {
    const url = r.url();
    if (url.includes('/thumbnail')) {
      imageResponses.push({ status: r.status(), url: url.substring(0, 120), bytes: r.headers()['content-length'] });
    }
    if (r.status() >= 500) {
      networkErrors.push({ status: r.status(), url: url.substring(0, 200) });
    }
  });

  console.log('[3/3] visiting target...');
  await page.goto(FRONTEND);
  await page.evaluate((t) => localStorage.setItem('access_token', t), token);

  const resp = await page.goto(`${FRONTEND}${TARGET}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  console.log(`  page status: ${resp ? resp.status() : 0}`);
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(2000); // wait for 15 thumbnail blob fetches

  const out = path.join(OUT_DIR, '08-wx-templates-v2.png');
  await page.screenshot({ path: out, fullPage: false });
  console.log(`  ✓ screenshot: ${out}`);

  // Count <img> tags with non-empty src
  const imgStats = await page.evaluate(() => {
    const imgs = Array.from(document.querySelectorAll('img'));
    return imgs.map((i) => ({ src: i.src.substring(0, 80), naturalWidth: i.naturalWidth, complete: i.complete }));
  });

  await browser.close();
  console.log(`\n--- thumbnails fetched (${imageResponses.length}) ---`);
  imageResponses.forEach((r) => console.log(`  ${r.status}  ${r.bytes || '?'} bytes  ${r.url}`));
  console.log(`\n--- <img> tags (${imgStats.length}) ---`);
  imgStats.slice(0, 5).forEach((i) => console.log(`  nw=${i.naturalWidth}  complete=${i.complete}  src=${i.src}`));
  console.log(`  ... (${imgStats.length - 5} more)`);
  console.log(`\n--- 5xx network errors: ${networkErrors.length} ---`);
  networkErrors.forEach((e) => console.log(`  ${e.status}  ${e.url}`));
}

main().catch((e) => { console.error('Fatal:', e); process.exit(1); });
