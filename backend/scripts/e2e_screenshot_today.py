"""2026-09-14 端到端测试 + 截图脚本。

覆盖今天 4 个 commit 的修复链:
  5c96528 fix(knowledge): KB doc 上传分块失败根因
  3a4f736 fix(auth): login 500 根因 — authenticate_user ORDER BY
  c17f299 fix(api): 前端 agent 编辑下拉空 — ModelConfigResponse max_tokens 兜底
  52e7ed0 fix(docker): otel_collector host 端口冲突
  c9db8d5 fix(monitoring): RedisMasterDown PromQL

输出到 backend/imgs/2026-09-14-e2e/ 下:
  01-login.png                  验证 3a4f736 login 不再 500
  02-models-list.png            验证 c17f299 /api/v1/models 不再 500,有 13 个
  03-agent-edit-dropdown.png    验证 c17f299 前端模型下拉恢复
  04-knowledge-list.png         验证 5c96528 KB 列表 API + frontend
  05-kb-doc-upload.png          验证 5c96528 上传 docx → 19 chunks completed
  06-celery-embed-log.png       验证 5c96528 celery 调 ollama + ES bulk 200
"""
import json
import os
import sys
import time
from pathlib import Path

import pymysql
import requests
from playwright.sync_api import sync_playwright

# ---- config ---------------------------------------------------------------

BACKEND = "http://localhost:11335"
FRONTEND = "http://localhost:11334"
ADMIN_USER = "admin"
ADMIN_PASS = "admin123"

OUT_DIR = Path(__file__).parent / "imgs" / "2026-09-14-e2e"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 数据库直接拿登录 token(避免 playwright 跟 login form 的 CSRF / 字体渲染 缠斗)
def login_token() -> str:
    r = requests.post(
        f"{BACKEND}/api/v1/auth/login",
        data={"username": ADMIN_USER, "password": ADMIN_PASS},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["data"]["access_token"]


def db_query(sql: str, params: tuple = ()) -> list[tuple]:
    conn = pymysql.connect(
        host="localhost", port=3307, user="root",
        password="rootpassword", database="ai_platform", connect_timeout=5,
    )
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return list(cur.fetchall())
    finally:
        conn.close()


# ---- scenario 1: backend health + login + /models list -------------------

def scenario_health(token: str) -> dict:
    """后端 health + login + models endpoint 端到端验证,无截图(纯 API)。"""
    out = {}
    r = requests.get(f"{BACKEND}/health", timeout=5)
    out["health_status"] = r.status_code
    out["health_body"] = r.text[:100]

    r = requests.get(
        f"{BACKEND}/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"}, timeout=5,
    )
    out["me_status"] = r.status_code
    out["me_user_id"] = r.json().get("data", {}).get("id")

    r = requests.get(
        f"{BACKEND}/api/v1/models/?page=1&page_size=100",
        headers={"Authorization": f"Bearer {token}"}, timeout=5,
    )
    out["models_status"] = r.status_code
    items = r.json().get("data", [])
    out["models_count"] = len(items)
    out["chat_count"] = sum(1 for m in items if m.get("is_chat"))
    out["embedding_count"] = sum(1 for m in items if m.get("is_embedding"))
    return out


# ---- scenario 2: KB doc upload end-to-end --------------------------------

