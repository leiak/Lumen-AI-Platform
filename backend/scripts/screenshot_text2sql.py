"""M33: Take screenshots of /dashboard/text2sql for visual verification.

Loads the page, logs in as admin, captures 3 screenshots:
1. Initial state (asking tab)
2. History tab
3. Data sources tab

Run: python -m scripts.screenshot_text2sql
"""
import asyncio
import os
import sys
from pathlib import Path

from playwright.async_api import async_playwright


API_BASE = "http://localhost:11335"
FRONTEND_BASE = "http://localhost:11334"
SCREENSHOTS_DIR = Path(__file__).parent.parent / "imgs" / "text2sql"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await context.new_page()

        # 1. Login via the API (form-data)
        print("Logging in as admin...")
        login_resp = await page.request.post(
            f"{API_BASE}/api/v1/auth/login",
            form={"username": "admin", "password": "admin123"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert login_resp.ok, f"login failed: {login_resp.status} {await login_resp.text()}"
        token = (await login_resp.json())["data"]["access_token"]
        print(f"  got token: {token[:30]}...")

        # 2. Inject token into localStorage so the SPA picks it up
        await page.goto(f"{FRONTEND_BASE}/dashboard/login", wait_until="domcontentloaded")
        await page.evaluate(f"localStorage.setItem('access_token', '{token}')")
        print("  token saved to localStorage")

        # 3. Navigate to text2sql page
        await page.goto(f"{FRONTEND_BASE}/dashboard/text2sql", wait_until="networkidle")
        # Give antd a moment to render the Tabs + cards
        await page.wait_for_selector("text=智能问数", timeout=10000)
        await page.wait_for_timeout(1500)

        # Screenshot 1: asking tab (default)
        out1 = SCREENSHOTS_DIR / "01-asking.png"
        await page.screenshot(path=str(out1), full_page=True)
        print(f"  saved {out1.name}")

        # Screenshot 2: history tab
        await page.click("text=历史")
        await page.wait_for_timeout(1500)
        out2 = SCREENSHOTS_DIR / "02-history.png"
        await page.screenshot(path=str(out2), full_page=True)
        print(f"  saved {out2.name}")

        # Screenshot 3: data sources tab
        await page.click("text=数据源管理")
        await page.wait_for_timeout(1500)
        out3 = SCREENSHOTS_DIR / "03-datasources.png"
        await page.screenshot(path=str(out3), full_page=True)
        print(f"  saved {out3.name}")

        # Screenshot 4: schema browser
        await page.click("text=Schema 浏览")
        await page.wait_for_timeout(2000)
        out4 = SCREENSHOTS_DIR / "04-schema.png"
        await page.screenshot(path=str(out4), full_page=True)
        print(f"  saved {out4.name}")

        await browser.close()
        print(f"\nAll screenshots saved to: {SCREENSHOTS_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
