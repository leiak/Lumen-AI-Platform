# 模块:Playbook 风格系统

> Lumen AI Platform 的 Playbook 视觉/语音风格系统。
> 文档讲透 Playbook 是什么、怎么用、和 AI 内容的结合。

---

## 1. 产品定位

**Playbook 是什么?**
- 一组"风格 token"(`keywords` / `palette` / `avoid` / `voice_direction`)
- 注入到 AI 生成的 prompt,锁定视觉/语音风格
- 5 个内置 + 自定义

**和"风格指南文档"比有什么不同?**
- Playbook 是**结构化的**,可被代码读
- 注入到 prompt 是**自动的**,不靠人记
- 多场景复用:**图 + 语音 + 文案**

**业务场景?**
- 公司 VI(logo 色 / 字体) → Playbook
- 不同客户(教育 / 金融 / 制造) → 不同 Playbook
- 不同 mood(温暖 / 学术 / 商务) → 不同 Playbook

---

## 2. 功能清单

| 功能 | 描述 |
|------|------|
| Playbook CRUD | 创建 / 编辑 / 删除 |
| 5 个内置 | clean-professional / anime-ghibli / cinematic-dark / tech-minimalist / warm-storytelling |
| 视觉 token | keywords / palette / avoid / style_direction |
| 语音 token | voice_direction / speed / pitch |
| 自动注入 | 图片 prompt / TTS voice / 文案 |
| 作用域 | 全局(平台) / 租户 |

---

## 3. 5 个内置 Playbook

