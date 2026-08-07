# 模块:模型管理

> Lumen AI Platform 的模型配置系统。
> 文档讲透能管理哪些模型、怎么用、per-KB 隔离。

---

## 1. 产品定位

**模型管理是什么?**
- 统一管理 LLM / Embedding / Image / TTS 模型
- 配置 provider(OpenAI / Ollama / Stability / ...)
- 凭证管理(SecretStr)

**和"硬编码 .env"比有什么不同?**
- UI 配置,不用改 .env
- 多模型并存,可切换
- 用途标志(chat / embedding / image / tts)

---

## 2. 功能清单

| 功能 | 描述 |
|------|------|
| 模型 CRUD | 创建 / 编辑 / 删除 / 启停 |
| 用途标志 | is_chat / is_embedding / is_image / is_tts |
| Ollama 一键导入 | 从本机 Ollama 拉模型 |
| 默认模型 | 每个用途可设 1 个默认 |
| 凭证管理 | SecretStr 包装 |
| 引用保护 | 被 KB 引用时不能删 |
| 验证 | 创建时测连通性 |

---

## 3. 数据模型

### 3.1 model_configs
```python
class ModelConfig(Base):
    id: int
    name: str                     # 显示名
    provider: str                 # openai / ollama / stability / ...
    model_name: str               # "gpt-4o" / "nomic-embed-text"
    api_key: str                  # SecretStr
    base_url: str                 # 自定义 endpoint
    is_chat: bool
    is_embedding: bool
    is_image: bool
    is_tts: bool
    is_default: bool              # 同用途只能 1 个默认
    is_active: bool
    config: dict                  # 额外参数(temperature 等)
    tenant_id: int                # NULL = 平台级
    created_at
```

### 3.2 文件
- ORM: `backend/lumen_models/model_config.py`
- Schema: `backend/lumen_schemas/model.py`
- 服务: `backend/lumen_services/model_service.py`
- 路由: `backend/lumen_api/v1/models.py`

---

## 4. UI

### 4.1 列表
- 路径: `frontend/app/dashboard/system/models/page.tsx`
- 表格:名字 / provider / 用途 / 状态 / 操作
- 过滤:按用途(is_chat / is_embedding / ...)

### 4.2 创建
- 表单:provider / model_name / api_key / base_url / 用途勾选
- 验证: 创建时测连通性

### 4.3 Ollama 一键导入
- 弹窗: `frontend/components/OllamaImportModal.tsx`
- 自动拉本机 Ollama 模型列表
- 一键建多个 model_config

### 4.4 关键组件
- `frontend/components/EmbeddingModelSelect.tsx`
- `frontend/components/ChatModelSelect.tsx`
- `frontend/components/OllamaImportModal.tsx`

---

## 5. 4 个用途

| 用途 | 标志 | 用在哪 |
|------|------|--------|
| **Chat** | `is_chat=True` | Agent / LLM 节点 |
| **Embedding** | `is_embedding=True` | KB 向量化 / 检索 |
| **Image** | `is_image=True` | 图片生成 |
| **TTS** | `is_tts=True` | TTS |

### 5.1 默认模型
- 每个用途可设 1 个默认(`is_default=True`)
- Agent 创建时默认选默认
- KB 创建时默认选默认 embedding

### 5.2 互斥
- 1 个 model 只能 1 个默认
- 改默认时,旧的自动取消

---

## 6. Provider 配置

### 6.1 OpenAI
- provider: "openai"
- model_name: "gpt-4o" / "gpt-3.5-turbo" / "text-embedding-3-small" ...
- api_key: sk-...
- base_url: 默认(可改 Azure / 其他兼容)

### 6.2 Ollama
- provider: "ollama"
- model_name: "qwen2.5:7b" / "nomic-embed-text" ...
- api_key: 不需要
- base_url: 默认 http://localhost:11434

### 6.3 Stability
- provider: "stability"
- model_name: "stable-diffusion-xl-1024-v1-0"
- api_key: sk-...

### 6.4 Stub
- provider: "stub"
- 用在 image / tts 演示
- 不需要配置

