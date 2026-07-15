"""2026-06-29 — 验证「草稿编辑器插入素材」UI 流程 + 截图.

流程:
  1. API 登录 admin
  2. seed 3 条手动素材(走 POST /wx-publisher/materials)
  3. 浏览器注入 token 到 localStorage → 打开 /dashboard/wx-publisher/drafts/85
  4. 截图 1: draft 85 初始状态(应看到 [插入素材] 按钮在左侧章节树)
  5. 点 [插入素材] → 截图 2: MaterialPickerModal(列表 3 条素材)
  6. 点第一条素材 → 等 modal 自动关闭 + 内容更新
  7. 截图 3: 章节内容已追加 separator + heading + material body

运行: python -m scripts.screenshot_draft_insert_material
"""
import asyncio
import json
from pathlib import Path

import httpx
from playwright.async_api import async_playwright


API_BASE = "http://localhost:11335"
FRONTEND_BASE = "http://localhost:11334"
DRAFT_ID = 85
SCREENSHOTS_DIR = Path(__file__).parent.parent / "imgs" / "wx_publisher_insert_material"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


SEED_MATERIALS = [
    {
        "title": "AI Agent 行业洞察 - 数据点",
        "content": (
            "**2026 Q1 数据**:全球 AI Agent 市场规模达 $42B,同比增长 187%。\n\n"
            "头部企业市占率:OpenAI 28% / Anthropic 19% / Microsoft 15%。\n\n"
            "中国市场:百度 / 阿里 / 字节 / 腾讯合计 47%,企业自建 Agent 渗透率达 32%。"
        ),
        "tags": ["AI", "行业洞察", "Q1"],
    },
    {
        "title": "MCP 协议要点速记",
        "content": (
            "MCP (Model Context Protocol) = Anthropic 推出的 tool-use 标准协议,JSON-RPC 2.0 over stdio / SSE / HTTP。\n\n"
            "三大原语:Tools(函数调用)/ Resources(结构化数据)/ Prompts(模板 prompt)。"
        ),
        "tags": ["MCP", "技术"],
    },
    {
        "title": "公众号开头金句模板",
        "content": (
            "如果你是 ____,那么这篇文章,千万别错过。\n\n"
            "今天我们聊聊 ____,看完你会得到 3 个意想不到的答案。"
        ),
        "tags": ["文案", "开头"],
    },
]


