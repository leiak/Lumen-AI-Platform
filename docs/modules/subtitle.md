# 模块:SRT 字幕生成

> Lumen AI Platform 的 SRT 字幕生成能力。
> 文档讲透怎么把文本转成 SRT、怎么翻译、怎么嵌入视频。

---

## 1. 产品定位

**SRT 是什么?**
- SubRip 字幕格式
- 1 个 .srt 文件 = 1 段视频的字幕
- 格式: `序号 \n 时间戳 \n 文本 \n\n`

**业务场景?**
- 视频字幕
- 教学视频
- 培训材料
- 视频号 / 抖音

---

## 2. 功能清单

| 功能 | 描述 |
|------|------|
| 文本 → SRT | 按字符密度分配时间戳 |
| 中英混合 | 不报错 |
| 时间校准 | 总时长可控 |
| 翻译 | 中 → 英 / 英 → 中(LLM) |
| 嵌入视频 | 视频合成时一起 |

---

## 3. 字幕生成算法

### 3.1 核心问题
- 给一段文本 + 总时长 → 切分 + 分配时间戳

### 3.2 算法:字符密度分配
```
总时长 D, 总字符数 N
每字符权重 = D / N
每条字幕长度 L 条
本条时长 = L * 每字符权重

切分:按句子(中文) / 单词(英文)
合并:单条 < 1.5 秒 或 字符 < 5 时合并下一句
```

### 3.3 输出
```srt
1
00:00:00,000 --> 00:00:02,500
今天我们来聊一聊 AI Agent

2
00:00:02,500 --> 00:00:05,000
它能帮我们自动处理很多工作

3
00:00:05,000 --> 00:00:07,800
比如客服、销售、知识库
```

---

## 4. 关键能力详解

### 4.1 中英混合
- 不依赖分词
- 按字符密度算
- 中英混排不报错

### 4.2 总时长校准
- 输入:总秒数(或视频时长)
- 算法:按密度算
- 输出:实际总时长 ≈ 输入时长(±0.5 秒)

### 4.3 单条长度限制
- 中文: ≤ 25 字
- 英文: ≤ 80 字符
- 超过自动切分

### 4.4 时间戳格式
- `HH:MM:SS,mmm`
- 用逗号(欧洲格式),不是点
- SRT 标准

---

## 5. 翻译(可选)

### 5.1 流程
```
原文 (SRT)
   │
   ▼
LLM 翻译
   │
   ▼
译文 (SRT,同样时间戳)
```

### 5.2 实现
- LLM 逐条翻译(保持时间戳)
- 提示词: "保持时间戳,只翻译文本"
- 失败:回退到原文

### 5.3 质量
- LLM 翻译质量中等
- 适合:视频字幕 / 简单场景
- 不适合:专业内容(法律 / 医疗)

---

## 6. 数据模型

### 6.1 subtitles
```python
class Subtitle(Base):
    id: int
    user_id: int
    tenant_id: int
    name: str
    text: str                     # 原始文本
    total_duration_seconds: float
    srt_content: str              # SRT 文本
    language: str                 # zh / en
    translated: bool
    translated_srt: str
    video_id: int                 # 关联视频(可空)
    created_at
```

### 6.2 文件
- ORM: `backend/lumen_models/subtitle.py`
- Schema: `backend/lumen_schemas/subtitle.py`
- 服务: `backend/lumen_services/subtitle_service.py`
- 算法: `backend/lumen_tools/srt.py`
- 路由: `backend/lumen_api/v1/subtitle.py`

---

## 7. UI

### 7.1 创建
- 路径: `frontend/app/dashboard/videos` 内嵌(视频合成时)
- 或 API 调
- 表单:text / 总时长 / 语言 / 翻译

### 7.2 预览 / 编辑
- 时间码表
- 文本编辑
- 下载 .srt 文件

---

## 8. 关键代码

### 8.1 SRT 生成
```python
# backend/lumen_tools/srt.py
def generate_srt(text: str, total_duration: float) -> str:
    # 1. 切分(按句)
    sentences = split_sentences(text)
    # 2. 字符数
    total_chars = sum(len(s) for s in sentences)
    # 3. 每字符时间
    per_char = total_duration / total_chars
    # 4. 生成 SRT
    srt_lines = []
    current_time = 0.0
    for i, sent in enumerate(sentences, 1):
        duration = len(sent) * per_char
        srt_lines.append(str(i))
        srt_lines.append(f"{format_timestamp(current_time)} --> {format_timestamp(current_time + duration)}")
        srt_lines.append(sent)
        srt_lines.append("")
        current_time += duration
    return "\n".join(srt_lines)

def format_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
```

### 8.2 切分算法
```python
def split_sentences(text: str) -> list[str]:
    # 中文:按 。!? 切
    # 英文:按 .!? 切
    # 中英混合:正则
    pattern = re.compile(r'[^.!?。！？]+[.!?。！？]?')
    return [s.strip() for s in pattern.findall(text) if s.strip()]
```

---

## 9. 嵌入视频

### 9.1 视频合成时
- 视频合成服务接受 srt 参数
- 用 ffmpeg 烧字幕:
  ```
  ffmpeg -i video.mp4 -vf subtitles=sub.srt -c:a copy output.mp4
  ```

详见 [video-composition](video-composition.md)。

---

## 10. 边界与不做

### 10.1 当前
- ✅ 字符密度算法
- ✅ 中英混合
- ✅ 时间校准
- ✅ 翻译(LLM)
- ✅ 嵌入视频

### 10.2 不做
- ❌ ASR(语音 → 字幕)
- ❌ 字幕样式(只生成 .srt,样式靠播放器)
- ❌ 多语言同条字幕

---

## 11. 升级路径

### 短期
- 📋 ASR 集成
- 📋 字幕样式导出

### 中期
- 📋 多语言对齐
- 📋 自动断句(更智能)

### 长期
- 📋 字幕翻译记忆库

---

## 12. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| SRT 格式错 | 编码问题 | 用 UTF-8 |
| 时间戳错 | 时长不准 | 改 total_duration |
| 中文乱码 | 编码错 | 改 UTF-8 BOM 头 |
| 翻译失败 | LLM 错 | 回退原文 |
| 字幕太长 | 单条 > 25 字 | 改 max_length |

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
