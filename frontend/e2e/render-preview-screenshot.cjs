// frontend/e2e/render-preview-screenshot.cjs
// M32.1 e2e screenshot script — 验证 RenderPreview 双屏预览
//
// 流程:
// 1. 登录拿 access_token, 写 localStorage (前端 axios interceptor 从这里读)
// 2. 导航到 /dashboard/wx-publisher/drafts/462 (存在的草稿)
// 3. 等待 draft 详情加载 + RenderPreview iframe
// 4. 截图 1: desktop 模式 (full page)
// 5. 点击 Segmented 「手机 (375px)」
// 6. 等待 phone-frame DOM 出现 (status bar 9:41 + home indicator)
// 7. 截图 2: mobile 模式
// 8. 输出到 imgs/m32-1-render-preview-desktop.png + mobile.png
//
// 不通过 vitest — 这是 standalone Node script,直接调 playwright。
// Chromium 用 chromium_headless_shell-1223 (项目本机已存在,避免重下 200MB)。

const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const CHROMIUM_PATH =
  'C:/Users/wma19/AppData/Local/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-win64/chrome-headless-shell.exe';

const FRONTEND = 'http://localhost:11334';
// Backend 用 127.0.0.1 (Node fetch 默认优先 IPv6 ::1,但 uvicorn 在 IPv4)
const BACKEND = 'http://127.0.0.1:11335';
const DRAFT_ID = 462; // dev DB 已存在的草稿
const OUT_DIR = path.resolve(__dirname, '../../imgs');

async function main() {
  // 1. 登录拿 token (OAuth2PasswordRequestForm — form-encoded)
  console.log('[1/6] Logging in...');
  const loginBody = new URLSearchParams({ username: 'admin', password: 'admin123' });
  const loginRes = await fetch(`${BACKEND}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: loginBody,
  });
  if (!loginRes.ok) {
    throw new Error(`Login failed: ${loginRes.status} ${await loginRes.text()}`);
  }
  const loginData = await loginRes.json();
  const token = loginData.data?.access_token || loginData.access_token;
  if (!token) throw new Error('No access_token in login response');
  console.log('  ✓ token acquired (length:', token.length, ')');

  // 2. 启动浏览器
  console.log('[2/6] Launching browser...');
  const browser = await chromium.launch({
    executablePath: CHROMIUM_PATH,
    headless: true,
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });

  // 监听 console + network 错误
  context.on('console', (msg) => {
    if (msg.type() === 'error' || msg.type() === 'warning') {
      console.log(`  [browser ${msg.type()}] ${msg.text()}`);
    }
  });

  // 3. 写 token 到 localStorage (先访问一次 frontend 让 origin 建立)
  console.log('[3/6] Setting access_token in localStorage...');
  const page = await context.newPage();
  await page.goto(FRONTEND);
  await page.evaluate((t) => {
    localStorage.setItem('access_token', t);
  }, token);

  // 4. 导航到草稿编辑页
  console.log(`[4/6] Navigating to /dashboard/wx-publisher/drafts/${DRAFT_ID}...`);
  await page.goto(`${FRONTEND}/dashboard/wx-publisher/drafts/${DRAFT_ID}`);
  // Wait for navigation to complete (might redirect to /login if token invalid)
  await page.waitForLoadState('networkidle', { timeout: 30000 });
  console.log(`  Current URL: ${page.url()}`);
  console.log(`  Page title: ${await page.title()}`);

  // Dump visible text for debug
  const visibleText = await page.evaluate(() => {
    const main = document.querySelector('main') || document.body;
    return main.innerText.substring(0, 500);
  });
  console.log(`  Visible text (first 500 chars):\n${visibleText}`);

  // 5. 等 draft 详情加载 + MDEditor + preview iframe
  console.log('[5/6] Waiting for desktop preview iframe...');
  await page.waitForSelector('iframe[title="render-preview-desktop"]', {
    timeout: 20000,
  });
  // 等渲染稳定
  await page.waitForTimeout(2000);

  // 截图 1: 桌面模式
  const desktopPath = path.join(OUT_DIR, 'm32-1-render-preview-desktop.png');
  await page.screenshot({ path: desktopPath, fullPage: false });
  console.log(`  ✓ desktop screenshot: ${desktopPath}`);

  // 6. 切到手机模式
  console.log('[6/6] Switching to mobile mode...');
  // Segmented 选项里有"手机 (375px)" 文字
  await page.getByText('手机 (375px)').click();
  await page.waitForSelector('iframe[title="render-preview-mobile"]', {
    timeout: 10000,
  });
  // 等 status bar / home indicator 渲染
  await page.waitForSelector('text=9:41', { timeout: 5000 });
  await page.waitForTimeout(1500);

  // 截图 2: 手机模式
  const mobilePath = path.join(OUT_DIR, 'm32-1-render-preview-mobile.png');
  await page.screenshot({ path: mobilePath, fullPage: false });
  console.log(`  ✓ mobile screenshot: ${mobilePath}`);

  // 验证关键元素
  const checks = {
    desktopIframe: await page
      .locator('iframe[title="render-preview-desktop"]')
      .count(),
    mobileIframe: await page.locator('iframe[title="render-preview-mobile"]').count(),
    statusBar9_41: await page.getByText('9:41').count(),
  };
  console.log('\n=== Verification ===');
  console.log('  Desktop iframes remaining:', checks.desktopIframe, '(expect 0)');
  console.log('  Mobile iframes present:  ', checks.mobileIframe, '(expect 1)');
  console.log('  Status bar "9:41":       ', checks.statusBar9_41, '(expect 1)');

  await browser.close();

  // 输出 summary
  console.log('\n=== Files ===');
  for (const p of [desktopPath, mobilePath]) {
    const stat = fs.statSync(p);
    console.log(`  ${p}: ${(stat.size / 1024).toFixed(1)} KB`);
  }

  if (checks.desktopIframe !== 0 || checks.mobileIframe !== 1) {
    console.error('\n❌ Verification FAILED');
    process.exit(1);
  }
  console.log('\n✅ Verification PASSED');
}

main().catch((err) => {
  console.error('Fatal:', err);
  process.exit(1);
});