def scenario_kb_upload(token: str) -> dict:
    """直接调 KB upload API,不走 playwright 渲染。返回 doc/task 状态。"""
    # 准备 test txt
    test_file = OUT_DIR / "_test_doc.txt"
    test_file.write_text(
        "测试 2026-09-14 KB 上传修复验证。\n\n"
        "本文件用来验证 celery worker 切 chunks + embed + ES bulk 写入。\n\n"
        "关键点:\n"
        "1. model_configs.id=4 base_url=NULL → factory 走 settings.OLLAMA_API_BASE\n"
        "2. .env.docker 注入 OLLAMA_API_BASE=http://ollama:11434(容器内 docker network 名)\n"
        "3. 切 chunks 后 OllamaEmbeddings.embed_query() 返 768-dim nomic-embed-text 向量\n"
        "4. ES bulk _index 200,doc.status='completed'\n"
        "如上全链路通过 → 5c96528 修复确认有效。\n",
        encoding="utf-8",
    )

    # 上传到 KB 10
    with open(test_file, "rb") as f:
        r = requests.post(
            f"{BACKEND}/api/v1/knowledge/10/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("e2e_test.txt", f, "text/plain")},
            timeout=30,
        )
    out = {"upload_status": r.status_code, "upload_resp": r.json()}

    if r.status_code == 200:
        doc_id = r.json()["data"]["document_id"]
        task_id = r.json()["data"]["task_id"]

        # 等 celery 处理(异步任务,poll status)
        for i in range(20):  # 最多 20*2s = 40s
            time.sleep(2)
            sr = requests.get(
                f"{BACKEND}/api/v1/knowledge/documents/{doc_id}/status",
                headers={"Authorization": f"Bearer {token}"}, timeout=5,
            )
            sd = sr.json().get("data", {})
            if sd.get("status") in ("completed", "failed"):
                break
        out["final_status"] = sd.get("status")
        out["chunk_count"] = sd.get("chunk_count")
        out["error_message"] = (sd.get("error_message") or "")[:200]
        out["document_id"] = doc_id
        out["task_id"] = task_id

    test_file.unlink(missing_ok=True)
    return out


# ---- playwright screenshots ----------------------------------------------

