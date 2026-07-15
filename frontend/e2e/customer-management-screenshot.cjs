// frontend/e2e/customer-management-screenshot.cjs
// M33 e2e screenshot — 验证客户管理 CRM 3 个页面 UI
//
// 流程:
// 1. 登录拿 access_token
// 2. seed 数据: 1 个客户 (POST /customers) + 2 条跟进 (POST /follow-ups)
//    + 1 个自定义字段 (POST /customer-fields) — 让 UI 有内容展示
// 3. 启动 chromium, 写 token 到 localStorage
// 4. 截图 1: /dashboard/customer (列表页 + Table + 过滤栏 + 待跟进 Drawer)
// 5. 截图 2: /dashboard/customer/{id} (详情页 + 3 列 + 跟进 timeline)
// 6. 截图 3: /dashboard/customer/settings (字段管理 Table + 6 field_type)
// 7. 验证关键元素存在 (Table row / Timeline / 字段定义 row)
//
// Spec: docs/superpowers/specs/2026-06-20-customer-management-design.md §8.3

const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const CHROMIUM_PATH =
  'C:/Users/wma19/AppData/Local/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-win64/chrome-headless-shell.exe';

const FRONTEND = 'http://localhost:11334';
// Backend 用 127.0.0.1 (Node fetch 默认优先 IPv6 ::1,但 uvicorn 在 IPv4)
const BACKEND = 'http://127.0.0.1:11335';
const OUT_DIR = path.resolve(__dirname, '../../imgs');