async def login() -> str:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{API_BASE}/api/v1/auth/login",
            data={"username": "admin", "password": "admin123"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        r.raise_for_status()
        return r.json()["data"]["access_token"]


async def seed_materials(token: str) -> list[int]:
    """清掉之前测过的 demo 素材(以 'AI Agent 行业洞察' / 'MCP 协议要点' /
    '公众号开头金句模板' 为 key — 都是这一轮 seed 的),然后 seed 3 条新的,
    返回 id 列表。避免 dev DB 反复跑残留一堆。

    注意:/materials list 返的是**老式扁形**:`{code, message, data: [list],
    total, page, page_size}` — 不是 PaginatedResponse 信封
    (data.items)。同 MEMORY.md 记的 /models/?is_embedding=true 模式。
    """
    async with httpx.AsyncClient(follow_redirects=True) as client:
        headers = {"Authorization": f"Bearer {token}"}
        # 清掉旧的 demo 素材
        r = await client.get(
            f"{API_BASE}/api/v1/wx-publisher/materials/",
            params={"page": 1, "page_size": 100},
            headers=headers,
        )
        r.raise_for_status()
        existing = r.json()["data"]  # 扁形:直接是 list
        for m in existing:
            if m["title"] in [s["title"] for s in SEED_MATERIALS]:
                await client.delete(
                    f"{API_BASE}/api/v1/wx-publisher/materials/{m['id']}",
                    headers=headers,
                )
                print(f"  cleaned existing material id={m['id']} '{m['title']}'")
        # seed 3 条新的
        ids = []
        for s in SEED_MATERIALS:
            r = await client.post(
                f"{API_BASE}/api/v1/wx-publisher/materials/",
                json=s,
                headers=headers,
            )
            r.raise_for_status()
            ids.append(r.json()["data"]["id"])
            print(f"  seeded material id={ids[-1]} '{s['title']}'")
        return ids


async def main():
    print("== 登录 ==")
    token = await login()
    print(f"  token: {token[:30]}...")

    print("\n== Seed 3 条素材 ==")
    material_ids = await seed_materials(token)
    print(f"  ids: {material_ids}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()

        # 把 token 注入 localStorage
        await page.goto(f"{FRONTEND_BASE}/dashboard/login", wait_until="domcontentloaded")
        await page.evaluate(f"localStorage.setItem('access_token', '{token}')")
        print("\n== 注入 token ==")

        # 打开 draft 85
        print(f"\n== 打开 /dashboard/wx-publisher/drafts/{DRAFT_ID} ==")
        # 首次进 dev 模式编译 MDEditor 很慢,不用 networkidle (会等到所有
        # fetch 完成 / SSE 关闭,可能 > 60s)。domcontentloaded + 等具体 selector
        # 更稳。
        await page.goto(
            f"{FRONTEND_BASE}/dashboard/wx-publisher/drafts/{DRAFT_ID}",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        # 等标题渲染 + 章节树 + (按钮)
        await page.wait_for_selector("text=插入素材", timeout=60000)
        await page.wait_for_timeout(3000)  # 等 MDEditor dynamic import 完成
        out1 = SCREENSHOTS_DIR / "01-draft85-initial.png"
        await page.screenshot(path=str(out1), full_page=True)
        print(f"  saved {out1.name}")

        # 点 [插入素材] 按钮 — 第一个章节 (一、背景) 默认激活
        print("\n== 点击 [插入素材] ==")
        # SectionTree 顶部 toolbar 的 [插入素材] 按钮
        # 不能用 text=插入素材 因为也会匹配到 modal 标题里的"从素材库选择"
        # 用更精准的 selector: 在左侧 Card 内的按钮
        insert_btns = page.locator("button", has_text="插入素材")
        await insert_btns.first.click()
        # 等 modal 渲染 + 列表加载
        await page.wait_for_selector("text=从素材库选择", timeout=10000)
        # 等 materialApi.list 解析 + 3 条素材渲染
        await page.wait_for_selector(f"text={SEED_MATERIALS[0]['title']}", timeout=10000)
        await page.wait_for_timeout(800)
        out2 = SCREENSHOTS_DIR / "02-picker-modal-open.png"
        await page.screenshot(path=str(out2), full_page=True)
        print(f"  saved {out2.name}")

        # 点第一条素材的 [插入到章节] 链接
        print("\n== 选第一条素材 ==")
        # MaterialList 里每行最右 [插入到章节] link button
        # 用 getByRole 限定 button name
        pick_btn = page.get_by_role("button", name="插入到章节").first
        await pick_btn.click()
        # 等 modal 关 + 章节内容更新
        await page.wait_for_selector("text=从素材库选择", state="detached", timeout=10000)
        # MDEditor textarea 应该含 separator + heading + content
        await page.wait_for_function(
            """() => {
                const ta = document.querySelector(
                    '.w-md-editor-text-input, .w-md-editor textarea'
                );
                return ta && ta.value.includes('---') && ta.value.includes('AI Agent 行业洞察');
            }""",
            timeout=10000,
        )
        await page.wait_for_timeout(1500)  # debounce preview
        out3 = SCREENSHOTS_DIR / "03-after-insert.png"
        await page.screenshot(path=str(out3), full_page=True)
        print(f"  saved {out3.name}")

        # 验证 textarea 实际内容
        textarea_value = await page.evaluate(
            """() => {
                const ta = document.querySelector(
                    '.w-md-editor-text-input, .w-md-editor textarea'
                );
                return ta ? ta.value : null;
            }"""
        )
        if textarea_value is None:
            print("\n  ⚠ 找不到 MDEditor textarea")
        else:
            print("\n== 章节 content_markdown 已更新 ==")
            # 打印关键片段 — 用 ASCII 字符避免 Windows GBK 编码错
            for marker in ["---", "**AI Agent 行业洞察**", "$42B", "Q1 数据"]:
                present = marker in textarea_value
                tag = "[OK]" if present else "[MISSING]"
                print(f"    {tag} contains '{marker}'")

        # 最后再 dump 一次 DB 看 draft content 是不是真持久化了
        # 注意:handleInsertMaterial 只更新本地 state + react-query cache,
        # **不会**自动写后端。要落库必须点「保存草稿」按钮 — 这一步验证
        # 点保存后端正常持久化。
        print("\n== 点 [保存草稿] 按钮落库 ==")
        await page.get_by_role("button", name="保存草稿").click()
        # 等 toast「已保存」 + refetch 完成
        await page.wait_for_selector("text=已保存", timeout=10000)
        await page.wait_for_timeout(1500)
        out4 = SCREENSHOTS_DIR / "04-after-save.png"
        await page.screenshot(path=str(out4), full_page=True)
        print(f"  saved {out4.name}")

        async with httpx.AsyncClient(follow_redirects=True) as client:
            r = await client.get(
                f"{API_BASE}/api/v1/wx-publisher/drafts/{DRAFT_ID}/",
                headers={"Authorization": f"Bearer {token}"},
            )
            draft = r.json()["data"]
            section0 = draft["sections"][0]
            print(f"\n== DB section 0 ('{section0['heading']}') 持久化结果 ==")
            for marker in ["---", "AI Agent 行业洞察", "$42B", "Q1 数据"]:
                present = marker in section0["content_markdown"]
                tag = "[OK]" if present else "[MISSING]"
                print(f"    {tag} contains '{marker}'")
            print(f"    length: {len(section0['content_markdown'])} chars (was 72 before insert)")

        await browser.close()
        print(f"\n== 完成,截图保存在: {SCREENSHOTS_DIR} ==")


if __name__ == "__main__":
    asyncio.run(main())