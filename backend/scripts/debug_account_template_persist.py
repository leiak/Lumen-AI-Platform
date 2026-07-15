"""Debug: 验证「选账号 + 选模板 + 保存 + 重新进入」是否真持久化."""
import asyncio
import httpx
from playwright.async_api import async_playwright


API_BASE = "http://localhost:11335"
FRONTEND_BASE = "http://localhost:11334"
DRAFT_ID = 85


async def login() -> str:
    async with httpx.AsyncClient() as c:
        r = await c.post(
            f"{API_BASE}/api/v1/auth/login",
            data={"username": "admin", "password": "admin123"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        return r.json()["data"]["access_token"]


async def get_draft(token: str) -> dict:
    async with httpx.AsyncClient(follow_redirects=True) as c:
        r = await c.get(
            f"{API_BASE}/api/v1/wx-publisher/drafts/{DRAFT_ID}/",
            headers={"Authorization": f"Bearer {token}"},
        )
        return r.json()["data"]


async def main():
    token = await login()

    print("== 初始 DB 状态 ==")
    d = await get_draft(token)
    print(f"  account_id={d.get('account_id')} template_id={d.get('template_id')}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()
        # Capture console + network
        page.on("console", lambda msg: print(f"[{msg.type[:5]}] {msg.text[:200]}"))
        page.on("requestfailed", lambda req: print(f"[reqfail] {req.method} {req.url}"))

        await page.goto(f"{FRONTEND_BASE}/dashboard/login", wait_until="domcontentloaded")
        await page.evaluate(f"localStorage.setItem('access_token', '{token}')")

        print("\n== 进入 draft 85 ==")
        await page.goto(
            f"{FRONTEND_BASE}/dashboard/wx-publisher/drafts/{DRAFT_ID}",
            wait_until="domcontentloaded", timeout=60000,
        )
        await page.wait_for_selector("text=插入素材", timeout=60000)
        await page.wait_for_timeout(3000)
        print("  page loaded")

        # Reset via direct DB to ensure clean state
        async with httpx.AsyncClient(follow_redirects=True) as c:
            await c.put(
                f"{API_BASE}/api/v1/wx-publisher/drafts/{DRAFT_ID}/",
                json={"title": "DBG-test", "content_markdown": "DBG", "account_id": None, "template_id": None},
                headers={"Authorization": f"Bearer {token}"},
            )
        print("\n== Reset DB (account_id=None, template_id=None) ==")
        # Reload page to reflect reset
        await page.reload(wait_until="domcontentloaded")
        await page.wait_for_selector("text=插入素材", timeout=60000)
        await page.wait_for_timeout(3000)
        print("  reloaded")

        # Step 1: Select account (Subscription 小梅时间)
        print("\n== Step 1: 选账号「小梅时间」 ==")
        account_selectors = await page.evaluate('''() => {
            return Array.from(document.querySelectorAll('.ant-select-selector')).map(s => ({
                placeholder: s.querySelector('.ant-select-selection-placeholder')?.textContent,
                title: s.querySelector('.ant-select-selection-item')?.title,
            }));
        }''')
        print(f"  初始 Selects: {account_selectors}")
        # 点 Account Select — 第 1 个 ant-select
        await page.evaluate('''() => {
            const all = document.querySelectorAll('.ant-select');
            if (all[0]) all[0].querySelector('.ant-select-selector').dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
        }''')
        await page.wait_for_selector(".ant-select-dropdown:not(.ant-select-dropdown-hidden)", timeout=5000)
        await page.wait_for_timeout(500)
        # 点 "小梅时间" 选项
        await page.evaluate('''() => {
            const items = document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option');
            for (const it of items) {
                if (it.textContent && it.textContent.includes('小梅时间')) {
                    it.dispatchEvent(new MouseEvent('click', {bubbles: true}));
                    break;
                }
            }
        }''')
        await page.wait_for_timeout(2000)
        print("  selected 小梅时间")

        # Verify DB
        d = await get_draft(token)
        print(f"  DB account_id after select: {d.get('account_id')}")

        # Step 2: Select template
        print("\n== Step 2: 选模板「科技黑曜」 ==")
        await page.evaluate('''() => {
            const all = document.querySelectorAll('.ant-select');
            if (all[1]) all[1].querySelector('.ant-select-selector').dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
        }''')
        await page.wait_for_selector(".ant-select-dropdown:not(.ant-select-dropdown-hidden)", timeout=5000)
        await page.wait_for_timeout(500)
        await page.evaluate('''() => {
            const items = document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option');
            for (const it of items) {
                if (it.textContent && it.textContent.includes('科技黑曜')) {
                    it.dispatchEvent(new MouseEvent('click', {bubbles: true}));
                    break;
                }
            }
        }''')
        await page.wait_for_timeout(2000)
        d = await get_draft(token)
        print(f"  DB after template select: account_id={d.get('account_id')} template_id={d.get('template_id')}")

        # Step 3: 点保存
        print("\n== Step 3: 点保存草稿 ==")
        await page.get_by_role("button", name="保存草稿").click()
        await page.wait_for_timeout(3000)
        d = await get_draft(token)
        print(f"  DB after save: account_id={d.get('account_id')} template_id={d.get('template_id')}")

        # Step 4: 退出再进来
        print("\n== Step 4: 重新进入 draft 85 ==")
        await page.goto(
            f"{FRONTEND_BASE}/dashboard/wx-publisher/drafts/{DRAFT_ID}",
            wait_until="domcontentloaded", timeout=60000,
        )
        await page.wait_for_selector("text=插入素材", timeout=60000)
        await page.wait_for_timeout(3000)
        # Check Select 显示的值
        account_selectors = await page.evaluate('''() => {
            return Array.from(document.querySelectorAll('.ant-select-selector')).map(s => ({
                placeholder: s.querySelector('.ant-select-selection-placeholder')?.textContent,
                selectedTitle: s.querySelector('.ant-select-selection-item')?.title,
                selectedText: s.querySelector('.ant-select-selection-item')?.textContent,
            }));
        }''')
        print(f"  重新进入后 Selects: {account_selectors}")
        d = await get_draft(token)
        print(f"  DB: account_id={d.get('account_id')} template_id={d.get('template_id')}")

        await browser.close()


asyncio.run(main())