---

## 7. 关键能力详解

### 7.1 SecretStr 包装
- api_key 用 Pydantic `SecretStr` 存
- 日志不打印明文
- API 返回脱敏(`**********`)

### 7.2 引用保护
- KB 引用了 embedding model → 不能删
- 显示"被 X 个 KB 引用"
- UI 弹警告

### 7.3 验证
- 创建时 ping provider
- OpenAI: 调 `/v1/models` 列表
- Ollama: 调 `/api/tags`
- 失败: 创建不通过

### 7.4 Ollama 一键导入
- 流程:
  1. 调 Ollama `/api/tags` 拉模型列表
  2. 用户勾选要导的
  3. 批量建 model_config
- 默认勾选 embedding / chat 用途

### 7.5 平台 vs 租户
- 平台级 (`tenant_id IS NULL`): 预置
- 租户级 (`tenant_id=N`): 私有
- 租户可见: 平台 + 本租户

---

## 8. 关键代码

### 8.1 Provider 注册中心
```python
# backend/lumen_core/model_providers.py
MODEL_PROVIDERS = {
    "openai": {
        "type": "openai",
        "supported_models": ["gpt-4o", "gpt-3.5-turbo", "text-embedding-3-small", "dall-e-3", "tts-1"],
        "required_config": ["api_key"],
        "default_base_url": "https://api.openai.com/v1",
    },
    "ollama": {
        "type": "ollama",
        "supported_models": "*",  # 任何 ollama 模型
        "required_config": [],
        "default_base_url": "http://localhost:11434",
    },
    "stability": {
        "type": "stability",
        "supported_models": ["stable-diffusion-xl-1024-v1-0"],
        "required_config": ["api_key"],
        "default_base_url": "https://api.stability.ai",
    },
    "stub": {
        "type": "stub",
        "supported_models": ["mock"],
        "required_config": [],
        "default_base_url": "",
    },
}
```

### 8.2 工厂
```python
# backend/lumen_core/chat_model_factory.py
def build_chat_model(model_config: ModelConfig) -> BaseChatModel:
    if model_config.provider == "openai":
        return ChatOpenAI(
            model=model_config.model_name,
            api_key=model_config.api_key.get_secret_value(),
            base_url=model_config.base_url or None,
        )
    elif model_config.provider == "ollama":
        return ChatOllama(
            model=model_config.model_name,
            base_url=model_config.base_url,
        )
    # ...
```

### 8.3 引用保护
```python
@router.delete("/{model_id}", response_model=SingleResponse[None])
def delete_model(model_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    model = db.query(ModelConfig).filter(ModelConfig.id == model_id).first()
    if not model:
        raise HTTPException(404, "模型不存在")

    # 检查引用
    if model.is_embedding:
        ref_count = db.query(KnowledgeBase).filter(KnowledgeBase.embedding_model_config_id == model_id).count()
        if ref_count > 0:
            raise HTTPException(409, f"被 {ref_count} 个知识库引用,不能删除")

    db.delete(model)
    db.commit()
```

---

## 9. 边界与不做

### 9.1 当前
- ✅ 4 用途
- ✅ 多 provider
- ✅ Ollama 一键导入
- ✅ 默认模型
- ✅ 引用保护
- ✅ 凭证管理

### 9.2 不做
- ❌ 模型训练(走 [model-training](model-training.md))
- ❌ 模型微调
- ❌ 成本统计

---

## 10. 升级路径

### 短期
- 📋 成本统计(每租户 / 每日)
- 📋 调用限流(每模型)

### 中期
- 📋 模型评分
- 📋 自动选模型(按场景)

### 长期
- 📋 模型微调
- 📋 联邦推理

---

## 11. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| 创建 401 | api_key 错 | 改凭证 |
| Ollama 连不上 | 容器挂 / 端口错 | 测端口 |
| 引用错 | KB 用了不同 model | 统一 |
| Secret 暴露 | 日志没脱敏 | 用 SecretStr |
| 默认切换失败 | 多默认 | 改 1 个默认 |

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
