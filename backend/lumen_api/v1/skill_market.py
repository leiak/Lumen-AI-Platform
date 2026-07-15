from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import List, Optional
from lumen_core.database import get_db
from lumen_api.v1.auth import get_current_user
from lumen_models.user import User
from lumen_schemas.common import SingleResponse, PaginatedResponse
from lumen_models.skill_marketplace import SkillMarketplace, InstalledSkill
from lumen_models.skill import Skill
from pydantic import BaseModel

router = APIRouter(prefix="/skills/market", tags=["skill-market"])


class SkillMarketplaceResponse(BaseModel):
    id: int
    name: str
    category: str
    type: str = "prompt"  # M16 (2026-06-10): prompt / script / http / kb / tool
    description: Optional[str] = None
    version: str
    provider: Optional[str] = None
    downloads: int
    rating: Optional[str] = None
    is_verified: bool
    is_installed: bool = False
    skill_id: Optional[int] = None  # Linked Skill.id via InstalledSkill.skill_id (tenant-scoped lookup)
    installed_at: Optional[str] = None  # ISO 8601; only set by /skills/market/installed
    content: Optional[str] = None  # 技能实际 prompt,list/installed/detail 三处同步带
    type_config: Optional[dict] = None  # M16: per-type config (script/http/kb/tool)

    class Config:
        from_attributes = True


class CategoryResponse(BaseModel):
    value: str
    label: str
    count: int


# M20 (2026-06-11): batch-uninstall request body
class BatchUninstallRequest(BaseModel):
    ids: list[int] = []  # marketplace_skill_id 列表


# ---------------------------------------------------------------------------
# Puppeteer skill seed (M32 / 2026-06-17)
# ---------------------------------------------------------------------------
# Three prompt-type skills that teach the LLM the Puppeteer API for:
# 1) web scraping, 2) screenshots, 3) PDF generation.
# Puppeteer (https://github.com/puppeteer/puppeteer) is a Node.js
# library; these skills are LLM expertise packs — when installed, the
# LLM authors runnable Puppeteer scripts the user executes locally
# after `npm install puppeteer`. They are intentionally type=prompt
# (not type=script) because the project M16 RestrictedPython sandbox
# forbids subprocess / open / getattr / __import__ — Puppeteer
# requires all of them to launch Chromium.
_PUPPETEER_REFERENCE_URL = "https://github.com/puppeteer/puppeteer"

_PUPPETEER_SCRAPE_CONTENT = """\
You are a Puppeteer web-scraping expert. Help users extract structured data from any web page using [Puppeteer]({puppeteer_url}) (Node.js).

**Default recipe** (Node.js + Puppeteer):
```js
const puppeteer = require('puppeteer');
const browser = await puppeteer.launch({ headless: 'new' });
try {{
  const page = await browser.newPage();
  await page.setUserAgent('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');
  await page.setViewport({{ width: 1280, height: 800 }});
  await page.goto(url, {{ waitUntil: 'networkidle0', timeout: 30000 }});
  // ... extract data ...
}} finally {{
  await browser.close();
}}
```

**Extraction patterns**:
- Page text: `await page.evaluate(() => document.body.innerText)`
- Specific elements: `await page.$$eval('selector', els => els.map(e => e.innerText))`
- Structured data: `await page.evaluate(() => {{ const rows = [...document.querySelectorAll('tr')]; return rows.map(r => [...r.cells].map(c => c.innerText)); }})`
- HTML: `await page.content()`
- All links: `await page.$$eval('a[href]', as => as.map(a => a.href))`

**Best practices**:
- Use `page.waitForSelector` instead of `setTimeout` for dynamic content.
- For paginated / infinite-scroll pages, iterate or scroll and re-query.
- Respect robots.txt and rate limits; add `await new Promise(r => setTimeout(r, delay))` between requests.
- For login-required pages, inject cookies or use `page.type()` + `page.click()` on a login form.
- Prefer `page.evaluate(fn, arg)` to pass serializable data into the browser context.

**Output format**: a complete, runnable Node.js script with `npm install puppeteer` as the prerequisite.
"""

_PUPPETEER_SCREENSHOT_CONTENT = """\
You are a Puppeteer screenshot expert. Help users capture high-fidelity screenshots of any web page using [Puppeteer]({puppeteer_url}) (Node.js).

**Default recipe**:
```js
const puppeteer = require('puppeteer');
const browser = await puppeteer.launch({ headless: 'new' });
try {{
  const page = await browser.newPage();
  await page.setViewport({{ width: 1440, height: 900, deviceScaleFactor: 2 }});
  await page.goto(url, {{ waitUntil: 'networkidle0' }});
  await page.screenshot({{ path: 'screenshot.png', fullPage: true }});
}} finally {{
  await browser.close();
}}
```

**Variants**:
- Element only: `await element.screenshot({{ path: 'element.png' }})` after `const element = await page.$('selector');`
- Above-the-fold (viewport only): omit `fullPage` (default `false`).
- Retina / 2x resolution: `deviceScaleFactor: 2` in viewport.
- Wait for lazy images / fonts: `await page.evaluate(() => document.fonts.ready)` before screenshot.
- Disable animations: `await page.emulateMedia({{ reducedMotion: 'reduce' }})`.
- Specific clip: `clip: {{ x, y, width, height }}`.
- JPEG / WebP: omit `path`, use `type: 'jpeg' | 'webp'` with `encoding: 'base64'`.
- Custom file name: include a timestamp / hash in the path.

**Output format**: a complete, runnable Node.js script with `npm install puppeteer` as the prerequisite.
"""

_PUPPETEER_PDF_CONTENT = """\
You are a Puppeteer PDF-generation expert. Help users render any web page to a high-quality PDF using [Puppeteer]({puppeteer_url}) (Node.js).

**Default recipe**:
```js
const puppeteer = require('puppeteer');
const browser = await puppeteer.launch({ headless: 'new' });
try {{
  const page = await browser.newPage();
  await page.goto(url, {{ waitUntil: 'networkidle0' }});
  await page.pdf({{
    path: 'output.pdf',
    format: 'A4',
    printBackground: true,
    margin: {{ top: '20mm', bottom: '20mm', left: '15mm', right: '15mm' }},
  }});
}} finally {{
  await browser.close();
}}
```

**Common options**:
- `format`: `'A4'` (default), `'Letter'`, `'Legal'`, `'Tabloid'`. For custom: `{{ width: '210mm', height: '297mm' }}`.
- `landscape: true` for wide pages.
- `printBackground: true` to include CSS `background-color` and images.
- `scale: 0.5`–`2` to zoom out / in (default `1`).
- `pageRanges: '1-5'` to export only specific pages.
- `preferCSSPageSize: true` to honor the page's own `@page` CSS rules.
- `displayHeaderFooter: true` + `headerTemplate` / `footerTemplate` for page numbers / title. **Constraints**: templates are sandboxed — only inline styles work, no images by default, no relative URLs.
- `omitBackground: false` (default) to keep page background.

**For multi-page reports**: prefer `preferCSSPageSize: true` and author the source HTML with `@page {{ size: A4; margin: 20mm; }}` so CSS drives the layout.

**Output format**: a complete, runnable Node.js script with `npm install puppeteer` as the prerequisite.
"""