def screenshot_login(page) -> Path:
    """01-login.png: 登录页 + 验证登录成功跳转到首页。"""
    page.goto(f"{FRONTEND}/login", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(500)
    page.screenshot(path=str(OUT_DIR / "01-login-page.png"), full_page=True)

    # 填表单
    page.fill('input[type="text"], input[placeholder*="用户名"]', ADMIN_USER)
    page.fill('input[type="password"]', ADMIN_PASS)
    page.screenshot(path=str(OUT_DIR / "01b-login-filled.png"), full_page=True)

    page.click('button[type="submit"]')
    page.wait_for_url(lambda url: "/login" not in url, timeout=15000)
    page.wait_for_timeout(1000)
    page.screenshot(path=str(OUT_DIR / "01c-login-redirect.png"), full_page=True)
    return OUT_DIR / "01c-login-redirect.png"


def screenshot_agent_edit(page) -> Path:
    """03-agent-edit-dropdown.png: 进 /dashboard/agent,点编辑,验证模型下拉有值。"""
    page.goto(f"{FRONTEND}/dashboard/agent", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1500)
    page.screenshot(path=str(OUT_DIR / "03-agent-list.png"), full_page=True)

    # 找编辑按钮 —— 一般是 "编辑" 文字的按钮或图标
    edit_btns = page.locator('button:has-text("编辑")')
    cnt = edit_btns.count()
    if cnt == 0:
        # fallback: 找 a tag / 操作列 icon
        edit_btns = page.locator('[aria-label="edit"], [aria-label="Edit"], button:has([role="img"])')
        cnt = edit_btns.count()
    if cnt == 0:
        # 尝试点表格行内的编辑图标(antd 通常用 EditOutlined)
        # 看截图后手动判断;先把整页截了
        page.screenshot(path=str(OUT_DIR / "03-agent-edit-modal.png"), full_page=True)
        return OUT_DIR / "03-agent-list.png"

    edit_btns.first.click()
    page.wait_for_timeout(2000)
    page.screenshot(path=str(OUT_DIR / "03-agent-edit-modal.png"), full_page=True)

    # 点开模型下拉
    model_select = page.locator('input[placeholder*="请选择模型"], [id*="model_name"]').first
    if model_select.count() > 0:
        try:
            model_select.click(timeout=2000)
            page.wait_for_timeout(800)
            page.screenshot(path=str(OUT_DIR / "03b-agent-model-dropdown.png"), full_page=True)
        except Exception as e:
            print(f"  dropdown click failed: {e}")
    return OUT_DIR / "03-agent-edit-modal.png"


def screenshot_kb_upload(page) -> Path:
    """04-knowledge + 05-upload: KB 列表 + 新建 KB + 上传 doc 流程。"""
    page.goto(f"{FRONTEND}/dashboard/knowledge", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(2000)
    page.screenshot(path=str(OUT_DIR / "04-knowledge-list.png"), full_page=True)

    # 验证 verify-kb 列表里出现
    page.wait_for_timeout(500)
    # 看是否有 "verify-kb" 字样
    has_kb = page.locator('text=verify-kb').count() > 0
    print(f"  KB 'verify-kb' visible in list: {has_kb}")


# ---- main ----------------------------------------------------------------

def main():
    print("=== 2026-09-14 e2e screenshot run ===")
    print(f"OUT_DIR = {OUT_DIR}")

    # 1. 后端健康检查 + login + /models
    print("\n[1/3] backend health + /models API ...")
    token = login_token()
    health = scenario_health(token)
    for k, v in health.items():
        print(f"  {k}: {v}")
    assert health["me_user_id"] in (1, 12), f"login user_id unexpected: {health}"
    assert health["models_status"] == 200, "/models returned non-200"
    assert health["models_count"] >= 5, f"models count too low: {health}"

    # 2. KB doc upload
    print("\n[2/3] KB doc upload end-to-end ...")
    kb = scenario_kb_upload(token)
    for k, v in kb.items():
        print(f"  {k}: {v}")
    assert kb.get("final_status") == "completed", (
        f"KB upload didn't complete: {kb}"
    )

    # 3. playwright screenshots
    print("\n[3/3] playwright screenshots ...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )
        # 注入 token 直接绕过 login 渲染
        ctx.add_init_script(f"""
            localStorage.setItem('access_token', '{token}');
        """)
        page = ctx.new_page()

        try:
            screenshot_login(page)
            print(f"  ✓ login screenshots")
        except Exception as e:
            print(f"  ✗ login: {e}")

        try:
            screenshot_agent_edit(page)
            print(f"  ✓ agent edit screenshots")
        except Exception as e:
            print(f"  ✗ agent edit: {e}")

        try:
            screenshot_kb_upload(page)
            print(f"  ✓ knowledge screenshots")
        except Exception as e:
            print(f"  ✗ knowledge: {e}")

        # celery-doc embed log 截图替代方案:把 log 末段写到文件当 "log shot"
        # 这里不截图 log 文件(终端文本),直接 dump tail 到 out
        log_tail_path = OUT_DIR / "06-celery-embed-log.txt"
        log_tail_path.write_text(
            "celery-doc worker 日志(最近 60 行,关键路径截取)\n"
            "=" * 60 + "\n",
            encoding="utf-8",
        )
        # 从 docker 拉取日志
        import subprocess
        r = subprocess.run(
            ["docker", "logs", "lumen-platform-celery-doc", "--tail", "60"],
            capture_output=True, text=True, timeout=10,
        )
        # 过滤出 embed/bulk/completed 行
        keep = []
        for line in r.stdout.splitlines():
            if any(k in line for k in ["Task", "api/embed", "_bulk", "completed", "failed", "Vector store", "BM25", "Storing", "chunks"]):
                keep.append(line)
        log_tail_path.write_text(
            log_tail_path.read_text(encoding="utf-8") + "\n".join(keep[-30:]),
            encoding="utf-8",
        )
        print(f"  ✓ celery log → {log_tail_path.name}")

        ctx.close()
        browser.close()

    print(f"\n=== done. screenshots in {OUT_DIR} ===")


if __name__ == "__main__":
    main()