### 3.1 clean-professional
- 视觉: 简洁、专业、商务
- keywords: clean, minimalist, professional, corporate
- palette: 蓝白灰(#1E3A8A / #FFFFFF / #6B7280)
- avoid: 卡通、夸张、霓虹色

### 3.2 anime-ghibli
- 视觉: 吉卜力动画风
- keywords: ghibli, anime, soft, warm, nostalgic
- palette: 暖色(#FCD34D / #F87171 / #6EE7B7)
- avoid: 现代建筑、机械、冷色

### 3.3 cinematic-dark
- 视觉: 电影感、暗调
- keywords: cinematic, dark, dramatic, moody
- palette: 暗色调(#1F2937 / #DC2626 / #F59E0B)
- avoid: 明亮、轻快

### 3.4 tech-minimalist
- 视觉: 科技极简
- keywords: tech, futuristic, minimal, geometric
- palette: 黑白(#000000 / #FFFFFF / #3B82F6)
- avoid: 装饰、复杂、有机

### 3.5 warm-storytelling
- 视觉: 温暖叙事
- keywords: warm, storytelling, intimate, soft
- palette: 米色(#FEF3C7 / #FB923C / #92400E)
- avoid: 工业、冷峻

---

## 4. 数据模型

### 4.1 playbooks
```python
class Playbook(Base):
    id: int
    name: str
    description: str
    keywords: list                # 关键词(注入到 prompt)
    palette: dict                 # 调色板 {"primary": "#...", "secondary": "#..."}
    avoid: list                   # 避免的元素
    style_direction: str          # 风格方向描述
    voice_direction: str          # 语音方向(注入到 TTS)
    voice_speed: float            # 语速
    voice_pitch: float            # 音调
    is_platform: bool             # 平台级
    tenant_id: int                # 租户级(可空)
    is_active: bool
    created_at
```

### 4.2 文件
- ORM: `backend/lumen_models/playbook.py`
- Schema: `backend/lumen_schemas/playbook.py`
- 服务: `backend/lumen_services/playbook_service.py`
- 渲染器: `backend/lumen_tools/playbook_renderer.py`
- 路由: `backend/lumen_api/v1/playbook.py`
- 种子: `backend/lumen_scripts/seed_playbooks.py`

---

## 5. UI

### 5.1 管理
- 路径: `frontend/app/dashboard/system/playbooks/page.tsx`
- 表格:名字 / 类型 / 用途 / 操作
- 操作:编辑 / 删 / 复制

### 5.2 编辑表单
- 名字 / 描述
- keywords(tags)
- palette(色卡)
- avoid(tags)
- style_direction(textarea)
- voice_direction(textarea)
- 预览(用 Playbook 渲染示例 prompt)

### 5.3 选择器
- 组件: `frontend/components/PlaybookSelect.tsx`
- 在 Agent / 图片生成 / TTS / 视频中用

---

## 6. 关键能力详解

### 6.1 注入到图片 prompt
```python
# backend/lumen_tools/playbook_renderer.py
def render_for_image(prompt: str, playbook: Playbook) -> str:
    parts = [prompt]
    if playbook.keywords:
        parts.append(", ".join(playbook.keywords))
    if playbook.palette:
        colors = ", ".join(playbook.palette.values())
        parts.append(f"color palette: {colors}")
    if playbook.style_direction:
        parts.append(playbook.style_direction)
    if playbook.avoid:
        parts.append(f"avoid: {', '.join(playbook.avoid)}")
    return ", ".join(parts)
```

### 6.2 注入到 TTS
```python
def render_for_tts(playbook: Playbook) -> dict:
    return {
        "voice": playbook.preferred_voice,  # 可选
        "voice_direction": playbook.voice_direction,
        "speed": playbook.voice_speed or 1.0,
        "pitch": playbook.voice_pitch or 0,
    }
```

### 6.3 注入到文案(LLM prompt)
```python
def render_for_text(content: str, playbook: Playbook) -> str:
    parts = [content]
    if playbook.style_direction:
        parts.append(f"\n\n【风格要求】\n{playbook.style_direction}")
    if playbook.avoid:
        parts.append(f"\n\n【避免】\n{', '.join(playbook.avoid)}")
    return "\n".join(parts)
```

### 6.4 作用域
- 平台级 (`is_platform=True` + `tenant_id IS NULL`): 5 个内置
- 租户级 (`is_platform=False` + `tenant_id=N`): 租户自定义
- 租户可看: 平台 + 本租户

---

## 7. 关键代码

### 7.1 渲染器
- `backend/lumen_tools/playbook_renderer.py`
- 3 个函数:
  - `render_for_image(prompt, playbook) -> str`
  - `render_for_tts(playbook) -> dict`
  - `render_for_text(content, playbook) -> str`

### 7.2 在 Agent 中用
- Agent 不直接用 Playbook
- Agent 的"工具"或"prompt"中可引用 Playbook
- 例: Agent prompt 里写"按 XX 风格回答"

### 7.3 在图片生成中用
- 创建图片任务时选 Playbook
- 后端 Celery 任务渲染

### 7.4 在 TTS 中用
- 创建 TTS 任务时选 Playbook
- 后端 Celery 任务应用 voice / speed

---

## 8. 边界与不做

### 8.1 当前
- ✅ 5 内置
- ✅ 视觉 + 语音 token
- ✅ 自动注入
- ✅ 平台 + 租户二级

### 8.2 不做
- ❌ 视觉预览(用 Playbook 渲示例图)
- ❌ 风格迁移(风格 A → 风格 B)
- ❌ 自动推荐(按内容选 Playbook)

---

## 9. 升级路径

### 短期
- 📋 视觉预览
- 📋 Playbook 导入 / 导出(YAML)

### 中期
- 📋 AI 自动生成 Playbook(从几张样例)
- 📋 风格迁移

### 长期
- 📋 跨平台 Playbook 同步

---

## 10. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| Playbook 不生效 | 没选 / 字段空 | 检查 |
| 风格不对 | keywords 不准 | 改 keywords |
| 颜色不对 | palette 错 | 改色码 |
| 注入后太长 | description 太长 | 改短 |

---

**维护者**:产品经理 + 全栈架构师
**最近更新**:2026-08-06