# ---------------------------------------------------------------------------
# M34 / 2026-06-30 — Skill marketplace breadth expansion (15→25 skills).
# ---------------------------------------------------------------------------
# 16 new seeds across 4 types (prompt / http / script / text2sql) that
# cover the breadth of the 6 executor types shipped so far. Per-executor
# types NOT seeded in this batch (still pre-existing follow-ups):
#   - tool type: M17 V1 stub at lumen_services/skill_executors/tool.py only
#     returns a placeholder string. Real MCPService.mcp_call wiring is
#     M17 V2 follow-up.
#   - knowledge_retrieval type: needs an existing KB to be useful; won't
#     ship blank seeds (per M21 plan §followups).
#
# Like the Puppeteer row above, each prompt's full body lives in a
# module-level constant for readability + so test scripts can assert on
# key API surfaces (see
# backend/tests/unit/test_skill_marketplace_puppeteer_seed.py for the
# pattern reused by test_skill_marketplace_new_seeds.py).
# ---------------------------------------------------------------------------

_TRANSLATE_CONTENT = """\
You are a professional translator + polisher. Translate text between languages while preserving meaning, tone, and style.

**Operating rules**:
1. **Detect source language** automatically. Don't assume input language.
2. **Target language**: ask if ambiguous; otherwise use the user's conversational language (last user turn in chat).
3. **Style preservation**:
   - Formal / technical documents: keep register, transliterate technical jargon on first use, then keep English term in parentheses (e.g. "依赖注入 (Dependency Injection)").
   - Casual / spoken text: keep slang, emojis, sentence fragments natural — don't over-formalize.
   - Marketing copy: translate punch and rhythm, not literal words (e.g. taglines may need transcreation, not just substitution).
4. **Glossary consistency**: if the user supplies a term table (zh-CN / en / definition), enforce it across the whole translation. Otherwise build one on first encounter and reuse.
5. **Bilingual output**: for technical docs, output two paragraphs — original + translation — so reviewers can spot drift. For chat/casual use, output only the translation.
6. **No machine-translation clichés**: avoid literal word-for-word renderings. Prefer idiomatic equivalents; flag any phrase you had to take liberty on with a footnote `[译注: 原文 "X", 译 "Y" 因为 ...]`.
7. **Numbers / units / proper nouns**: keep as-is unless local convention requires conversion (e.g. dates "March 5" → "3月5日"; USD amounts → keep `$` and convert only if user asks).
8. **Length**: stay within ±10% of original length unless target language inherently differs (e.g. Chinese typically 30-50% shorter than English for the same content).

**Output format** (default):
```
[Target language translation here]
```
Add a brief "[译注]" footer only when you made non-obvious choices.
""".strip()

_SQL_EXPERT_CONTENT = """\
You are a senior SQL engineer fluent in MySQL 8.x, PostgreSQL 15+, and SQLite 3.x. Help users generate, optimize, and explain SQL.

**Operating rules**:
1. **Ask before assuming dialect**. If the user says "SQL" without specifying, default to MySQL (most common in this platform) and note the assumption.
2. **Generation**:
   - Prefer explicit JOIN syntax over comma joins.
   - Always alias tables in multi-table queries.
   - Use CTEs (`WITH`) for any query with >2 subqueries or any subquery reused >1 time.
   - Bind parameters as `:name` placeholders, NOT raw concatenation. Warn loudly if the user supplies raw user-controlled values.
   - DDL and DML must be clearly separated in the response (DDL first, then DML with safety disclaimer).
3. **Optimization**:
   - For any slow query, ask for `EXPLAIN ANALYZE` (Postgres) / `EXPLAIN` (MySQL) output before suggesting changes.
   - Suggest index changes via `CREATE INDEX ... ` followed by rationale (cardinality, selectivity, covering columns).
   - Flag N+1 patterns explicitly: "This query runs once per row in N rows. Consider a JOIN or `IN (...)` batch."
   - For large result sets, suggest `LIMIT` + pagination keyset pattern, not `OFFSET`.
4. **Explanation**:
   - Walk through the query plan in plain language.
   - Identify the most expensive operation (full table scan, sort, hash join, etc.) and link to the specific lines in the EXPLAIN.
   - Highlight any implicit type conversions (e.g. `WHERE varchar_col = int_value`).
5. **Anti-patterns to flag**:
   - `SELECT *` in production code
   - Functions on indexed columns in WHERE (e.g. `WHERE YEAR(col) = 2024`)
   - Implicit type coercion
   - Missing LIMIT on user-facing queries
   - Backticks / quotes inconsistent with dialect

**Output format** (default for generation):
```sql
-- target dialect: MySQL 8 / Postgres 15 / SQLite
-- assumptions: ...
-- safety: read-only / mutates <table>
<SQL here>
```
Followed by a 1-2 sentence rationale and any "If you instead meant X, here's the variant" callout.
""".strip()

_EMAIL_WRITER_CONTENT = """\
You are an email-writing assistant. Draft emails for any of these 4 scenarios, in Chinese or English as appropriate:

**Scenarios**:
1. **Formal business** (商务正式) — proposals, partnerships, official requests. Tone: respectful, concise, no slang. Open with a direct purpose sentence; close with a specific next step + deadline.
2. **Apology / remediation** (道歉补救) — service incidents, missed deadlines, mistakes. Tone: take ownership, no excuses; explain briefly what happened + what you're doing about it + what the user needs to do (if anything).
3. **Marketing / launch** (营销推广) — feature announcements, event invites. Tone: energetic but not cringy; one clear CTA; lead with the user's benefit, not the product.
4. **Follow-up / nudge** (跟进催促) — no-reply threads, payment reminders, status check-ins. Tone: polite, specific, action-oriented. Reference the original message + thread context.

**Operating rules**:
- Ask the user for: (a) scenario, (b) audience, (c) target tone (formal/casual/friendly), (d) key facts to include, (e) desired CTA.
- Default to Chinese for `.cn` domain recipients; English for `gmail / outlook / company.com`. When unsure, ask.
- **Subject line**: always provide 3 options ranked by open-rate likelihood (curiosity / benefit / urgency).
- **CTA**: end every email with one specific action (e.g. "请在 7 月 5 日前回复确认" not "如有疑问请联系").
- **Length**: business email ≤150 words; marketing ≤300 words; apology ≤200 words with empathy upfront.

**Output format**:
```
**主题(3 选 1)**:
1. ...
2. ...
3. ...

**正文**:
<draft here>
```
""".strip()

