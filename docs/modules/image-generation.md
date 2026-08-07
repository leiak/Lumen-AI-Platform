# 模块:AI 图片生成

> Lumen AI Platform 的 AI 图片生成能力。
> 文档讲透能用什么 provider、怎么用、与 Playbook 的集成。

---

## 1. 产品定位

**图片生成是什么?**
- 用 AI 根据文字描述生成图片
- 4 个 provider 抽象:OpenAI / Stability / Ollama / Stub
- 后台任务 + WS 通知

**业务场景?**
- 公众号配图
- 营销图
- 草图 / 概念图
- AI 头像

---

## 2. 功能清单

| 功能 | 描述 |
|------|------|
| 多 provider 抽象 | OpenAI / Stability / Ollama / Stub |
| Playbook 集成 | 视觉风格 token 注入 prompt |
| 后台任务 | Celery 异步生成 |
| 缩略图持久化 | Pillow 自动生成 |
| 详情 Modal | 大图 + 重新生成 + 下载 |
| 历史记录 | 列表 + 搜索 + 标签 |
| 失败重试 | 3 次 + 退避 |

---

## 3. 4 个 Provider

| Provider | 模型 | 费用 | 速度 | 用途 |
|----------|------|------|------|------|
| **OpenAI** | DALL·E 3 / SD 协议 | $$ | 中 | 生产 |
| **Stability** | Stable Diffusion XL | $ | 中 | 高质量 |
| **Ollama** | 本地 SD 模型 | 免费 | 慢 | demo / 私有化 |
| **Stub** | mock 图片 | 免费 | 立刻 | 演示 / 测试 |

### 3.1 配置
- `model_configs.is_image=True` 标记为图片生成模型
- 凭证: `OPENAI_API_KEY` / `STABILITY_API_KEY` / (Ollama 无)
- Stub: 无需配置

---

## 4. 数据模型

### 4.1 image_generations
```python
class ImageGeneration(Base):
    id: int
    user_id: int
    tenant_id: int
    prompt: str                    # 原始 prompt
    final_prompt: str              # 注入 Playbook 后的
    provider: str                  # openai / stability / ollama / stub
    model: str                     # dall-e-3 / stable-diffusion-xl
    playbook_id: int               # 用的 Playbook
    size: str                      # 1024x1024
    n: int                         # 生成数量
    reference_images: list         # 参考图
    status: str                    # pending / running / success / failed
    file_path: str                 # 主图相对路径
    thumbnail_path: str            # 缩略图路径
    error: str
    metadata: dict                 # provider 响应
    created_at, finished_at
```

### 4.2 文件
- ORM: `backend/lumen_models/image_generation.py`
- Schema: `backend/lumen_schemas/image_generation.py`
- 服务: `backend/lumen_services/image_generation_service.py`
- Celery: `backend/lumen_tasks/image_gen_tasks.py`
- Provider: `backend/lumen_tools/image_providers/{openai,stability,ollama,stub}.py`
- 路由: `backend/lumen_api/v1/image_generation.py`

---

## 5. UI

### 5.1 列表
- 路径: `frontend/app/dashboard/image-generation/page.tsx`
- 卡片网格:缩略图 + prompt + 状态
- 操作:详情 / 删 / 重新生成

### 5.2 创建
- 表单:prompt / provider / model / size / 参考图 / Playbook
- 提交 → 后台任务

### 5.3 详情 Modal
- 文件: `frontend/components/image-generation/DetailModal.tsx`
- 大图 + 元数据 + 重新生成 + 下载
- **M22 立的 Bearer 模式**:`fetch + blob + createObjectURL` 显示受保护图片

### 5.4 关键组件
- `frontend/components/image-generation/ImageCard.tsx`
- `frontend/components/image-generation/DetailModal.tsx`
- `frontend/services/image-generation.ts`

---

## 6. 关键能力详解

### 6.1 Playbook 集成(M35)
- 选 Playbook → 注入 `keywords` / `palette` / `avoid` / `style_direction` 到 prompt
- 例: "夏日儿童插画" + "warm-storytelling" Playbook
  → 最终: "夏日儿童插画,暖色调,水彩风格,避免现代建筑,温暖叙事感"

### 6.2 后台任务
- 用户提交 → 立即返回 img_id
- Celery 任务 `generate(img_id)`:
  1. 调 provider API
  2. 下载图
  3. Pillow 生成缩略图
  4. 存 storage/generated_images/<tenant>/<date>/<id>.png
  5. 写 `image_generations.status=success`
  6. WS 推通知

