#!/usr/bin/env python3
"""
批量导入 alirezarezvani/claude-skills 到 SkillMarketplace 表。

用法:
    cd backend
    python -m lumen_scripts.import_claude_skills [--dry-run] [--repo <path>]

    --repo  : 本地 git clone 的仓库路径（避免每次都请求 GitHub API）。
              示例: /path/to/claude-skills
    --dry-run: 只打印将要插入的记录，不实际写入数据库。

GitHub API 限速 60 req/hr，建议先用 --repo 指向本地 clone。

仓库结构（每个 skill 目录）:
    <domain>/skills/<skill-name>/
        SKILL.md          — YAML frontmatter + markdown 描述
        references/       — 额外参考文档
        scripts/          — Python 可执行工具（可选）
            *.py
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.request

# ---- DB setup ----
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lumen_core.database import SessionLocal
from lumen_models.skill_marketplace import SkillMarketplace


# ---- GitHub API ----

def gh_get(url: str) -> dict | list:
    """发 GET 请求到 GitHub API，自动处理 403/429."""
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github.v3+json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    return data


def gh_list_dir(url: str) -> list:
    """返回指定目录下的所有条目（name, type, download_url）."""
    entries = gh_get(url)
    return [
        {"name": e["name"], "type": e["type"], "url": e.get("url"), "download_url": e.get("download_url")}
        for e in entries
    ]


def gh_download(url: str) -> str:
    """下载文件内容并解码为 UTF-8 字符串."""
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
    return base64.b64decode(raw).decode("utf-8", errors="replace")


# ---- SKILL.md 解析 ----

def parse_skill_md(raw: str) -> tuple[dict, str]:
    """解析 SKILL.md，返回 ({name, description}, content).

    frontmatter 格式::
        ---
        name: "xxx"
        description: "..."
        ---
        # Markdown 内容
    """
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {"name": "unknown", "description": ""}, raw

    fm_text, content = parts[1], parts[2]
    meta: dict = {}
    for line in fm_text.strip().splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        val = val.strip().strip('"').strip("'")
        meta[key.strip()] = val

    name = meta.get("name", "unknown")
    desc = meta.get("description", "")
    return {"name": name, "description": desc}, content.strip()


# ---- 脚本内容读取 ----

def load_scripts_content(skill_dir_path: str, repo_local: str) -> str | None:
    """从本地仓库读取 scripts/ 目录下所有 .py 文件，拼成单个字符串。"""
    scripts_path = os.path.join(repo_local, skill_dir_path, "scripts")
    if not os.path.isdir(scripts_path):
        return None

    py_files = sorted(f for f in os.listdir(scripts_path) if f.endswith(".py"))
    if not py_files:
        return None

    chunks: list[str] = []
    for fname in py_files:
        fpath = os.path.join(scripts_path, fname)
        with open(fpath, encoding="utf-8", errors="replace") as f:
            chunks.append(f"# ---- {fname} ----\n{f.read()}")

    return "\n\n".join(chunks) + "\n"


def load_scripts_from_gh(skill_dir_path: str) -> str | None:
    """从 GitHub API 读取 scripts/ 目录下所有 .py 文件。"""
    api_url = f"https://api.github.com/repos/alirezarezvani/claude-skills/contents/{skill_dir_path}/scripts"
    try:
        entries = gh_list_dir(api_url)
    except Exception:
        return None

    py_entries = [e for e in entries if e["name"].endswith(".py")]
    if not py_entries:
        return None

    chunks: list[str] = []
    for e in sorted(py_entries, key=lambda x: x["name"]):
        try:
            content = gh_download(e["download_url"])
            chunks.append(f"# ---- {e['name']} ----\n{content}")
        except Exception:
            continue

    return ("\n\n".join(chunks) + "\n") if chunks else None


# ---- 主导入逻辑 ----

# 扫描哪些 domain/skills 目录
DOMAIN_SKILL_PATHS = [
    "engineering/skills",
    "business-growth/skills",
    "c-level-advisor/skills",
    "docs/skills",
    "engineering-team/skills",
    "markdown-html/skills",
    "marketing-skill/skills",
    "product-team/skills",
    "project-management/skills",
    "ra-qm-team/skills",
    "research-ops/skills",
]

# 领域 → category 映射
CATEGORY_MAP = {
    "engineering": "engineering",
    "business-growth": "business",
    "c-level-advisor": "strategy",
    "docs": "docs",
    "engineering-team": "engineering",
    "markdown-html": "tools",
    "marketing-skill": "marketing",
    "product-team": "product",
    "project-management": "management",
    "ra-qm-team": "qa",
    "research-ops": "research",
}


def import_one_skill(
    domain: str,
    skill_name: str,
    skill_dir_path: str,
    repo_local: str | None,
    dry_run: bool,
    session,
) -> SkillMarketplace | None:
    """导入单个 skill，返回 SkillMarketplace 实例或 None（跳过）。"""
    # 1. 读取 SKILL.md
    if repo_local:
        md_path = os.path.join(repo_local, skill_dir_path, "SKILL.md")
        if not os.path.exists(md_path):
            return None
        with open(md_path, encoding="utf-8", errors="replace") as f:
            raw_md = f.read()
        scripts_content = load_scripts_content(skill_dir_path, repo_local)
        references = []
        refs_path = os.path.join(repo_local, skill_dir_path, "references")
        if os.path.isdir(refs_path):
            for rf in sorted(os.listdir(refs_path)):
                if rf.endswith(".md"):
                    references.append(rf)
    else:
        api_url = f"https://api.github.com/repos/alirezarezvani/claude-skills/contents/{skill_dir_path}/SKILL.md"
        try:
            raw_md = gh_download(gh_get(api_url)["download_url"])
        except Exception:
            return None
        scripts_content = load_scripts_from_gh(skill_dir_path)
        references = []
        # references 暂时不抓（减少 API 请求）

    meta, content_md = parse_skill_md(raw_md)
    skill_name_in_meta = meta["name"]
    description = meta["description"]

    # 2. 判断 type
    is_script = scripts_content is not None
    skill_type = "script" if is_script else "prompt"
    final_content = scripts_content if is_script else content_md

    # 3. category
    category = CATEGORY_MAP.get(domain, domain)

    # 4. meta_data
    meta_data = {"domain": domain, "imported_from": "alirezarezvani/claude-skills"}
    if is_script:
        meta_data["has_scripts"] = True
    if references:
        meta_data["references"] = references

    # 5. 查重（按 name + provider）
    if dry_run:
        existing = None
    else:
        existing = session.query(SkillMarketplace).filter(
            SkillMarketplace.name == skill_name_in_meta,
            SkillMarketplace.provider == "alirezarezvani/claude-skills",
        ).first()

    if existing:
        # 更新内容
        if not dry_run:
            existing.description = description
            existing.content = final_content
            existing.category = category
            existing.type = skill_type
            existing.meta_data = meta_data
        action = "UPDATED"
    else:
        if not dry_run:
            existing = SkillMarketplace(
                name=skill_name_in_meta,
                description=description,
                category=category,
                type=skill_type,
                content=final_content,
                provider="alirezarezvani/claude-skills",
                meta_data=meta_data,
                downloads=0,
            )
            session.add(existing)
        action = "INSERT"

    if dry_run:
        print(f"  [{action}] {category}/{skill_name_in_meta}  type={skill_type}  content_len={len(final_content) if final_content else 0}")
        return True  # signal success for dry-run count
    else:
        session.commit()
        print(f"  [{action}] {category}/{skill_name_in_meta}  type={skill_type}  id={existing.id}")
        return existing

    return existing


def main():
    parser = argparse.ArgumentParser(description="Import claude-skills into SkillMarketplace")
    parser.add_argument("--repo", default="", help="Local git clone path (skip GitHub API)")
    parser.add_argument("--dry-run", action="store_true", help="Print without writing")
    parser.add_argument("--domain", default="", help="Import only this domain (e.g. engineering/skills)")
    args = parser.parse_args()

    repo = args.repo.strip() or None

    session = SessionLocal() if not args.dry_run else None

    domains_to_scan = [args.domain] if args.domain else DOMAIN_SKILL_PATHS

    total_insert = 0
    total_update = 0
    total_skip = 0

    for domain_path in domains_to_scan:
        domain = domain_path.split("/")[0]
        print(f"\nScanning {domain_path} ...")

        if repo:
            full_path = os.path.join(repo, domain_path)
            if not os.path.isdir(full_path):
                print(f"  [SKIP] not found: {full_path}")
                continue
            skill_dirs = [d for d in os.listdir(full_path)
                          if os.path.isdir(os.path.join(full_path, d)) and d != "skills"]
        else:
            url = f"https://api.github.com/repos/alirezarezvani/claude-skills/contents/{domain_path}"
            try:
                entries = gh_list_dir(url)
                skill_dirs = [e["name"] for e in entries if e["type"] == "dir"]
            except Exception as e:
                print(f"  [ERROR] {e}")
                if "403" in str(e) or "429" in str(e):
                    print("GitHub API rate limit hit. Use --repo with local clone.")
                continue

        for skill_name in sorted(skill_dirs):
            skill_dir = f"{domain_path}/{skill_name}"
            result = import_one_skill(domain, skill_name, skill_dir, repo, args.dry_run, session)
            if result is None:
                total_skip += 1
            elif args.dry_run:
                pass  # dry-run always rolls back
            else:
                # Check if it was insert or update by counting
                pass

    if session:
        session.close()
    else:
        print("(dry-run: no DB session opened)")

    print(f"\nDone. skip={total_skip}")


if __name__ == "__main__":
    main()
