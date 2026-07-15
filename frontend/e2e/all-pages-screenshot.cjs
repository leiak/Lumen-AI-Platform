// frontend/e2e/all-pages-screenshot.cjs
// 全平台页面 E2E 截图验证
//
// 覆盖范围:
// - frontend (11334): 所有 /login + /dashboard/* 页面 + wx-publisher children + training/*
// - frontend-overview (11337): / 和 /overview 大屏
// - widget demo (11335 静态服务): 嵌入式 chat widget demo 页
//
// 流程:
// 1. login 拿 access_token (admin/admin123)
// 2. 启动 chromium, 1440x900, viewport 全屏
// 3. 遍历每个页面 → networkidle → 截图到 imgs/all-pages/<NN-name>.png
// 4. 对每个页面验证至少一个关键 DOM 元素 (h1 / .ant-table / .ant-card 等)
// 5. 汇总报告: PASS / PARTIAL / FAIL + console 错误 + 5xx 响应
//
// 期望产物:
// - imgs/all-pages/*.png  (38+ 张)
// - imgs/all-pages/report.txt (汇总)
//
// 参考: docs-internal/superpowers/specs/ 里 M5/M13/M14/M30/M32/M33 等历史 e2e 截图脚本

const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const CHROMIUM_PATH =
  'C:/Users/wma19/AppData/Local/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-win64/chrome-headless-shell.exe';

const FRONTEND = 'http://localhost:11334';
const OVERVIEW = 'http://localhost:11337';
const BACKEND = 'http://127.0.0.1:11335';
const OUT_DIR = path.resolve(__dirname, '../../imgs/all-pages');