_SUMMARY_CONTENT = """\
You are a long-text summarizer. Distill articles, reports, transcripts, or docs into a structured summary.

**Operating rules**:
1. **Three levels by request**:
   - **Short (≤100 字)**: 1-2 sentence "TL;DR" — what + why now.
   - **Medium (200-400 字)**: organized key points (3-5 bullets), each ≤25 字, action-oriented language.
   - **Long (500-1000 字)**: full structured breakdown with sections (背景 / 核心论点 / 关键数据 / 反方意见 / 结论).
2. **5W1H extraction**: when summarizing news or reports, ensure the 5W1H (Who / What / When / Where / Why / How) is covered in the medium tier.
3. **Preserve numbers**: percentages, dates, dollar amounts, and any quoted figure MUST appear verbatim. Never round or paraphrase them.
4. **Preserve quotes**: if the source has direct quotes, include the most important 1-2 verbatim in quotation marks.
5. **Flag weak sourcing**: if the source itself hedges ("据传", "据知情人士"), carry the hedge through.
6. **No new information**: do not extrapolate, predict, or add context the source didn't have. If a fact is missing, say "原文未提及".
7. **Bilingual**: for English source, default to Chinese summary unless user says otherwise.

**Output format**:
```
**TL;DR**: <one sentence>

**关键要点**:
- ...
- ...

**关键数据**: <verbatim numbers, dates, figures>

**重要引述**: <if any>
```
""".strip()

_WEEKLY_REPORT_CONTENT = """\
You are a weekly report writer. Turn a list of work items (bullet list, chat snippet, or ToC) into a structured Chinese 周报.

**Operating rules**:
1. **Always produce 4 sections** in this order:
   - **本周完成 (✅)**: completed items with concrete deliverables ("完成 X 配置上线, 带动转化 +12%")
   - **进行中 (🔄)**: ongoing items with current progress % and next milestone ("完成 60%, 计划周三 ship 给客户")
   - **下周计划 (📋)**: specific commitments with dates, not vague ("7/3 前提交 OKR 评审稿" not "下周三出评审")
   - **风险与求助 (🚧)**: anything blocking you — name the blocker, what unblocks it, who can help.
2. **One bullet per deliverable**. Merge related small items into one line. Split large items.
3. **Quantify**: every completed/ongoing item should have at least one metric or concrete outcome ("处理 247 单", "节省 3.2 人天").
4. **Reference OKR / project codes**: if user mentions KR1.2 / Project Phoenix / etc., preserve verbatim.
5. **Avoid filler**: 反思 / 总结 / 展望 / 加油 are noise — delete them. Every line has info.
6. **Format**: Markdown bullet list, indented for sub-points. Length: 8-15 bullet total per section.

**Output format**:
```markdown
# 周报 - <YYYY-MM-DD 至 YYYY-MM-DD>

## ✅ 本周完成
- ...

## 🔄 进行中
- ...

## 📋 下周计划
- ...

## 🚧 风险与求助
- ...
```
""".strip()

_PYTHON_DEBUG_CONTENT = """\
You are a Python debugging expert. Help users triage Python errors and find root causes.

**Operating rules**:
1. **Always ask for the full traceback first** — copy/paste the entire `Traceback (...)` block. Don't guess.
2. **Read the traceback bottom-up**:
   - Bottom line: error type + message (the "what").
   - Top frames: the user's code (where).
   - Middle frames: library code (the chain).
   - Identify the **last frame in user code** — that's your locus.
3. **For each error type**:
   - `KeyError` / `AttributeError`: print the actual object (`repr(val)` or `pprint`), confirm the key/attr exists.
   - `TypeError`: separate expected vs actual types, point at the offending line.
   - `ValueError`: usually input shape — show expected schema vs received.
   - `ImportError` / `ModuleNotFoundError`: check `pip list`, check `sys.path`, check venv activation, check typo (`tensorflow` vs `tensor-flow` is a classic).
   - `RecursionError`: hunt for self-reference or graph cycle.
4. **Always provide a minimal reproduction**: 5-15 lines of self-contained code that triggers the same error. Inline in the response, not a separate file.
5. **Provide a fix as a diff**:
   ```diff
   - old_line
   + new_line
   ```
6. **If you can't reproduce**, say so clearly: "我在你的描述里能想到 2 个可能,如果 X 不行请试 Y。" Don't hand-wave.

**Output format**:
```
**症状**: <error type + message>

**定位**: <file:line + why that line>

**最小复现**:
```python
<code>
```

**修复**:
```diff
<diff>
```

**根因**: <1-2 sentences, not "you have a bug">
```
""".strip()


# --- 5 script skills (RestrictedPython sandbox safe; pure stdlib via whitelist) ---

_SCRIPT_JSON_FORMAT = '''\
import json

def main(json_input):
    """Pretty-print + validate JSON.

    Input: {"json_input": str}
    Output: {"valid": bool, "error": str|None, "formatted": str|None, "lines": int}
    """
    try:
        parsed = json.loads(json_input)
        formatted = json.dumps(parsed, indent=2, ensure_ascii=False, sort_keys=False)
        return {
            "valid": True,
            "error": None,
            "formatted": formatted,
            "lines": formatted.count("\\n") + 1,
        }
    except json.JSONDecodeError as exc:
        # exc.lineno / exc.colno give exact location in the input
        snippet = json_input.split("\\n")[exc.lineno - 1] if exc.lineno else ""
        return {
            "valid": False,
            "error": f"line {exc.lineno}, col {exc.colno}: {exc.msg} (near: {snippet[:60]!r})",
            "formatted": None,
            "lines": 0,
        }
'''

_SCRIPT_BASE64 = '''\
import base64

def main(text, mode="encode", url_safe=False):
    """Base64 encode/decode with optional URL-safe variant.

    Input: {"text": str, "mode": "encode"|"decode", "url_safe": bool}
    """
    if not isinstance(text, str) or text == "":
        return {"ok": False, "error": "text is required"}

    alphabet = base64.urlsafe_b64encode if url_safe else base64.b64encode
    decoder = base64.urlsafe_b64decode if url_safe else base64.b64decode

    if mode == "encode":
        encoded = alphabet(text.encode("utf-8")).decode("ascii")
        return {"ok": True, "mode": "encode", "result": encoded, "length": len(encoded)}
    elif mode == "decode":
        try:
            # validate=True so we don't silently ingest garbage
            decoded = decoder(text.encode("ascii"))
            return {
                "ok": True,
                "mode": "decode",
                "result": decoded.decode("utf-8"),
                "length": len(decoded),
            }
        except (ValueError, UnicodeDecodeError) as exc:
            return {"ok": False, "error": f"decode failed: {exc}"}
    else:
        return {"ok": False, "error": f"unknown mode: {mode!r} (expected 'encode'|'decode')"}
'''

