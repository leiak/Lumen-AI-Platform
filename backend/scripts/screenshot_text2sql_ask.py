"""M33: Capture a full ask flow with result rendering.

Triggers a real ask via the UI, waits for the result block, and
takes a screenshot showing SQL + result table + explanation card.
"""
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright


API_BASE = "http://localhost:11335"
FRONTEND_BASE = "http://localhost:11334"
OUT = Path(__file__).parent.parent / "imgs" / "text2sql" / "05-ask-result.png"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 1400})
        page = await context.new_page()

        # Login
        login = await page.request.post(
            f"{API_BASE}/api/v1/auth/login",
            form={"username": "admin", "password": "admin123"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        token = (await login.json())["data"]["access_token"]

        # Open the page with token
        await page.goto(f"{FRONTEND_BASE}/dashboard/login", wait_until="domcontentloaded")
        await page.evaluate(f"localStorage.setItem('access_token', '{token}')")
        await page.goto(f"{FRONTEND_BASE}/dashboard/text2sql", wait_until="networkidle")
        await page.wait_for_selector("text=智能问数", timeout=10000)
        await page.wait_for_timeout(1500)

        # Click the "默认 ai_platform" data source button (the seed
        # default). Without this the page falls back to the first
        # test_del_* row in the list, which is not what we want.
        await page.get_by_role("button", name="默认 ai_platform").click()
        await page.wait_for_timeout(500)

        # Select the default data source (already selected by default).
        # Type a question and submit via keyboard (Enter triggers the
        # onSubmit handler — same as clicking the disabled 提问 button)
        textarea = page.locator("textarea").first
        await textarea.fill("ai_platform 库里有几个用户?")
        print("Question typed, pressing Enter...")
        await textarea.press("Enter")

        # Wait for the result to appear. The page renders an Alert with
        # status="success" or status="failed" / "rejected". For
        # success we look for the SQL card heading.
        # The whole ask cycle is slow with qwen2.5:0.5b (~45s).
        print("Waiting for result (this can take 30-60s on CPU)...")
        try:
            await page.wait_for_selector("text=SQL", timeout=120_000)
            print("  SQL card appeared")
        except Exception as e:
            print(f"  Timeout waiting for SQL card: {e}")
            # Capture error state anyway
            await page.screenshot(path=str(OUT), full_page=True)
            await browser.close()
            return

        # Wait a beat for the result table + explanation to render
        await page.wait_for_timeout(3000)

        await page.screenshot(path=str(OUT), full_page=True)
        print(f"  saved {OUT.name}")

        # Also capture the explanation card area only
        await page.screenshot(
            path=str(OUT.parent / "06-ask-explanation.png"),
            full_page=True,
        )
        print(f"  saved 06-ask-explanation.png")

        await browser.close()
        print(f"\nDone. Result saved to: {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