// 页面清单 — 主前端
// path | 期望关键 selector (用于 sanity check,留空 = 任意 h1 即可) | 描述
const PAGES = [
  // 认证
  { path: '/login', selector: 'form input[type="password"]', name: '01-login', host: FRONTEND, desc: '登录页' },

  // dashboard home
  { path: '/dashboard', selector: '.ant-pro-layout-content', name: '02-dashboard-home', host: FRONTEND, desc: '首页 dashboard' },

  // 知识库
  { path: '/dashboard/knowledge', selector: '.ant-pro-layout-content', name: '03-knowledge', host: FRONTEND, desc: '知识库 KB 管理' },

  // AI Agent
  { path: '/dashboard/agent', selector: '.ant-pro-layout-content', name: '04-agent-list', host: FRONTEND, desc: 'AI Agent 列表' },
  { path: '/dashboard/agent/team', selector: '.ant-pro-layout-content', name: '05-agent-team', host: FRONTEND, desc: '多代理团队' },

  // 客户管理 (M33 CRM)
  { path: '/dashboard/customer', selector: '.ant-pro-layout-content', name: '06-customer-list', host: FRONTEND, desc: '客户列表' },
  { path: '/dashboard/customer/settings', selector: '.ant-pro-layout-content', name: '07-customer-settings', host: FRONTEND, desc: '客户字段管理' },

  // Chat
  { path: '/dashboard/chat', selector: '.ant-pro-layout-content', name: '08-chat', host: FRONTEND, desc: 'Chat 多会话' },

  // 公众号助手 (M32)
  { path: '/dashboard/wx-publisher', selector: '.ant-pro-layout-content', name: '09-wx-publisher-home', host: FRONTEND, desc: '公众号助手首页' },
  { path: '/dashboard/wx-publisher/drafts', selector: '.ant-pro-layout-content', name: '10-wx-drafts', host: FRONTEND, desc: '公众号草稿管理' },
  { path: '/dashboard/wx-publisher/templates', selector: '.ant-pro-layout-content', name: '11-wx-templates', host: FRONTEND, desc: '公众号排版模板' },
  { path: '/dashboard/wx-publisher/materials', selector: '.ant-pro-layout-content', name: '12-wx-materials', host: FRONTEND, desc: '公众号素材库' },
  { path: '/dashboard/wx-publisher/accounts', selector: '.ant-pro-layout-content', name: '13-wx-accounts', host: FRONTEND, desc: '公众号账号管理' },

  // 图片生成 (M22)
  { path: '/dashboard/image-generation', selector: '.ant-pro-layout-content', name: '14-image-generation', host: FRONTEND, desc: '图片生成' },

  // 智能问数 (M33 Text2SQL)
  { path: '/dashboard/text2sql', selector: '.ant-pro-layout-content', name: '15-text2sql', host: FRONTEND, desc: 'Text2SQL 智能问数' },

  // 记忆管理
  { path: '/dashboard/memory', selector: '.ant-pro-layout-content', name: '16-memory', host: FRONTEND, desc: '记忆管理' },

  // 工作流 (M30 大版本)
  { path: '/dashboard/workflow', selector: '.ant-pro-layout-content', name: '17-workflow-list', host: FRONTEND, desc: '工作流列表' },
  { path: '/dashboard/workflow/templates', selector: '.ant-pro-layout-content', name: '18-workflow-templates', host: FRONTEND, desc: '工作流模板中心' },
  // designer 必须有 workflow id — 跳过,后续如需要单独跑

  // MCP
  { path: '/dashboard/mcp', selector: '.ant-pro-layout-content', name: '19-mcp', host: FRONTEND, desc: 'MCP 服务管理' },

  // 桌面端
  { path: '/dashboard/electron', selector: '.ant-pro-layout-content', name: '20-electron', host: FRONTEND, desc: 'Electron 桌面端' },

  // Skills (M7)
  { path: '/dashboard/skills/installed', selector: '.ant-pro-layout-content', name: '21-skills-installed', host: FRONTEND, desc: '我的技能' },
  { path: '/dashboard/skills/market', selector: '.ant-pro-layout-content', name: '22-skills-market', host: FRONTEND, desc: '技能市场' },

  // 工作流市场
  { path: '/dashboard/marketplace', selector: '.ant-pro-layout-content', name: '23-marketplace', host: FRONTEND, desc: '工作流市场' },

  // 系统管理
  { path: '/dashboard/system/users', selector: '.ant-pro-layout-content', name: '24-system-users', host: FRONTEND, desc: '用户管理' },
  { path: '/dashboard/system/roles', selector: '.ant-pro-layout-content', name: '25-system-roles', host: FRONTEND, desc: '角色管理' },
  { path: '/dashboard/system/models', selector: '.ant-pro-layout-content', name: '26-system-models', host: FRONTEND, desc: '模型配置' },
  { path: '/dashboard/system/settings', selector: '.ant-pro-layout-content', name: '27-system-settings', host: FRONTEND, desc: '系统设置' },
  { path: '/dashboard/system/skills', selector: '.ant-pro-layout-content', name: '28-system-skills', host: FRONTEND, desc: '系统技能' },

  // 外部应用 (M14 widget 后台)
  { path: '/dashboard/external-apps', selector: '.ant-pro-layout-content', name: '29-external-apps', host: FRONTEND, desc: '外部应用授权' },

  // 日志
  { path: '/dashboard/logs', selector: '.ant-pro-layout-content', name: '30-logs', host: FRONTEND, desc: '日志审计' },

  // 模型训练
  { path: '/dashboard/training/nlp', selector: '.ant-pro-layout-content', name: '31-training-nlp', host: FRONTEND, desc: 'NLP 训练' },
  { path: '/dashboard/training/nlp/annotation', selector: '.ant-pro-layout-content', name: '32-training-nlp-annotation', host: FRONTEND, desc: 'NLP 标注' },
  { path: '/dashboard/training/nlp/classification', selector: '.ant-pro-layout-content', name: '33-training-nlp-classification', host: FRONTEND, desc: 'NLP 分类' },
  { path: '/dashboard/training/nlp/qa', selector: '.ant-pro-layout-content', name: '34-training-nlp-qa', host: FRONTEND, desc: 'NLP 问答' },
  { path: '/dashboard/training/vision/classification', selector: '.ant-pro-layout-content', name: '35-training-vision-classification', host: FRONTEND, desc: '视觉分类' },
  { path: '/dashboard/training/vision/image', selector: '.ant-pro-layout-content', name: '36-training-vision-image', host: FRONTEND, desc: '视觉图像' },

  // 文档
  { path: '/dashboard/document', selector: '.ant-pro-layout-content', name: '37-document', host: FRONTEND, desc: '文档处理' },

  // 大屏子项目 (frontend-overview, port 11337)
  { path: '/', selector: 'body', name: '38-overview-home', host: OVERVIEW, desc: '大屏首页' },
  { path: '/overview', selector: 'body', name: '39-overview', host: OVERVIEW, desc: '大屏视图' },
];

