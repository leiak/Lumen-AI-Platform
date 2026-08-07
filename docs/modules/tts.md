# 模块:TTS 语音合成

> Lumen AI Platform 的 TTS(Text-to-Speech)能力。
> 文档讲透能用哪些 provider、怎么用、与 Playbook 集成。

---

## 1. 产品定位

**TTS 是什么?**
- 把文字转语音
- 多 provider 抽象:Edge TTS / Piper / OpenAI / Stub
- 异步任务 + 流式下载

**业务场景?**
- 公众号音频
- 视频配音
- 有声书
- AI 助手语音

---

## 2. 功能清单

| 功能 | 描述 |
|------|------|
| 4 provider 抽象 | Edge TTS / Piper / OpenAI / Stub |
| Playbook 集成 | 语音风格 / 语速 |
| 后台任务 | Celery 异步生成 |
| 流式下载 | Bearer 鉴权 |
| 多语言 | 中 / 英 / 日 / ... |
| 历史记录 | 列表 + 搜索 |

---

## 3. 4 个 Provider

| Provider | 模型 | 费用 | 速度 | 中文 |
|----------|------|------|------|------|
| **Edge TTS** | Microsoft Edge 在线 | 免费 | 快 | ✅ |
| **Piper** | 本地 ONNX | 免费 | 中 | ✅ |
| **OpenAI** | TTS-1 / TTS-1-HD | $$ | 快 | ✅ |
| **Stub** | mock 音频 | 免费 | 立刻 | - |

### 3.1 推荐
- **demo / 内部** → Edge TTS(免费 + 中文好)
- **生产** → OpenAI TTS-1-HD(质量高)
- **私有化** → Piper(本地)
- **测试** → Stub

---

## 4. 数据模型

### 4.1 tts_jobs
```python
class TTSJob(Base):
    id: int
    user_id: int
    tenant_id: int
    text: str
    provider: str                 # edge / piper / openai / stub
    voice: str                    # "zh-CN-XiaoxiaoNeural" / "alloy" / ...
    speed: float                  # 0.5~2.0
    pitch: float                  # -12~12
    playbook_id: int
    status: str                   # pending / running / success / failed
    file_path: str                # mp3 路径
    duration_seconds: float
    error: str
    created_at, finished_at
```

### 4.2 文件
- ORM: `backend/lumen_models/tts.py`
- Schema: `backend/lumen_schemas/tts.py`
- 服务: `backend/lumen_services/tts_service.py`
- Celery: `backend/lumen_tasks/tts_tasks.py`
- Provider: `backend/lumen_tools/tts_providers/{edge,piper,openai,stub}.py`
- 路由: `backend/lumen_api/v1/tts.py`

---

## 5. UI

### 5.1 列表
- 路径: `frontend/app/dashboard/tts/page.tsx`
- 表格:text / provider / voice / 状态 / 时长 / 操作
- 操作:播放 / 下载 / 删

### 5.2 创建
- 表单:text / provider / voice / speed / Playbook
- 提交 → 后台任务

### 5.3 音频播放
- HTML5 `<audio>` 标签
- 受保护资源:fetch + blob + createObjectURL

---

## 6. 关键能力详解

### 6.1 Playbook 集成
- `playbook.voice_direction`: 注入到 TTS(例: "请用温柔女声")
- 选 Playbook → 注入 voice / speed / pitch

### 6.2 流式下载
- 端点: `GET /api/v1/tts/jobs/{id}/audio`
- 鉴权: `Authorization: Bearer <token>`
- 返回 mp3 二进制流
- 不走信封

### 6.3 失败重试
- 3 次 + 指数退避

### 6.4 多语言
- Edge TTS: 100+ voice,40+ 语言
- Piper: 离线模型,中英主流
- OpenAI: 6 voice,多语言

---

## 7. 性能

| Provider | 耗时(100 字) |
|----------|--------------|
| Edge TTS | 2~5 秒 |
| Piper | 5~10 秒 |
| OpenAI | 2~4 秒 |
| Stub | < 0.1 秒 |

---

## 8. 关键代码

### 8.1 Provider 抽象
```python
# backend/lumen_tools/tts_providers/base.py
class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str, voice: str, **kwargs) -> bytes:
        pass

# edge.py
class EdgeTTSProvider(TTSProvider):
    async def synthesize(self, text, voice="zh-CN-XiaoxiaoNeural", **kwargs):
        communicate = edge_tts.Communicate(text, voice)
        audio = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio.write(chunk["data"])
        return audio.getvalue()
```

### 8.2 流式下载
```python
# backend/lumen_api/v1/tts.py
@router.get("/jobs/{job_id}/audio")
def download_audio(job_id: int, current_user: User = Depends(get_current_user)):
    job = load_tts_job(job_id, current_user.tenant_id)
    if not job or job.status != "success":
        raise HTTPException(404)
    return FileResponse(
        job.file_path,
        media_type="audio/mpeg",
        filename=f"tts_{job_id}.mp3"
    )
```

### 8.3 前端播放
```tsx
const [audioUrl, setAudioUrl] = useState<string>('')

const playAudio = async (jobId: number) => {
  const res = await fetch(`${API_URL}/tts/jobs/${jobId}/audio`, {
    headers: { Authorization: `Bearer ${token}` }
  })
  const blob = await res.blob()
  if (audioUrl) URL.revokeObjectURL(audioUrl)
  setAudioUrl(URL.createObjectURL(blob))
}
```

---

## 9. 边界与不做

### 9.1 当前
- ✅ 4 provider
- ✅ Playbook 集成
- ✅ 后台任务
- ✅ 流式下载
- ✅ 失败重试

### 9.2 不做
- ❌ 实时流式合成
- ❌ 语音克隆
- ❌ 多人对话(每句不同 voice)

---

## 10. 升级路径

### 短期
- 📋 实时流式合成
- 📋 SSML 支持

### 中期
- 📋 语音克隆
- 📋 多人对话

### 长期
- 📋 情感语音
- 📋 实时翻译

---

## 11. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| 401 Edge | 网络问题 | 测连通性 |
| 401 OpenAI | API key 错 | 改凭证 |
| 音频 0 字节 | provider 错 | 换 provider |
| 中文不标准 | voice 选错 | 换中文 voice |
| 一直 pending | Celery 没跑 | 启 worker |
| 流式下载 401 | token 没带 | 改 Bearer 模式 |

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