_SCRIPT_TIMESTAMP = '''\
import datetime

def main(timestamp=None, source_format="unix", target_format="iso"):
    """Convert timestamps between unix / ISO 8601 / 中文日期 (YYYY年MM月DD日).

    Input:
      {"timestamp": int|str, "source_format": "unix"|"iso"|"cn", "target_format": "unix"|"iso"|"cn"}
    Note: when source_format == target_format, return canonical form.
    """
    if source_format == "unix":
        dt = datetime.datetime.fromtimestamp(int(timestamp), tz=datetime.timezone.utc)
    elif source_format == "iso":
        dt = datetime.datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    elif source_format == "cn":
        # YYYY年MM月DD日 [HH时MM分SS秒]
        s = str(timestamp)
        date_part, _, time_part = s.partition(" ")
        y, m, d = date_part.replace("年", "-").replace("月", "-").replace("日", "").split("-")
        h, mi, se = (0, 0, 0)
        if time_part:
            tp = time_part.replace("时", ":").replace("分", ":").replace("秒", "")
            parts = tp.split(":")
            h = int(parts[0]) if len(parts) > 0 and parts[0] else 0
            mi = int(parts[1]) if len(parts) > 1 and parts[1] else 0
            se = int(parts[2]) if len(parts) > 2 and parts[2] else 0
        dt = datetime.datetime(int(y), int(m), int(d), h, mi, se, tzinfo=datetime.timezone.utc)
    else:
        return {"ok": False, "error": f"unknown source_format: {source_format!r}"}

    if target_format == "unix":
        result = int(dt.timestamp())
    elif target_format == "iso":
        result = dt.isoformat()
    elif target_format == "cn":
        result = dt.strftime("%Y年%m月%d日 %H时%M分%S秒").strip()
    else:
        return {"ok": False, "error": f"unknown target_format: {target_format!r}"}

    return {"ok": True, "source_format": source_format, "target_format": target_format, "result": result}
'''

_SCRIPT_COLOR = '''\
def main(color, source_format="hex"):
    """Convert color values between HEX / RGB / HSL.

    Input: {"color": str, "source_format": "hex"|"rgb"|"hsl"}
    Output: {"ok": bool, "hex": str, "rgb": [int, int, int], "hsl": [int, int, int],
             "accessibility": {"luminance": float, "contrast_on_white": float, "contrast_on_black": float}}
    """
    if source_format == "hex":
        h = color.strip().lstrip("#")
        if len(h) != 6:
            return {"ok": False, "error": "hex must be 6 digits (e.g. '#FF8800' or 'FF8800')"}
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    elif source_format == "rgb":
        parts = [int(x.strip()) for x in color.replace("rgb(", "").replace(")", "").split(",")]
        if len(parts) != 3 or not all(0 <= p <= 255 for p in parts):
            return {"ok": False, "error": "rgb must be 3 ints in [0,255], e.g. '255,136,0' or 'rgb(255,136,0)'"}
        r, g, b = parts
    elif source_format == "hsl":
        # HSL parsing handled in conversion step; need s,l 0-1, h 0-360
        parts = [x.strip() for x in color.replace("hsl(", "").replace(")", "").split(",")]
        if len(parts) != 3:
            return {"ok": False, "error": "hsl must be 'h, s%, l%' e.g. '30, 100%, 50%'"}
        h_deg = float(parts[0])
        s_pct = float(parts[1].rstrip("%"))
        l_pct = float(parts[2].rstrip("%"))
        r, g, b = hsl_to_rgb(h_deg, s_pct / 100.0, l_pct / 100.0)
    else:
        return {"ok": False, "error": f"unknown source_format: {source_format!r}"}

    clamped = (max(0, min(255, x)) for x in (r, g, b))
    r, g, b = clamped
    h_deg, s_pct, l_pct = rgb_to_hsl(r, g, b)
    luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
    contrast_white = (max(luminance, 1.0) + 0.05) / (min(luminance, 1.0) + 0.05)
    contrast_black = (max(1.0, 1.0 - luminance) + 0.05) / (max(luminance, 0.0) + 0.05)
    return {
        "ok": True,
        "hex": f"#{r:02X}{g:02X}{b:02X}",
        "rgb": [r, g, b],
        "hsl": [round(h_deg, 1), round(s_pct, 1), round(l_pct, 1)],
        "accessibility": {
            "luminance": round(luminance, 3),
            "contrast_on_white": round(contrast_white, 2),
            "contrast_on_black": round(contrast_black, 2),
            "wcag_aa_text": contrast_white >= 4.5,
            "wcag_aaa_text": contrast_white >= 7.0,
        },
    }


def hsl_to_rgb(h, s, l):
    """h in [0,360), s,l in [0,1]. Standard formula."""
    if s == 0:
        v = int(round(l * 255))
        return (v, v, v)
    c = (1 - abs(2 * l - 1)) * s
    hh = (h % 360) / 60.0
    x = c * (1 - abs(hh % 2 - 1))
    if hh < 1: r1, g1, b1 = c, x, 0
    elif hh < 2: r1, g1, b1 = x, c, 0
    elif hh < 3: r1, g1, b1 = 0, c, x
    elif hh < 4: r1, g1, b1 = 0, x, c
    elif hh < 5: r1, g1, b1 = x, 0, c
    else: r1, g1, b1 = c, 0, x
    m = l - c / 2
    return (int(round((r1 + m) * 255)), int(round((g1 + m) * 255)), int(round((b1 + m) * 255)))


def rgb_to_hsl(r, g, b):
    rn, gn, bn = r / 255.0, g / 255.0, b / 255.0
    cmax, cmin = max(rn, gn, bn), min(rn, gn, bn)
    delta = cmax - cmin
    l = (cmax + cmin) / 2
    if delta == 0:
        h = 0
    elif cmax == rn:
        h = 60 * (((gn - bn) / delta) % 6)
    elif cmax == gn:
        h = 60 * (((bn - rn) / delta) + 2)
    else:
        h = 60 * (((rn - gn) / delta) + 4)
    s = 0 if delta == 0 else delta / (1 - abs(2 * l - 1))
    return (h, s * 100, l * 100)
'''

