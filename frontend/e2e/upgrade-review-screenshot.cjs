// frontend/e2e/upgrade-review-screenshot.cjs
// 2026-06-20 整体 dashboard 扫描:登录 → 逐个访问 sidebar 入口 → 截图 + 收集 console error
// 输出到 imgs/upgrade-review/<slug>.png + imgs/upgrade-review/console-errors.json
//
// 目的: 整理"待升级完善"清单(视觉/UX/bug)供人工复核

const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const CHROMIUM_PATH =
  'C:/Users/wma19/AppData/Local/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-win64/chrome-headless-shell.exe';

const FRONTEND = 'http://localhost:11334';
const BACKEND = 'http://127.0.0.1:11335';
const OUT_DIR = path.resolve(__dirname, '../../imgs/upgrade-review');

// 截图目标(从 frontend/app/dashboard/layout.tsx sidebar 入口整理)
// slug 用作文件名,path 是 URL path
const TARGETS = [
  { slug: '01-home',             path: '/dashboard' },
  { slug: '02-knowledge',        path: '/dashboard/knowledge' },
  { slug: '03-agent',            path: '/dashboard/agent' },
  { slug: '04-agent-team',       path: '/dashboard/agent/team' },
  { slug: '05-chat',             path: '/dashboard/chat' },
  { slug: '06-wx-publisher',     path: '/dashboard/wx-publisher' },
  { slug: '07-wx-drafts',        path: '/dashboard/wx-publisher/drafts' },
  { slug: '08-wx-templates',     path: '/dashboard/wx-publisher/templates' },
  { slug: '09-wx-materials',     path: '/dashboard/wx-publisher/materials' },
  { slug: '10-wx-accounts',      path: '/dashboard/wx-publisher/accounts' },
  { slug: '11-image-generation', path: '/dashboard/image-generation' },
  { slug: '12-memory',           path: '/dashboard/memory' },
  { slug: '13-workflow',         path: '/dashboard/workflow' },
  { slug: '14-workflow-templates', path: '/dashboard/workflow/templates' },
  { slug: '15-mcp',              path: '/dashboard/mcp' },
  { slug: '16-electron',         path: '/dashboard/electron' },
  { slug: '17-skills-installed', path: '/dashboard/skills/installed' },
  { slug: '18-skills-market',    path: '/dashboard/skills/market' },
  { slug: '19-marketplace',      path: '/dashboard/marketplace' },
  { slug: '20-system-users',     path: '/dashboard/system/users' },
  { slug: '21-system-roles',     path: '/dashboard/system/roles' },
  { slug: '22-system-models',    path: '/dashboard/system/models' },
  { slug: '23-system-settings',  path: '/dashboard/system/settings' },
  { slug: '24-external-apps',    path: '/dashboard/external-apps' },
  { slug: '25-logs',             path: '/dashboard/logs' },
];

async function main() {
  // 准备输出目录
  fs.mkdirSync(OUT_DIR, { recursive: true });

  // 1. 登录
  console.log('[1/3] Logging in...');
  const loginBody = new URLSearchParams({ username: 'admin', password: 'admin123' });
  const loginRes = await fetch(`${BACKEND}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: loginBody,
  });
  if (!loginRes.ok) throw new Error(`Login failed: ${loginRes.status}`);
  const loginData = await loginRes.json();
  const token = loginData.data?.access_token || loginData.access_token;
  if (!token) throw new Error('No access_token');
  console.log('  ✓ token (len:', token.length, ')');

  // 2. 启动浏览器
  console.log('[2/3] Launching browser...');
  const browser = await chromium.launch({
    executablePath: CHROMIUM_PATH,
    headless: true,
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  const page = await context.newPage();

  // 收集 console 错误
  const consoleErrors = []; // {slug, type, text}
  const networkErrors = []; // {slug, status, url}

  page.on('console', (msg) => {
    if (msg.type() === 'error' || msg.type() === 'warning') {
      consoleErrors.push({
        slug: page._currentSlug || '?',
        type: msg.type(),
        text: msg.text().substring(0, 300),
      });
    }
  });
  page.on('response', (res) => {
    if (res.status() >= 500) {
      networkErrors.push({
        slug: page._currentSlug || '?',
        status: res.status(),
        url: res.url().substring(0, 200),
      });
    }
  });

  // 写 token
  await page.goto(FRONTEND);
  await page.evaluate((t) => localStorage.setItem('access_token', t), token);

  // 3. 逐个截图
  console.log(`[3/3] Visiting ${TARGETS.length} pages...`);
  const results = [];
  for (const t of TARGETS) {
    page._currentSlug = t.slug;
    process.stdout.write(`  ${t.slug.padEnd(28)} ${t.path} ... `);
    try {
      const start = Date.now();
      const resp = await page.goto(`${FRONTEND}${t.path}`, {
        waitUntil: 'domcontentloaded',
        timeout: 30000,
      });
      const status = resp ? resp.status() : 0;
      // 等稳定
      await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
      // 让 antd skeleton / 数据 fetch 完成
      await page.waitForTimeout(800);
      const outPath = path.join(OUT_DIR, `${t.slug}.png`);
      await page.screenshot({ path: outPath, fullPage: false });
      const ms = Date.now() - start;
      const title = await page.title();
      const finalUrl = page.url();
      const visibleText = await page.evaluate(() => {
        const m = document.querySelector('main') || document.body;
        return m.innerText.substring(0, 200).replace(/\n+/g, ' / ');
      });
      results.push({ slug: t.slug, path: t.path, status, ms, title, finalUrl, visibleText, outPath });
      process.stdout.write(`HTTP ${status} ${ms}ms\n`);
    } catch (err) {
      results.push({ slug: t.slug, path: t.path, error: err.message.substring(0, 200) });
      process.stdout.write(`❌ ${err.message.substring(0, 80)}\n`);
    }
  }

  await browser.close();

  // 4. 写报告
  const report = {
    timestamp: new Date().toISOString(),
    targets_total: TARGETS.length,
    visited_ok: results.filter((r) => !r.error).length,
    visited_err: results.filter((r) => r.error).length,
    http_5xx: results.filter((r) => r.status >= 500).length,
    console_errors: consoleErrors,
    network_errors: networkErrors,
    pages: results,
  };
  const reportPath = path.join(OUT_DIR, 'report.json');
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));

  console.log('\n=== Summary ===');
  console.log(`  Pages:        ${report.visited_ok} ok / ${report.visited_err} err`);
  console.log(`  HTTP 5xx:     ${report.http_5xx}`);
  console.log(`  Console:      ${consoleErrors.length} (warn+err)`);
  console.log(`  Network 5xx:  ${networkErrors.length}`);
  console.log(`  Report:       ${reportPath}`);
}

main().catch((err) => {
  console.error('Fatal:', err);
  process.exit(1);
});
