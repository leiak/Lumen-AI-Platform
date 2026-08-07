# 模块:视频合成

> Lumen AI Platform 的视频合成能力(M36)。
> 文档讲透视频怎么拼、怎么配音、怎么烧字幕。

---

## 1. 产品定位

**视频合成是什么?**
- 把图片 + 音频 + 字幕 拼成视频
- 用 ffmpeg
- 后台任务

**业务场景?**
- 公众号视频号
- 营销视频
- AI 配音 + 字幕
- 培训视频

---

## 2. 功能清单

| 功能 | 描述 |
|------|------|
| 图片拼装 | 多图 → 视频(每图 5 秒) |
| 音频叠加 | TTS / 背景音乐 |
| 字幕烧入 | SRT 字幕嵌入 |
| 转场 | 简单淡入淡出 |
| 缩略图 | 自动生成 |
| 后台任务 | Celery 异步 |
| 取消 | 中断长时间任务 |
| 下载 | mp4 流式 |

---

## 3. 数据模型

### 3.1 videos
```python
class Video(Base):
    id: int
    user_id: int
    tenant_id: int
    name: str
    image_paths: list             # 图片路径(本地 / URL)
    audio_path: str               # 音频路径(可空)
    subtitle_srt: str             # SRT 文本(可空)
    background_music_path: str    # 背景音乐(可空)
    total_duration_seconds: float
    status: str                   # pending / composing / success / failed / cancelled
    file_path: str                # 输出 mp4
    thumbnail_path: str
    error: str
    created_at, finished_at
```

### 3.2 文件
- ORM: `backend/lumen_models/video.py`
- Schema: `backend/lumen_schemas/video.py`
- 服务: `backend/lumen_services/video_compose_service.py`
- ffmpeg: `backend/lumen_tools/video_compose.py`
- Celery: `backend/lumen_tasks/video_tasks.py`
- 路由: `backend/lumen_api/v1/video.py`

---

## 4. UI

### 4.1 列表
- 路径: `frontend/app/dashboard/videos/page.tsx`
- 表格:名字 / 时长 / 状态 / 创建时间 / 操作
- 操作:播放 / 下载 / 取消 / 删

### 4.2 创建
- ComposeModal:
  - 上传图片 / 从素材库选
  - 加音频(TTS 任务 / 上传)
  - 加字幕
  - 设置总时长
- 提交 → 后台

### 4.3 关键组件
- `frontend/services/video.ts`
- `frontend/components/video/ComposeModal.tsx`
- `frontend/components/video/StockPickerModal.tsx`(从素材库选)

---

## 5. 关键能力详解

### 5.1 图片拼装
- 每张图 5 秒(可配)
- 分辨率:统一 1920x1080(可配)
- 格式:jpeg / png

### 5.2 音频叠加
- 主轨: TTS 音频
- 背景: 背景音乐(音量 30%)
- ffmpeg:
  ```
  ffmpeg -i video.mp4 -i tts.mp3 -filter_complex "amix=inputs=2:duration=first" -c:a aac output.mp4
  ```

### 5.3 字幕烧入
- SRT 嵌入
- ffmpeg:
  ```
  ffmpeg -i video.mp4 -vf "subtitles=sub.srt:force_style='FontSize=24,PrimaryColour=&Hffffff&'" -c:a copy output.mp4
  ```

### 5.4 转场
- 简单淡入淡出(xfade)
- 高级转场计划中

### 5.5 取消
- Celery `revoke(task_id, terminate=True)`
- 标记 `videos.status=cancelled`

---

## 6. 关键代码

### 6.1 图片拼装
```python
# backend/lumen_tools/video_compose.py
def compose_from_images(image_paths: list[str], output_path: str, duration_per_image: int = 5):
    # 用 ffmpeg concat
    list_file = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    for img in image_paths:
        list_file.write(f"file '{img}'\nduration {duration_per_image}\n")
    list_file.close()

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", list_file.name,
        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        output_path,
    ]
    subprocess.run(cmd, check=True)
```

### 6.2 加音频 + 字幕
```python
def add_audio_and_subtitle(video_path: str, audio_path: str, srt_path: str, output_path: str):
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-vf", f"subtitles={srt_path}",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-shortest",
        output_path,
    ]
    subprocess.run(cmd, check=True)
```

### 6.3 Celery 任务
```python
# backend/lumen_tasks/video_tasks.py
@celery_app.task(bind=True)
def compose_video(self, video_id: int):
    video = load_video(video_id)
    try:
        # 1. 解析图片
        local_image_paths = [resolve_image_to_local_path(p) for p in video.image_paths]

        # 2. 拼装
        temp_video = f"storage/_tmp/{video_id}_video.mp4"
        compose_from_images(local_image_paths, temp_video, duration_per_image=5)

        # 3. 加音频 + 字幕
        final_path = f"storage/generated_videos/{video.tenant_id}/{date}/{video_id}.mp4"
        if video.audio_path or video.subtitle_srt:
            add_audio_and_subtitle(temp_video, video.audio_path, video.subtitle_srt, final_path)
        else:
            os.rename(temp_video, final_path)

        # 4. 缩略图
        thumbnail = make_thumbnail(final_path)

        # 5. 更新
        video.file_path = final_path
        video.thumbnail_path = thumbnail
        video.status = "success"
        save(video)

        notify_ws(video.user_id, "video_complete", {"id": video_id})
    except Exception as e:
        video.status = "failed"
        video.error = str(e)
        save(video)
```

---

## 7. 性能

| 阶段 | 耗时(1 分钟视频) |
|------|------------------|
| 图片拼装 | 10~30 秒 |
| 加音频 | 5~10 秒 |
| 烧字幕 | 10~20 秒 |
| 缩略图 | 2~5 秒 |
| **合计** | **30~60 秒** |

---

## 8. 边界与不做

### 8.1 当前
- ✅ 图片 → 视频
- ✅ 加音频
- ✅ 烧字幕
- ✅ 取消 / 下载
- ✅ 股票素材选择

### 8.2 不做
- ❌ 视频剪辑
- ❌ 实时预览
- ❌ 复杂转场

---

## 9. 升级路径

### 短期
- 📋 视频模板
- 📋 简单剪辑

### 中期
- 📋 AI 自动剪辑
- 📋 视频滤镜

### 长期
- 📋 AI 视频生成(扩展 Sora / 可灵)
- 📋 实时协作编辑

---

## 10. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| ffmpeg 找不到 | PATH 错 | 装 ffmpeg |
| 视频黑屏 | 图片路径错 | 改路径 |
| 字幕不显示 | 编码错 | 改 UTF-8 |
| 取消无效 | Celery 任务没启 revoke | 修 Celery 配置 |
| 缩略图 0 字节 | ffmpeg 错 | 看日志 |
| 图片 URL 路径解析失败 | 服务没支持 URL 解析 | 改 `_resolve_image_to_local_path` (M36.2.1.x) |

详见 [troubleshooting/common-errors.md](../troubleshooting/common-errors.md)。

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