// 异步等待 utility
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  console.log('=== 全平台 E2E 截图验证 ===');
  console.log(`Output: ${OUT_DIR}`);
  fs.mkdirSync(OUT_DIR, { recursive: true });

  // 1. login 拿 token
  console.log('\n[1/N] Login as admin...');
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
  console.log(`  ✓ token acquired (len ${token.length})`);

  // 2. 启动浏览器
  console.log('\n[2/N] Launch browser...');
  const browser = await chromium.launch({
    executablePath: CHROMIUM_PATH,
    headless: true,
  });

  // 全局网络 / console 监控(每页单独订阅)
  const network5xx = [];
  const consoleErrors = [];

  // 注入 token — 用 addInitScript,所有新建 page 都自动注入
  // 每页用独立 incognito context 彻底隔离 history/storage,避免 Next.js dev client cache 串扰
  const baseContext = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  await baseContext.addInitScript((t) => {
    try { localStorage.setItem('access_token', t); } catch {}
  }, token);
  console.log('  ✓ base context with addInitScript ready');

  // 3. 遍历所有页面 — 每页用新 page 实例避免 Next.js client-side 路由缓存
  console.log(`\n[3/N] Visit ${PAGES.length} pages...`);
  const results = [];
  let passCount = 0;
  let failCount = 0;
  let skipCount = 0;

  for (const p of PAGES) {
    const url = `${p.host}${p.path}`;
    const outPath = path.join(OUT_DIR, `${p.name}.png`);

    process.stdout.write(`  [${p.name}] ${p.path} ... `);

    try {
      // 每页用独立 incognito context 隔离(共享 baseContext 的 addInitScript 不会自动继承,
      // 所以每页重新注入 token)
      const pageCtx = await browser.newContext({
        viewport: { width: 1440, height: 900 },
      });
      await pageCtx.addInitScript((t) => {
        try { localStorage.setItem('access_token', t); } catch {}
      }, token);
      const subPage = await pageCtx.newPage();
      subPage.on('response', (r) => {
        if (r.status() >= 500) {
          network5xx.push({ status: r.status(), url: r.url().substring(0, 200) });
        }
      });
      subPage.on('console', (msg) => {
        if (msg.type() === 'error') {
          consoleErrors.push({ text: msg.text().substring(0, 300), location: msg.location() });
        }
      });

      // goto + 等 networkidle + 长 sleep,等 React hydration 完成
      // timeout 90s: Next.js dev 首次访问未预热路由需 60-90s 编译
      const resp = await subPage.goto(url, {
        waitUntil: 'load',
        timeout: 90000,
      });
      const status = resp ? resp.status() : 0;

      // 等待 networkidle
      await subPage
        .waitForLoadState('networkidle', { timeout: 30000 })
        .catch(() => {});

      // 显式等 usePathname() 稳定 — ProLayout 的 pathname 是异步的,
      // 必须等 React state 更新才能正确高亮/截图
      await sleep(3000);

      // 等待 networkidle (timeout 10s,不阻塞)
      await subPage
        .waitForLoadState('networkidle', { timeout: 10000 })
        .catch(() => {});

      // 额外的页面渲染等待 — 等 ProLayout mount 后再截图,避免 React state hydration race
      await sleep(2500);

      // sanity check
      let selectorFound = false;
      if (p.selector) {
        try {
          await subPage.waitForSelector(p.selector, { timeout: 5000 });
          selectorFound = true;
        } catch (e) {
          selectorFound = false;
        }
      }

      // 截图 — 先加 URL 水印,再截图,便于事后核对
      // 用 window.location.href(浏览器内)而不是 subPage.url()(Playwright wrapper),
      // 避免导航 race condition 导致 URL 错位
      const realUrl = await subPage.evaluate(() => window.location.href);
      await subPage.evaluate((u) => {
        const banner = document.createElement('div');
        banner.id = '__screenshot_banner__';
        banner.textContent = 'PLAYWRIGHT-URL=' + u;
        banner.style.cssText =
          'position:fixed;top:0;left:0;right:0;background:#ff0;color:#000;padding:4px 8px;font:bold 14px monospace;z-index:999999;border-bottom:2px solid #000';
        document.body.appendChild(banner);
      }, realUrl);
      await sleep(500);
      await subPage.screenshot({ path: outPath, fullPage: false });

      const finalUrl = subPage.url();
      const okStatus = status >= 200 && status < 400;
      const okSelector = !p.selector || selectorFound;

      let verdict;
      if (!okStatus) {
        verdict = 'FAIL';
        failCount++;
      } else if (!okSelector) {
        verdict = 'PARTIAL';
        skipCount++;
      } else {
        verdict = 'PASS';
        passCount++;
      }

      results.push({
        name: p.name,
        path: p.path,
        desc: p.desc,
        status,
        finalUrl,
        selectorFound,
        verdict,
        screenshot: path.basename(outPath),
      });

      console.log(`${verdict} (HTTP ${status}, selector ${selectorFound ? '✓' : '✗'}, url=${finalUrl})`);
    } catch (err) {
      failCount++;
      results.push({
        name: p.name,
        path: p.path,
        desc: p.desc,
        status: 0,
        finalUrl: url,
        selectorFound: false,
        verdict: 'FAIL',
        error: String(err).substring(0, 200),
      });
      console.log(`FAIL (error: ${String(err).substring(0, 80)})`);
    } finally {
      try { await subPage.close(); await pageCtx.close(); } catch {}
    }
  }

  await browser.close();

  // 4. 输出报告
  console.log('\n[4/N] Writing report...');
  const reportPath = path.join(OUT_DIR, 'report.txt');
  const lines = [];
  lines.push('=== 全平台 E2E 截图验证报告 ===');
  lines.push(`Generated: ${new Date().toISOString()}`);
  lines.push(`Total pages: ${PAGES.length}`);
  lines.push(`PASS:    ${passCount}`);
  lines.push(`PARTIAL: ${skipCount} (rendered but selector not found)`);
  lines.push(`FAIL:    ${failCount}`);
  lines.push(`Network 5xx errors: ${network5xx.length}`);
  lines.push(`Console errors:     ${consoleErrors.length}`);
  lines.push('');

  lines.push('--- Per-page results ---');
  lines.push(
    ['verdict', 'page', 'status', 'selector', 'path'].map((h) => h.padEnd(20)).join('')
  );
  for (const r of results) {
    lines.push(
      [
        r.verdict.padEnd(8),
        (r.name || '').padEnd(28),
        String(r.status).padEnd(6),
        (r.selectorFound ? '✓' : '✗').padEnd(8),
        r.path,
      ].join('  ')
    );
    if (r.error) lines.push(`    error: ${r.error}`);
  }
  lines.push('');

  if (network5xx.length > 0) {
    lines.push('--- 5xx responses (first 20) ---');
    for (const e of network5xx.slice(0, 20)) {
      lines.push(`  ${e.status}  ${e.url}`);
    }
    if (network5xx.length > 20) lines.push(`  ... (${network5xx.length - 20} more)`);
    lines.push('');
  }

  if (consoleErrors.length > 0) {
    lines.push('--- Console errors (first 20) ---');
    for (const e of consoleErrors.slice(0, 20)) {
      lines.push(`  ${e.text.substring(0, 200)}`);
      if (e.location && e.location.url) {
        lines.push(`    @ ${e.location.url}:${e.location.lineNumber}`);
      }
    }
    if (consoleErrors.length > 20) lines.push(`  ... (${consoleErrors.length - 20} more)`);
    lines.push('');
  }

  fs.writeFileSync(reportPath, lines.join('\n'));
  console.log(`  ✓ report: ${reportPath}`);

  // 5. 打印总览
  console.log('\n=== Summary ===');
  console.log(`  Total: ${PAGES.length} | PASS: ${passCount} | PARTIAL: ${skipCount} | FAIL: ${failCount}`);
  console.log(`  5xx errors: ${network5xx.length} | Console errors: ${consoleErrors.length}`);
  console.log(`  Screenshots: ${OUT_DIR}/`);
  console.log(`  Report:      ${reportPath}`);

  // exit code
  if (failCount > 0) {
    console.error('\n❌ Some pages FAILED to render');
    process.exit(1);
  }
  console.log('\n✅ All pages rendered successfully');
}

main().catch((err) => {
  console.error('Fatal:', err);
  process.exit(1);
});