async function main() {
  // 1. 登录拿 token
  console.log('[1/8] Logging in...');
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

  const authHeaders = {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
  };

  // 2. seed 数据
  console.log('[2/8] Seeding test data (1 customer + 2 follow-ups + 1 field)...');

  // 用时间戳做 suffix 保证多次跑不冲突
  const runId = String(Date.now()).slice(-6);
  const fieldKey = `customer_ltv_e2e_${runId}`;
  const customerName = `e2e 测试客户 ${runId} · 张三`;
  const wechatId = `zhang_e2e_${runId}`;
  const emailAddr = `zhang.e2e.${runId}@example.com`;

  // 2a. 创建客户
  const customerPayload = {
    name: customerName,
    owner_user_id: 1,
    phone: '13800138000',
    email: emailAddr,
    wechat: wechatId,
    gender: 'M',
    company_name: 'ACME 科技有限公司',
    company_position: 'CTO',
    industry: 'IT',
    company_size: '51-200',
    level: 'vip',
    source: 'referral',
    tags: ['决策人', 'Q4 重点'],
    remark: '通过 e2e 自动化测试创建的示例客户',
  };
  const customerRes = await fetch(`${BACKEND}/api/v1/customers`, {
    method: 'POST',
    headers: authHeaders,
    body: JSON.stringify(customerPayload),
  });
  if (!customerRes.ok) {
    throw new Error(`Create customer failed: ${customerRes.status} ${await customerRes.text()}`);
  }
  const customerBody = await customerRes.json();
  const customerId = customerBody.data.id;
  console.log('  ✓ customer created id =', customerId);

  // 2b. 创建 2 条跟进
  const now = new Date();
  const tomorrow = new Date(now.getTime() + 24 * 60 * 60 * 1000).toISOString();
  const fuList = [
    {
      follow_up_type: 'phone',
      content: '首次电话沟通,客户对 AI Agent 集成方案有兴趣,希望看 demo',
      next_step: '安排线下产品 demo',
      next_follow_up_at: tomorrow,
    },
    {
      follow_up_type: 'wechat',
      content: '微信跟进 demo 时间,客户确认下周二下午 3 点',
      next_step: '准备 demo 环境 + 案例分享',
    },
  ];
  for (const fu of fuList) {
    const fuRes = await fetch(`${BACKEND}/api/v1/customers/${customerId}/follow-ups`, {
      method: 'POST',
      headers: authHeaders,
      body: JSON.stringify(fu),
    });
    if (!fuRes.ok) {
      throw new Error(`Create follow-up failed: ${fuRes.status} ${await fuRes.text()}`);
    }
  }
  console.log('  ✓', fuList.length, 'follow-ups created');

  // 2c. 创建 1 个自定义字段 (number)
  const fieldPayload = {
    field_key: fieldKey,
    field_label: '客户终身价值',
    field_type: 'number',
    required: false,
    order_index: 1,
  };
  const fieldRes = await fetch(`${BACKEND}/api/v1/customer-fields`, {
    method: 'POST',
    headers: authHeaders,
    body: JSON.stringify(fieldPayload),
  });
  if (!fieldRes.ok) {
    throw new Error(`Create field failed: ${fieldRes.status} ${await fieldRes.text()}`);
  }
  console.log('  ✓ 1 field definition created');

  // 3. 启动浏览器
  console.log('[3/8] Launching browser...');
  const browser = await chromium.launch({
    executablePath: CHROMIUM_PATH,
    headless: true,
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });

  context.on('console', (msg) => {
    if (msg.type() === 'error' || msg.type() === 'warning') {
      console.log(`  [browser ${msg.type()}] ${msg.text()}`);
    }
  });

  const page = await context.newPage();
  await page.goto(FRONTEND);
  await page.evaluate((t) => {
    localStorage.setItem('access_token', t);
  }, token);

  // 4. 截图列表页
  console.log('[4/8] Screenshotting customer list page...');
  await page.goto(`${FRONTEND}/dashboard/customer`);
  await page.waitForLoadState('networkidle', { timeout: 30000 });
  console.log(`  Current URL: ${page.url()}`);

  // 等 AntD Table 渲染
  await page.waitForSelector('.ant-table-row', { timeout: 15000 });
  await page.waitForTimeout(1000);
  const listPath = path.join(OUT_DIR, 'm33-customer-list.png');
  await page.screenshot({ path: listPath, fullPage: false });
  console.log(`  ✓ list screenshot: ${listPath}`);

  // 5. 截图详情页
  console.log(`[5/8] Screenshotting customer detail page (id=${customerId})...`);
  await page.goto(`${FRONTEND}/dashboard/customer/${customerId}`);
  await page.waitForLoadState('networkidle', { timeout: 30000 });
  console.log(`  Current URL: ${page.url()}`);

  // 等 AntD Timeline / Descriptions 渲染
  await page.waitForSelector('.ant-timeline', { timeout: 15000 });
  await page.waitForTimeout(1000);
  const detailPath = path.join(OUT_DIR, 'm33-customer-detail.png');
  await page.screenshot({ path: detailPath, fullPage: false });
  console.log(`  ✓ detail screenshot: ${detailPath}`);

  // 6. 截图字段管理页
  console.log('[6/8] Screenshotting field settings page...');
  await page.goto(`${FRONTEND}/dashboard/customer/settings`);
  await page.waitForLoadState('networkidle', { timeout: 30000 });
  await page.waitForSelector('.ant-table-row', { timeout: 15000 });
  await page.waitForTimeout(1000);
  const settingsPath = path.join(OUT_DIR, 'm33-customer-settings.png');
  await page.screenshot({ path: settingsPath, fullPage: false });
  console.log(`  ✓ settings screenshot: ${settingsPath}`);

  // 7. 验证关键元素
  console.log('[7/8] Verifying key elements...');

  // 7a. 列表页验证: 回到列表页检查
  await page.goto(`${FRONTEND}/dashboard/customer`);
  await page.waitForSelector('.ant-table-row', { timeout: 15000 });
  await page.waitForTimeout(500);
  const listChecks = {
    tableRows: await page.locator('.ant-table-row').count(),
    hasNewCustomer: await page
      .getByText(customerName)
      .count(),
    hasVipTag: await page.getByText('VIP').count(),
    hasSearchBox: await page
      .locator('input[placeholder*="搜索"]')
      .count(),
  };

  // 7b. 详情页验证
  await page.goto(`${FRONTEND}/dashboard/customer/${customerId}`);
  await page.waitForSelector('.ant-timeline', { timeout: 15000 });
  const detailChecks = {
    timeline: await page.locator('.ant-timeline').count(),
    followUpItems: await page.locator('.ant-timeline-item').count(),
    aiSuggestBtn: await page
      .getByRole('button', { name: /AI 智能建议/ })
      .count(),
    basicInfoCard: await page
      .locator('.ant-card-head-title')
      .filter({ hasText: '基础信息' })
      .count(),
    companyInfoCard: await page
      .locator('.ant-card-head-title')
      .filter({ hasText: '公司信息' })
      .count(),
  };

  // 7c. 字段管理验证
  await page.goto(`${FRONTEND}/dashboard/customer/settings`);
  await page.waitForSelector('.ant-table-row', { timeout: 15000 });
  const settingsChecks = {
    tableRows: await page.locator('.ant-table-row').count(),
    hasNumberTag: await page.getByText('数字').count(),
    hasLtvField: await page.getByText(fieldKey).count(),
    hasLtvLabel: await page.getByText('客户终身价值').count(),
  };

  console.log('\n=== Verification ===');
  console.log('  List page:');
  console.log(`    Table rows:        ${listChecks.tableRows} (expect >= 1)`);
  console.log(`    New customer row: ${listChecks.hasNewCustomer} (expect 1)`);
  console.log(`    VIP tag:          ${listChecks.hasVipTag} (expect >= 1)`);
  console.log(`    Search input:     ${listChecks.hasSearchBox} (expect 1)`);
  console.log('  Detail page:');
  console.log(`    Timeline:         ${detailChecks.timeline} (expect 1)`);
  console.log(`    Follow-up items:  ${detailChecks.followUpItems} (expect 2)`);
  console.log(`    AI suggest btn:   ${detailChecks.aiSuggestBtn} (expect 1)`);
  console.log(`    Basic info card:  ${detailChecks.basicInfoCard} (expect 1)`);
  console.log(`    Company info card:${detailChecks.companyInfoCard} (expect 1)`);
  console.log('  Settings page:');
  console.log(`    Table rows:       ${settingsChecks.tableRows} (expect >= 1)`);
  console.log(`    Number tag:       ${settingsChecks.hasNumberTag} (expect >= 1)`);
  console.log(`    ltv field_key:    ${settingsChecks.hasLtvField} (expect 1)`);
  console.log(`    ltv field label:  ${settingsChecks.hasLtvLabel} (expect 1)`);

  await browser.close();

  // 输出文件大小
  console.log('\n=== Files ===');
  for (const p of [listPath, detailPath, settingsPath]) {
    const stat = fs.statSync(p);
    console.log(`  ${p}: ${(stat.size / 1024).toFixed(1)} KB`);
  }

  // 8. 验证通过条件
  const allOk =
    listChecks.tableRows >= 1 &&
    listChecks.hasNewCustomer >= 1 &&
    listChecks.hasVipTag >= 1 &&
    listChecks.hasSearchBox >= 1 &&
    detailChecks.timeline === 1 &&
    detailChecks.followUpItems === 2 &&
    detailChecks.aiSuggestBtn >= 1 &&
    detailChecks.basicInfoCard >= 1 &&
    detailChecks.companyInfoCard >= 1 &&
    settingsChecks.tableRows >= 1 &&
    settingsChecks.hasNumberTag >= 1 &&
    settingsChecks.hasLtvField >= 1 &&
    settingsChecks.hasLtvLabel >= 1;

  if (!allOk) {
    console.error('\n❌ Verification FAILED');
    process.exit(1);
  }
  console.log('\n✅ Verification PASSED — M33 客户管理 CRM UI 截图 + 14 个 DOM 断言全过');
  console.log(`   Seeded customer id = ${customerId} (可在 /dashboard/customer 列表看到)`);
}

main().catch((err) => {
  console.error('Fatal:', err);
  process.exit(1);
});