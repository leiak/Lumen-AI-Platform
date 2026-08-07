# How-to:E2E 截图验证

> 用 Playwright 把 dev 跑起来,所有页面截图下来,作为视觉回归基线。
> 适用场景:改 UI / 加新页面 / 上线前 MCP-E2E 验证。

---

## 1. 工具

| 工具 | 用途 |
|------|------|
| **Playwright** | 浏览器自动化 |
| **Chromium** | headless 浏览器 |
| **Python** | 脚本入口 |

---

## 2. 准备

### 2.1 安装

```bash
pip install playwright
playwright install chromium
```

### 2.2 启动 dev 服务

```bash
# Docker
docker compose up -d mysql redis ollama elasticsearch

# 后端
cd backend && python -m uvicorn lumen_main:app --reload --port 11335

# 前端
cd frontend && npm run dev
```

**验证**:
- `http://localhost:11335/docs` — Swagger
- `http://localhost:11334/` — Dashboard

---

## 3. 跑截图

### 3.1 全平台截图

```bash
python backend/scripts/e2e_screenshot.py --all
```

输出:`backend/storage/e2e_screenshots/<page>.png`

### 3.2 单页面

```bash
python backend/scripts/e2e_screenshot.py \
  --page /dashboard/chat \
  --output storage/screenshots/chat.png
```

### 3.3 自定义脚本

```python
# scripts/screenshot_my_page.py
from playwright.sync_api import sync_playwright
from pathlib import Path

URL = "http://localhost:11334"
TOKEN = "your-jwt-token"  # 提前 login 拿

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 900})

        # 注入 token
        context.add_init_script(f'localStorage.setItem("access_token", `{TOKEN}`)')

        page = context.new_page()
        page.goto(f"{URL}/dashboard/chat", wait_until="networkidle")
        page.wait_for_timeout(2000)  # 等动画

        out = Path("storage/screenshots/chat.png")
        out.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out), full_page=True)
        print(f"Saved: {out}")

        browser.close()

if __name__ == "__main__":
    main()
```

---

## 4. 截图目录

```
backend/storage/e2e_screenshots/
├── dashboard/
│   ├── overview.png
│   ├── chat.png
│   ├── agents.png
│   ├── knowledge/
│   ├── workflows/
│   └── ...
├── auth/
│   ├── login.png
├── settings/
└── ...
```

**不要提交到 git**(忽略 `.gitignore`):
```
storage/e2e_screenshots/
```

---

## 5. 关键页面

### 5.1 必截

| 页面 | URL |
|------|-----|
| 登录 | `/login` |
| 仪表盘 | `/dashboard` |
| Chat | `/dashboard/chat` |
| Agent 列表 | `/dashboard/agents` |
| Agent 详情 | `/dashboard/agents/{id}` |
| 知识库列表 | `/dashboard/knowledge` |
| 工作流列表 | `/dashboard/workflows` |
| 工作流画布 | `/dashboard/workflows/{id}` |
| 技能市场 | `/dashboard/skill-market` |
| 系统设置 | `/dashboard/system` |
| 通知中心 | `/dashboard/notifications` |

### 5.2 排查页面

- 登录页(防忘记)
- 错误页(404 / 500)
- 加载态(loading skeleton)
- 空状态(空列表)

---

## 6. 踩坑

### 6.1 URL swap(per-page context)

**症状**:截 30 个页面,所有图都是同一个 URL。

**根因**:同一个 context 用了多个 goto,页面刷新但 URL 没变。

**修法**:**每个 page 用独立的 context**:
```python
for path in pages:
    context = browser.new_context()
    context.add_init_script(f'localStorage.setItem("access_token", `{TOKEN}`)')
    page = context.new_page()
    page.goto(f"{URL}{path}")
    page.screenshot(path=...)
    context.close()
```

### 6.2 加载未完成

**症状**:截图里元素没渲染好。

**修法**:
```python
page.wait_for_load_state("networkidle", timeout=30000)
page.wait_for_timeout(2000)  # 等动画
```

或等特定元素:
```python
page.wait_for_selector(".ant-table-row", timeout=10000)
```

### 6.3 AntD 水印

**症状**:截图上有 "Lumen AI Platform" 水印。

**修法**:截图脚本执行时登录**同一个用户**(水印是用户 ID 哈希),对比时忽略。

### 6.4 鉴权过期

**症状**:页面跳到 `/login`。

**修法**:每次截图新 login 并塞 token。

```python
# 1. login
import requests
r = requests.post("http://localhost:11335/api/v1/auth/login",
                  json={"email": "admin@example.com", "password": "admin"})
token = r.json()["data"]["access_token"]

# 2. add init script
context.add_init_script(f"localStorage.setItem('access_token', '{token}')")
```