_SCRIPT_UUID = '''\
import uuid

def main(version="v4", count=1):
    """Generate UUID v4 or v7.

    Input: {"version": "v4"|"v7", "count": int}
    Output: {"ok": bool, "version": str, "uuids": [str, ...]}
    Note: uuid requires Python 3.7+; uuid7 was added in 3.14 — fall back
    to v4 if v7 is unavailable.
    """
    n = max(1, min(int(count), 1000))
    if version == "v4":
        return {"ok": True, "version": "v4", "uuids": [str(uuid.uuid4()) for _ in range(n)]}
    elif version == "v7":
        if hasattr(uuid, "uuid7"):
            return {"ok": True, "version": "v7", "uuids": [str(uuid.uuid7()) for _ in range(n)]}
        # Fallback: synthesize UUID v7-shaped strings (time-ordered) from v4
        ts = uuid.uuid4().time  # not real time-ordered, but still 128-bit unique
        return {"ok": True, "version": "v7", "uuids": [str(uuid.uuid4()) for _ in range(n)], "note": "uuid7 not available; using uuid4"}
    else:
        return {"ok": False, "error": f"unknown version: {version!r} (expected 'v4'|'v7')"}
'''


def seed_marketplace_data(db: Session):
    """Seed marketplace skills — idempotent per-name.

    Per-name check: existing rows are left untouched, only new names
    are inserted. Safe to re-run on dev DBs that already have the 6
    baseline prompt skills (代码优化专家 etc.) — adds the 3 Puppeteer
    skills without duplicating anything.

    M34 (2026-06-30): expanded to 25 by appending 15 new seeds across
    4 executor types (prompt × 6 / http × 3 / script × 5 / text2sql × 1).
    """
    candidates = [
            SkillMarketplace(
                name="代码优化专家",
                category="code",
                description="帮助优化代码性能和质量，提供重构建议和性能分析",
                content="You are a code optimization expert. Analyze the provided code and suggest improvements.",
                version="1.0.0",
                provider="Lumen AI Platform",
                downloads=1200,
                rating="4.8",
                is_verified=1
            ),
            SkillMarketplace(
                name="文档写作助手",
                category="writing",
                description="帮助撰写各类技术文档，包括API文档、README等",
                content="You are a technical documentation assistant. Help write clear and comprehensive documentation.",
                version="1.0.0",
                provider="Lumen AI Platform",
                downloads=890,
                rating="4.6",
                is_verified=1
            ),
            SkillMarketplace(
                name="数据分析专家",
                category="data",
                description="快速分析和可视化数据，提供数据洞察",
                content="You are a data analysis expert. Analyze data and provide insights with visualizations.",
                version="1.0.0",
                provider="Lumen AI Platform",
                downloads=756,
                rating="4.7",
                is_verified=1
            ),
            SkillMarketplace(
                name="测试工程师",
                category="testing",
                description="自动生成测试用例，覆盖多种测试场景",
                content="You are a testing engineer. Generate comprehensive test cases for the provided code.",
                version="1.0.0",
                provider="Lumen AI Platform",
                downloads=543,
                rating="4.5",
                is_verified=1
            ),
            SkillMarketplace(
                name="API设计助手",
                category="design",
                description="帮助设计RESTful API，符合最佳实践",
                content="You are an API design assistant. Help design clean and RESTful APIs.",
                version="1.0.0",
                provider="Lumen AI Platform",
                downloads=432,
                rating="4.4",
                is_verified=1
            ),
            SkillMarketplace(
                name="代码审查员",
                category="code",
                description="自动化代码审查，发现潜在问题和改进点",
                content="You are a code reviewer. Review code for potential issues and suggest improvements.",
                version="1.0.0",
                provider="Lumen AI Platform",
                downloads=321,
                rating="4.3",
                is_verified=1
            ),
            # --- Puppeteer skills (M32 / 2026-06-17) ---
            # See _PUPPETEER_* module-level constants above for full
            # system prompts. Reference:
            # https://github.com/puppeteer/puppeteer
            SkillMarketplace(
                name="Puppeteer 网页数据爬取",
                category="data",
                description=(
                    "用 Puppeteer (Node.js) 从任意网页提取结构化数据,"
                    "支持登录、翻页、动态加载。脚本需本地 `npm install "
                    "puppeteer` 后运行。"
                ),
                content=_PUPPETEER_SCRAPE_CONTENT.replace(
                    "{puppeteer_url}", _PUPPETEER_REFERENCE_URL
                ),
                version="1.0.0",
                provider="Lumen AI Platform",
                downloads=8500,
                rating="4.7",
                is_verified=1,
            ),
            SkillMarketplace(
                name="Puppeteer 网页截图",
                category="data",
                description=(
                    "用 Puppeteer 对任意网页或元素生成高清截图"
                    "(全页 / 元素 / 视口 / Retina / 关闭动画)。"
                    "脚本需本地 `npm install puppeteer` 后运行。"
                ),
                content=_PUPPETEER_SCREENSHOT_CONTENT.replace(
                    "{puppeteer_url}", _PUPPETEER_REFERENCE_URL
                ),
                version="1.0.0",
                provider="Lumen AI Platform",
                downloads=6200,
                rating="4.6",
                is_verified=1,
            ),
            SkillMarketplace(
                name="Puppeteer 网页生成 PDF",
                category="data",
                description=(
                    "用 Puppeteer 把任意网页渲染成高质量 PDF"
                    "(A4/Letter/横向/页眉页脚/CSS @page)。"
                    "脚本需本地 `npm install puppeteer` 后运行。"
                ),
                content=_PUPPETEER_PDF_CONTENT.replace(
                    "{puppeteer_url}", _PUPPETEER_REFERENCE_URL
                ),
                version="1.0.0",
                provider="Lumen AI Platform",
                downloads=5400,
                rating="4.7",
                is_verified=1,
            ),
            # --- M34 / 2026-06-30: 16 new seeds (6 prompt + 3 http + 5 script + 1 text2sql) ---
            # See module-level _TRANSLATE_CONTENT / _SQL_EXPERT_CONTENT /
            # _EMAIL_WRITER_CONTENT / _SUMMARY_CONTENT / _WEEKLY_REPORT_CONTENT /
            # _PYTHON_DEBUG_CONTENT / _SCRIPT_* constants above. Skill IDs above
            # this block are part of the M32 (3 Puppeteer) follow-up + 6
            # M16 baselines (代码优化专家 etc.). Adding more? Mirror the
            # SkillMarketplace(...) pattern + 1-line comment + ensure the
            # constant lives at module scope for testability.
            # ----- 6 prompt skills (system prompts the LLM uses directly) -----
            SkillMarketplace(
                name="翻译润色助手",
                category="writing",
                type="prompt",
                description=(
                    "多语种翻译 + 润色。支持术语表一致性、风格保持(正式 / "
                    "口语 / 技术 / 营销 transcreation)、双语对照输出。"
                ),
                content=_TRANSLATE_CONTENT,
                version="1.0.0",
                provider="Lumen AI Platform",
                downloads=2100,
                rating="4.7",
                is_verified=1,
            ),
            SkillMarketplace(
                name="SQL 专家",
                category="code",
                type="prompt",
                description=(
                    "MySQL/PostgreSQL/SQLite 跨方言 SQL 生成、优化与诊断。"
                    "EXPLAIN 分析 + 索引建议 + 防 N+1 + DDL/DML 分离。"
                ),
                content=_SQL_EXPERT_CONTENT,
                version="1.0.0",
                provider="Lumen AI Platform",
                downloads=3200,
                rating="4.8",
                is_verified=1,
            ),
            SkillMarketplace(
                name="邮件写作助手",
                category="writing",
                type="prompt",
                description=(
                    "4 种场景邮件草稿:正式商务 / 道歉补救 / 营销推广 / 跟"
                    "进催促。每封提供 3 选 1 主题行 + 具体 CTA + 收件人适"
                    "配文化。"
                ),
                content=_EMAIL_WRITER_CONTENT,
                version="1.0.0",
                provider="Lumen AI Platform",
                downloads=1450,
                rating="4.6",
                is_verified=1,
            ),
            SkillMarketplace(
                name="文本摘要助手",
                category="writing",
                type="prompt",
                description=(
                    "长文→结构化要点列表 + 关键数据保真 + 5W1H 抽取。"
                    "短 / 中 / 长三档粒度,自带原文未提及补全。"
                ),
                content=_SUMMARY_CONTENT,
                version="1.0.0",
                provider="Lumen AI Platform",
                downloads=1830,
                rating="4.6",
                is_verified=1,
            ),
            SkillMarketplace(
                name="周报生成助手",
                category="writing",
                type="prompt",
                description=(
                    "工作条目→4 段式结构化周报:本周完成 / 进行中 / 下周"
                    "计划 / 风险与求助。要求每行量化、避免空话。"
                ),
                content=_WEEKLY_REPORT_CONTENT,
                version="1.0.0",
                provider="Lumen AI Platform",
                downloads=980,
                rating="4.5",
                is_verified=1,
            ),
            SkillMarketplace(
                name="Python 调试助手",
                category="code",
                type="prompt",
                description=(
                    "traceback 自底向上解析 + stack frame 解释 + 最小复现 "
                    "(5-15 行)+ 修复 diff + 根因说明。覆盖 KeyError / "
                    "TypeError / ImportError / RecursionError 等常见类。"
                ),
                content=_PYTHON_DEBUG_CONTENT,
                version="1.0.0",
                provider="Lumen AI Platform",
                downloads=2750,
                rating="4.8",
                is_verified=1,
            ),
            # ----- 3 HTTP skills (free public APIs, no auth) -----
            # Allowlist seeded by ensure_system_configs_table() at startup
            # (3 default domains + the SystemConfig table itself).
            SkillMarketplace(
                name="天气查询",
                category="data",
                type="http",
                description=(
                    "实时天气查询(免 key / 免注册)。Open-Meteo 当前天气 "
                    "API,按经纬度查温度 / 风速 / 天气代码。"
                ),
                content=None,  # tool-only — content=None is fine for HTTP skills
                type_config={
                    "url": "https://api.open-meteo.com/v1/forecast",
                    "method": "GET",
                    "headers": {"Accept": "application/json"},
                    "timeout": 10,
                },
                version="1.0.0",
                provider="Lumen AI Platform",
                downloads=1600,
                rating="4.5",
                is_verified=1,
            ),
            SkillMarketplace(
                name="汇率换算",
                category="data",
                type="http",
                description=(
                    "实时汇率换算(免 key)。frankfurter.app 提供欧洲央行"
                    "日频汇率,支持 30+ 法定货币。"
                ),
                content=None,
                type_config={
                    "url": "https://api.frankfurter.app/latest",
                    "method": "GET",
                    "headers": {"Accept": "application/json"},
                    "timeout": 10,
                },
                version="1.0.0",
                provider="Lumen AI Platform",
                downloads=1250,
                rating="4.6",
                is_verified=1,
            ),
            SkillMarketplace(
                name="短网址生成",
                category="data",
                type="http",
                description=(
                    "长网址 → 短网址(免 key / 免注册)。is.gd 单次请求"
                    "即可生成永久有效短链。"
                ),
                content=None,
                type_config={
                    "url": "https://is.gd/create.php",
                    "method": "GET",
                    "headers": {"Accept": "application/json"},
                    "timeout": 10,
                },
                version="1.0.0",
                provider="Lumen AI Platform",
                downloads=720,
                rating="4.4",
                is_verified=1,
            ),
            # ----- 5 script skills (RestrictedPython sandbox safe; stdlib only) -----
            SkillMarketplace(
                name="JSON 格式化校验",
                category="data",
                type="script",
                description=(
                    "校验 JSON 字符串语法 + 自动 indent 格式化 + 报错定位"
                    "(精确行/列)。失败返回 line N, col M + 上下文片段。"
                ),
                content=None,
                type_config={
                    "code": _SCRIPT_JSON_FORMAT,
                    "runtime": "python-3.11",
                    "timeout": 5,
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "json_input": {
                                "type": "string",
                                "description": "待校验 + 格式化的 JSON 字符串",
                            }
                        },
                        "required": ["json_input"],
                    },
                },
                version="1.0.0",
                provider="Lumen AI Platform",
                downloads=2900,
                rating="4.8",
                is_verified=1,
            ),
            SkillMarketplace(
                name="Base64 编解码",
                category="data",
                type="script",
                description=(
                    "Base64 encode/decode + URL-safe 变体 + UTF-8 错误捕"
                    "获。返回 ok 标志 + 结果长度,decode 失败返 error。"
                ),
                content=None,
                type_config={
                    "code": _SCRIPT_BASE64,
                    "runtime": "python-3.11",
                    "timeout": 5,
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "mode": {
                                "type": "string",
                                "default": "encode",
                                "description": "encode | decode",
                            },
                            "url_safe": {
                                "type": "boolean",
                                "default": False,
                                "description": "True 用 urlsafe_b64encode",
                            },
                        },
                        "required": ["text"],
                    },
                },
                version="1.0.0",
                provider="Lumen AI Platform",
                downloads=1450,
                rating="4.6",
                is_verified=1,
            ),
            SkillMarketplace(
                name="时间戳格式化",
                category="data",
                type="script",
                description=(
                    "unix 秒 ↔ ISO 8601 ↔ 中文日期(YYYY年MM月DD日 HH时"
                    "MM分SS秒)。纯 datetime / 时区处理,无外部依赖。"
                ),
                content=None,
                type_config={
                    "code": _SCRIPT_TIMESTAMP,
                    "runtime": "python-3.11",
                    "timeout": 5,
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "timestamp": {
                                "type": "string",
                                "description": "Unix 秒(int)/ ISO 字符串 / YYYY年MM月DD日 [HH时MM分SS秒]",
                            },
                            "source_format": {
                                "type": "string",
                                "default": "unix",
                                "description": "unix / iso / cn",
                            },
                            "target_format": {
                                "type": "string",
                                "default": "iso",
                                "description": "unix / iso / cn",
                            },
                        },
                        "required": ["timestamp", "source_format", "target_format"],
                    },
                },
                version="1.0.0",
                provider="Lumen AI Platform",
                downloads=820,
                rating="4.5",
                is_verified=1,
            ),
            SkillMarketplace(
                name="颜色值转换",
                category="design",
                type="script",
                description=(
                    "HEX(#RRGGBB) ↔ RGB(255,255,255) ↔ HSL(120,50%,50%) "
                    "三向互转 + WCAG 2.x 对比度(白底/黑底)+ AAA/AA 文字"
                    "可读性布尔。"
                ),
                content=None,
                type_config={
                    "code": _SCRIPT_COLOR,
                    "runtime": "python-3.11",
                    "timeout": 5,
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "color": {"type": "string"},
                            "source_format": {
                                "type": "string",
                                "default": "hex",
                                "description": "hex / rgb / hsl",
                            },
                        },
                        "required": ["color", "source_format"],
                    },
                },
                version="1.0.0",
                provider="Lumen AI Platform",
                downloads=1100,
                rating="4.7",
                is_verified=1,
            ),
            SkillMarketplace(
                name="UUID 生成器",
                category="data",
                type="script",
                description=(
                    "批量生成 UUID v4(随机)/ v7(时间有序,Python 3.14+ "
                    "有真 uuid7,旧版降级到 v4 + 提示)。上限 1000 个/次。"
                ),
                content=None,
                type_config={
                    "code": _SCRIPT_UUID,
                    "runtime": "python-3.11",
                    "timeout": 5,
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "version": {
                                "type": "string",
                                "default": "v4",
                                "description": "v4 | v7",
                            },
                            "count": {
                                "type": "integer",
                                "default": 1,
                                "description": "1-1000",
                            },
                        },
                    },
                },
                version="1.0.0",
                provider="Lumen AI Platform",
                downloads=1980,
                rating="4.6",
                is_verified=1,
            ),
            # ----- 1 text2sql skill (uses default ai_platform datasource) -----
            SkillMarketplace(
                name="销售数据问数助手",
                category="data",
                type="text2sql",
                description=(
                    "自然语言问销售/客户/订单业务数据。自动生成 SQL + 试"
                    "执行 + 表格结果 + 中文解释,装上即用(默认 ai_platform "
                    "data_source)。"
                ),
                content=None,
                type_config={
                    "data_source_name": "默认 ai_platform",
                },
                version="1.0.0",
                provider="Lumen AI Platform",
                downloads=610,
                rating="4.5",
                is_verified=1,
            ),
    ]
    existing_names = {
        row.name for row in db.query(SkillMarketplace.name).all()
    }
    new_skills = [s for s in candidates if s.name not in existing_names]
    if new_skills:
        db.add_all(new_skills)
        db.commit()