### 6.3 缩略图持久化(M32.1 follow-up)
- Pillow 直绘 15 张默认缩略图
- 解决: 列表页加载慢(每次都 fetch 大图)
- 详见 [modules/llm-call-logs.md § Bearer 模式](llm-call-logs.md)

### 6.4 重新生成
- 复用 prompt + provider,只改随机种子(若支持)
- 创建新 `image_generations` 行(不覆盖原)

### 6.5 失败重试
- 网络错:重试 3 次 + 指数退避
- 鉴权错:不重试(改凭证)
- 限额错:不重试(等下次)

---

## 7. 性能

| 阶段 | 耗时 |
|------|------|
| OpenAI DALL·E 3 | 5~15 秒 |
| Stability SDXL | 8~20 秒 |
| Ollama SD | 30~60 秒 |
| Stub | < 1 秒 |

---

## 8. 关键代码

### 8.1 Provider 抽象
```python
# backend/lumen_tools/image_providers/base.py
class ImageProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, model: str, **kwargs) -> bytes:
        """返回图片二进制"""
        pass

# openai.py
class OpenAIProvider(ImageProvider):
    async def generate(self, prompt, model="dall-e-3", size="1024x1024", n=1):
        client = AsyncOpenAI(api_key=self.api_key)
        response = await client.images.generate(
            model=model, prompt=prompt, size=size, n=n, response_format="b64_json"
        )
        return base64.b64decode(response.data[0].b64_json)
```

### 8.2 Playbook 注入
```python
# backend/lumen_tools/playbook_renderer.py
def inject_playbook(prompt: str, playbook: Playbook) -> str:
    if not playbook:
        return prompt
    tokens = []
    if playbook.keywords:
        tokens.append(", ".join(playbook.keywords))
    if playbook.palette:
        tokens.append(f"color palette: {playbook.palette}")
    if playbook.style_direction:
        tokens.append(playbook.style_direction)
    if playbook.avoid:
        tokens.append(f"avoid: {', '.join(playbook.avoid)}")
    return f"{prompt}, {', '.join(tokens)}"
```

### 8.3 Celery 任务
```python
# backend/lumen_tasks/image_gen_tasks.py
@celery_app.task(bind=True, max_retries=3)
def generate_image(self, img_id: int):
    img = load_image_generation(img_id)
    try:
        provider = build_provider(img.provider)
        final_prompt = inject_playbook(img.prompt, img.playbook)
        img_bytes = await provider.generate(final_prompt, model=img.model)

        # 存主图
        main_path = save_image(img_bytes, f"storage/generated_images/{img.tenant_id}/{date}/{img_id}.png")
        # 缩略图
        thumb_path = make_thumbnail(main_path, size=(256, 256))

        img.file_path = main_path
        img.thumbnail_path = thumb_path
        img.status = "success"
        save(img)

        notify_ws(img.user_id, "image_generation_complete", {"id": img_id})
    except Exception as e:
        if self.request.retries < 3:
            raise self.retry(exc=e, countdown=2 ** self.request.retries)
        else:
            img.status = "failed"
            img.error = str(e)
            save(img)
```

---

## 9. 边界与不做

### 9.1 当前
- ✅ 4 provider
- ✅ Playbook 集成
- ✅ 后台任务
- ✅ 缩略图
- ✅ 重新生成
- ✅ 失败重试
- ✅ WS 通知

### 9.2 不做
- ❌ 视频生成
- ❌ 图片编辑(inpainting)
- ❌ 风格转换

---

## 10. 升级路径

### 短期
- 📋 图片编辑(inpainting)
- 📋 多图对比(选 1 张)

### 中期
- 📋 视频生成(扩展 Sora / 可灵)
- 📋 实时图(配合 Chat 流式)

### 长期
- 📋 3D 生成
- 📋 用户自定义模型

---

## 11. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| 401 / 403 | API key 错 | 改凭证 |
| 429 | 限额 | 等下次 / 换 provider |
| 一直 pending | Celery 没跑 | 启动 worker |
| 缩略图空白 | Pillow 错 | 看日志 |
| 详情 Modal 不显示图 | fetch 没带 token | 改 Bearer 模式 |
| Playbook 不生效 | 没选 | 选 Playbook |

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