### 6.5 CORS 跨域

**症状**:Playwright 报 "net::ERR_FAILED" 跨域。

**原因**:本地 frontend 11334 调 backend 11335,跨端口 CORS。

**修法**:本地后端默认放行 11334,确认 `lumen_core/dynamic_cors.py` 配置。如果刚加过 origin,记得 `invalidate()`。

---

## 7. 视觉回归

### 7.1 baseline 对比

```bash
# 第一次截 → baseline
git add storage/e2e_screenshots/
git commit -m "chore: e2e screenshots baseline"

# 改 UI 后
python backend/scripts/e2e_screenshot.py --all

# 对比
python backend/scripts/diff_screenshots.py \
  --baseline HEAD~1 \
  --current HEAD \
  --output diff/
```

### 7.2 自动化

**CI**:
```yaml
- name: E2E screenshots
  run: |
    docker compose up -d
    python backend/scripts/e2e_screenshot.py --all
    python backend/scripts/diff_screenshots.py --baseline main
```

**对比算法**:
- pixel diff(快速)
- perceptual hash(抗抖动)
- 区域 diff(局部改动)

**目前**(M22):手动比较,以后升级自动对比。

---

## 8. 截图脚本模板

```python
"""E2E screenshot script for Lumen AI Platform."""
import argparse
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

API_URL = "http://localhost:11335"
FRONT_URL = "http://localhost:11334"
SCREENSHOTS_DIR = Path("backend/storage/e2e_screenshots")

# 必截页面
PAGES = [
    ("login", "/login"),
    ("dashboard", "/dashboard"),
    ("chat", "/dashboard/chat"),
    ("agents", "/dashboard/agents"),
    ("knowledge", "/dashboard/knowledge"),
    ("workflows", "/dashboard/workflows"),
    ("skill-market", "/dashboard/skill-market"),
    ("settings", "/dashboard/settings"),
    ("notifications", "/dashboard/notifications"),
    # ... 全部
]


def login(email: str = "admin@example.com", password: str = "admin") -> str:
    import requests
    r = requests.post(f"{API_URL}/api/v1/auth/login",
                      json={"email": email, "password": password})
    r.raise_for_status()
    return r.json()["data"]["access_token"]


def screenshot_one(browser, token: str, name: str, path: str):
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    context.add_init_script(f"localStorage.setItem('access_token', '{token}')")
    page = context.new_page()
    try:
        page.goto(f"{FRONT_URL}{path}", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)

        out = SCREENSHOTS_DIR / f"{name}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out), full_page=True)
        print(f"  ✓ {name}: {out}")
    except Exception as e:
        print(f"  ✗ {name}: {e}")
    finally:
        context.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="截所有页面")
    parser.add_argument("--page", help="单页面路径")
    parser.add_argument("--name", help="单页面文件名")
    args = parser.parse_args()

    token = login()

    with sync_playwright() as p:
        browser = p.chromium.launch()

        if args.page:
            name = args.name or args.page.strip("/").replace("/", "_")
            screenshot_one(browser, token, name, args.page)
        elif args.all:
            for name, path in PAGES:
                screenshot_one(browser, token, name, path)
        else:
            parser.print_help()
            sys.exit(1)

        browser.close()


if __name__ == "__main__":
    main()
```

---

## 9. 性能

- 每个页面 ~3-5 秒
- 30 个页面 = 2-3 分钟
- 加并发:`browser.new_context()` × N(浏览器一个,多 context)

```python
from concurrent.futures import ThreadPoolExecutor

with ThreadPoolExecutor(max_workers=4) as ex:
    list(ex.map(lambda p: screenshot_one(browser, token, *p), PAGES))
```

---

## 10. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| 截图全黑 | 浏览器没起来 | `playwright install chromium` |
| 跳到登录页 | token 无效 | 重新 login |
| 页面没渲染 | 跨域 / 加载慢 | 加 `wait_for_timeout` |
| 元素被截断 | viewport 太小 | 改 1440x900 |
| TypeError 'NoneType' | 元素没找到 | 加 `wait_for_selector` |
| 截图全白 | 加载动画卡住 | 关 antd 动画 |
| 跨 origin 不通 | CORS 没配 | 改 `dynamic_cors` |

---

**相关文档**
- [uvicorn-zombie.md](../troubleshooting/uvicorn-zombie.md)
- [common-errors.md](../troubleshooting/common-errors.md)

**维护者**:全栈架构师
**最近更新**:2026-08-06