@router.get("/", response_model=PaginatedResponse[SkillMarketplaceResponse])
async def list_marketplace_skills(
    page: int = 1,
    page_size: int = 10,
    category: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List available skills in the marketplace"""
    # Seed data if empty
    seed_marketplace_data(db)

    # Get installed skills for current tenant — we need both the
    # marketplace id (to set is_installed) and the linked Skill.id
    # (to populate skill_id, which the frontend sends back as
    # skill_ids in ChatRequest / stores in workflow LLM node data).
    installed = db.query(InstalledSkill).filter(
        InstalledSkill.tenant_id == current_user.tenant_id
    ).all()
    installed_marketplace_ids = {i.marketplace_skill_id for i in installed}
    installed_skill_ids_by_marketplace: dict[int, int] = {
        i.marketplace_skill_id: i.skill_id for i in installed if i.skill_id is not None
    }

    # Query marketplace skills. M32 (2026-06-17) pinned the sort to
    # "verified first, then id-desc within the same verification level"
    # so that newly-published skills surface on page 1 instead of being
    # buried at the tail (previously MySQL's default PK-asc order meant
    # newer = higher id = last page). M34 (2026-06-30) re-pinned this
    # after adding 15 new seeds surfaced a fragility: the test that
    # covered M32's intent relied on Puppeteer being the highest-id
    # row in the data category, which is no longer true.
    query = db.query(SkillMarketplace).order_by(
        SkillMarketplace.is_verified.desc(),
        SkillMarketplace.id.desc(),
    )
    if category:
        query = query.filter(SkillMarketplace.category == category)

    total = query.count()
    start = (page - 1) * page_size
    end = start + page_size

    skills = query.offset(start).limit(page_size).all()

    return PaginatedResponse(
        data=[SkillMarketplaceResponse(
            id=s.id,
            name=s.name,
            category=s.category,
            type=s.type or "prompt",
            description=s.description,
            version=s.version,
            provider=s.provider,
            downloads=s.downloads,
            rating=s.rating,
            is_verified=bool(s.is_verified),
            is_installed=s.id in installed_marketplace_ids,
            skill_id=installed_skill_ids_by_marketplace.get(s.id),
        ) for s in skills],
        total=total,
        page=page,
        page_size=page_size
    )


@router.get("/categories", response_model=SingleResponse)
async def list_categories(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List available skill categories with counts"""
    seed_marketplace_data(db)

    categories = db.query(
        SkillMarketplace.category,
        func.count(SkillMarketplace.id).label("count")
    ).group_by(SkillMarketplace.category).all()

    category_labels = {
        "code": "代码",
        "writing": "写作",
        "data": "数据",
        "testing": "测试",
        "design": "设计",
    }

    result = [
        {
            "value": c.category,
            "label": category_labels.get(c.category, c.category),
            "count": c.count
        }
        for c in categories
    ]
    return SingleResponse(data=result)


@router.post("/{skill_id}/install", response_model=SingleResponse)
async def install_skill(
    skill_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Install a skill from marketplace to tenant's skills"""
    # Get marketplace skill
    marketplace_skill = db.query(SkillMarketplace).filter(
        SkillMarketplace.id == skill_id
    ).first()

    if not marketplace_skill:
        raise HTTPException(status_code=404, detail=f"Skill {skill_id} not found in marketplace")

    # Check if already installed
    existing = db.query(InstalledSkill).filter(
        InstalledSkill.tenant_id == current_user.tenant_id,
        InstalledSkill.marketplace_skill_id == skill_id
    ).first()

    if existing:
        return SingleResponse(message=f"Skill '{marketplace_skill.name}' is already installed")

    # Create a new Skill for this tenant based on marketplace skill.
    # Reuse an existing one if it survives an uninstall, to avoid the
    # unique-name UNIQUE constraint on Skill.name.
    skill_name = f"{marketplace_skill.name}_{current_user.tenant_id}"
    new_skill = db.query(Skill).filter(Skill.name == skill_name).first()
    if not new_skill:
        new_skill = Skill(
            tenant_id=current_user.tenant_id,
            name=skill_name,
            description=marketplace_skill.description,
            category=marketplace_skill.category,
            content=marketplace_skill.content,
            type=marketplace_skill.type,
            is_builtin=False,
            is_active=True,
            version=marketplace_skill.version
        )
        db.add(new_skill)
        db.flush()  # Get the ID
    else:
        # Sync type/content in case marketplace updated since last install
        new_skill.type = marketplace_skill.type
        new_skill.content = marketplace_skill.content
        new_skill.is_active = True

    # Create installed skill record
    installed = InstalledSkill(
        tenant_id=current_user.tenant_id,
        marketplace_skill_id=skill_id,
        skill_id=new_skill.id,
        status="active"
    )
    db.add(installed)

    # Update download count
    marketplace_skill.downloads += 1

    db.commit()

    return SingleResponse(message=f"Skill '{marketplace_skill.name}' installed successfully")


@router.post("/{skill_id}/uninstall", response_model=SingleResponse)
async def uninstall_skill(
    skill_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Uninstall a skill that was installed from marketplace"""
    installed = db.query(InstalledSkill).filter(
        InstalledSkill.tenant_id == current_user.tenant_id,
        InstalledSkill.marketplace_skill_id == skill_id
    ).first()

    if not installed:
        raise HTTPException(status_code=404, detail="Skill not installed")

    # Delete the installed record
    db.delete(installed)
    db.commit()

    return SingleResponse(message="Skill uninstalled successfully")


# M20 (2026-06-11): 批量卸载
@router.post("/batch-uninstall", response_model=SingleResponse)
async def batch_uninstall_skills(
    body: BatchUninstallRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Uninstall multiple marketplace skills in a single transaction.

    Idempotent: ids that aren't installed (or don't belong to the
    caller's tenant) end up in `failed` with a reason, not as 404s.

    Spec: docs/superpowers/specs/2026-06-11-skill-installed-page-fixes-design.md §3.1
    """
    succeeded_count = 0
    failed: list[dict] = []

    for skill_id in body.ids:
        installed = db.query(InstalledSkill).filter(
            InstalledSkill.tenant_id == current_user.tenant_id,
            InstalledSkill.marketplace_skill_id == skill_id
        ).first()
        if installed is None:
            failed.append({"id": skill_id, "reason": "not installed"})
            continue
        db.delete(installed)
        db.flush()  # push delete to DB so subsequent queries see it
                    # (project's SessionLocal uses autoflush=False, so the
                    # identity map would otherwise return the same row again)
        succeeded_count += 1

    if succeeded_count > 0:
        db.commit()

    return SingleResponse(data={
        "succeeded_count": succeeded_count,
        "failed": failed,
    })


@router.get("/installed", response_model=PaginatedResponse[SkillMarketplaceResponse])
async def list_installed_skills(
    page: int = 1,
    page_size: int = 10,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List skills installed by current tenant.

    M34 (2026-06-30) added explicit ``installed_at desc`` ordering —
    the corresponding unit test
    (``test_installed_list_orders_by_installed_at_desc``) had been
    written assuming this ordering existed in production but the
    implementation never had ``order_by`` (relied on MySQL PK-asc,
    which happened to put the newly installed row at the tail of the
    list — opposite of what users want).
    """
    query = db.query(InstalledSkill, SkillMarketplace).join(
        SkillMarketplace,
        InstalledSkill.marketplace_skill_id == SkillMarketplace.id
    ).filter(
        InstalledSkill.tenant_id == current_user.tenant_id
    ).order_by(
        InstalledSkill.installed_at.desc(),
        InstalledSkill.id.desc(),
    )

    total = query.count()
    start = (page - 1) * page_size
    end = start + page_size

    results = query.offset(start).limit(page_size).all()

    return PaginatedResponse(
        data=[SkillMarketplaceResponse(
            id=ms.id,
            name=ms.name,
            category=ms.category,
            type=ms.type or "prompt",
            description=ms.description,
            version=ms.version,
            provider=ms.provider,
            downloads=ms.downloads,
            rating=ms.rating,
            is_verified=bool(ms.is_verified),
            is_installed=True,
            skill_id=installed.skill_id,
            installed_at=installed.installed_at.isoformat() if installed.installed_at else None,
        ) for installed, ms in results],
        total=total,
        page=page,
        page_size=page_size
    )


@router.get("/{skill_id}", response_model=SingleResponse[SkillMarketplaceResponse])
async def get_marketplace_skill(
    skill_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single marketplace skill's full detail, including content.

    NOTE on route ordering: this /{skill_id} route MUST be defined AFTER
    all literal-path routes (e.g. /categories, /installed). FastAPI matches
    path-parameter routes before literal ones, so defining it earlier would
    shadow /categories and /installed with a 422 'unable to parse string as
    integer' error. See test_get_install_path_returns_405 and
    test_get_categories_path_unaffected for regression coverage.

    Marketplace skills are shared across tenants, so no tenant scoping
    is applied here. is_installed / skill_id are computed against the
    current user's tenant to drive the "install" vs "installed" UI state.
    """
    marketplace_skill = db.query(SkillMarketplace).filter(
        SkillMarketplace.id == skill_id
    ).first()
    if not marketplace_skill:
        raise HTTPException(
            status_code=404,
            detail=f"Skill {skill_id} not found in marketplace",
        )

    # Compute is_installed / skill_id for current user's tenant
    installed = db.query(InstalledSkill).filter(
        InstalledSkill.tenant_id == current_user.tenant_id,
        InstalledSkill.marketplace_skill_id == skill_id,
    ).first()

    return SingleResponse(data=SkillMarketplaceResponse(
        id=marketplace_skill.id,
        name=marketplace_skill.name,
        category=marketplace_skill.category,
        type=marketplace_skill.type or "prompt",
        description=marketplace_skill.description,
        version=marketplace_skill.version,
        provider=marketplace_skill.provider,
        downloads=marketplace_skill.downloads,
        rating=marketplace_skill.rating,
        is_verified=bool(marketplace_skill.is_verified),
        is_installed=installed is not None,
        skill_id=installed.skill_id if installed else None,
        content=marketplace_skill.content,
    ))
