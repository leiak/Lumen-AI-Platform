"""M36: VideoComposeNode — 在工作流里调度一次 mp4 合成。

设计取舍(与 TTS 不同)
------------------------
- ``TTSNode``(M35)用 BackgroundTasks 异步派发,workflow 立刻拿到
  ``job_id``,下游靠轮询拿音频 URL。
- ``VideoComposeNode``(M36)用 **同步** 路径
  (``VideoComposeService.create_sync_for_workflow``),workflow 阻塞
  等 mp4 落盘后再继续。原因:视频合成是工作流尾部的产出节点,下游
  (Notification / CDN 上传 / Knowledge 入库等)要拿到视频 URL 才能
  动。让一个 30s+ 的合成本身在节点里跑完,workflow 的语义比 TTS
  那种"派发+轮询"更直观,也避免了 condition / parallel 节点重复实现
  重试+轮询。

输入约定
--------
- ``source_images``: ``list[str]``。每一项可以是:
  * 图像本地路径(``"/tmp/foo.png"``)→ 直接使用
  * GeneratedImage 的 id(``"42"``)→ 查 DB 拿 ``file_path``
  * image-generation URL(``"/api/v1/image-generation/42/image"``)→
    解析 id 再查 DB
  * ``{{node.image_url}}`` 模板引用,先由 ``VariableTemplateParser``
    替换为以上三种之一
- ``audio_path`` / ``subtitle_path``: 同样允许本地路径或 id 引用
  (由 service 内部的 ``_resolve_asset_to_path`` 解析 — 不支持 URL)。

outputs: ``video_id``, ``video_url``, ``status``, ``duration_ms``,
``file_size``。``video_url`` 是 Bearer-auth 保护的下载端点,前端
跟图像/音频一样走 fetch+blob+createObjectURL 模式。

Spec: docs-internal/superpowers/specs/m36-multimodal-foundation.md §4
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import ConfigDict, Field

from lumen_core.workflow.entities import BaseNodeData, NodeRunResult, OutputVar
from lumen_core.workflow.nodes.base import BaseNode
from lumen_core.workflow.template_parser import VariableTemplateParser
from lumen_core.workflow.types import SegmentType
from lumen_schemas.video import VideoComposeCreate

# 解析 ``source_images`` 里每条 entry(URL / digit / 字面路径)→ 磁盘绝对
# 路径,集中放在 service 层(同时支持 image-generation + M36.2.1 stock)。
from lumen_services.video_compose_service import (
    _resolve_image_to_local_path,
)


class VideoComposeNodeData(BaseNodeData):
    model_config = ConfigDict(extra="ignore")

    # 图像:list[str],支持路径/URL/id/{{...}} 模板
    source_images: List[str] = Field(
        default_factory=list,
        description="图像列表(本地路径/GeneratedImage id/GET URL/{{node.image_url}} 模板)",
    )
    audio_path: Optional[str] = Field(
        None,
        description="音频路径 或 generated_audios.id(数字字串)。None → 合成静默",
    )
    subtitle_path: Optional[str] = Field(
        None,
        description="字幕 SRT 路径 或 subtitles.id(数字字串)。None → 无字幕烧录",
    )
    # M36.2.2: 背景音乐,跟 audio_path / subtitle_path 同模式(本地路径
    # 或 stock_musics.id)。None → 不加 BGM,workflow 节点跟 dashboard
    # 走完全相同的 _resolve_asset_to_path 路径。
    background_music_path: Optional[str] = Field(
        None,
        description="背景音乐路径 或 stock_musics.id(整数)。None → 不加 BGM",
    )
    background_music_volume: float = Field(
        default=0.3, ge=0.0, le=1.0,
        description="BGM 音量相对主轨的比例 (0.0 - 1.0)",
    )
    # 构图参数
    resolution: str = Field(default="1280x720")
    fps: int = Field(default=24, ge=1, le=60)
    audio_fade_in: float = Field(default=0.0, ge=0.0, le=10.0)
    audio_fade_out: float = Field(default=0.0, ge=0.0, le=10.0)
    subtitle_font: Optional[str] = Field(
        None, description='字体名,如 "Microsoft YaHei"',
    )
    per_image_seconds: Optional[float] = Field(
        None, gt=0.0, description="单图显示时长覆盖(>1 张图时生效)",
    )


class VideoComposeNode(BaseNode):
    """Synchronously compose an mp4 from upstream assets.

    Unlike TTSNode this does NOT return a job id to poll — the workflow
    blocks here until the mp4 lands on disk and the row flips to
    ``status=completed``. If FFmpeg fails the node raises ValueError
    (propagated to the executor's retry / error_strategy).
    """

    metadata_type = "video_compose"
    metadata_label = "视频合成"
    metadata_description = (
        "把图像+音频+字幕合成 mp4(同步等待)。下游可拿 video_url。"
    )
    metadata_icon = "🎬"
    metadata_color = "magenta"
    metadata_category = "integration"

    def init_node_data(self, config: dict) -> BaseNodeData:
        return VideoComposeNodeData.model_validate(
            {**config, "version": config.get("version", "1")}
        )

    def outputs(self) -> list[OutputVar]:
        return [
            OutputVar(
                name="video_id", type=SegmentType.NUMBER,
                description="generated_videos.id",
            ),
            OutputVar(
                name="video_url", type=SegmentType.STRING,
                description="GET /api/v1/videos/{id}/download(Bearer auth)",
            ),
            OutputVar(
                name="status", type=SegmentType.STRING,
                description="completed / failed",
            ),
            OutputVar(
                name="duration_ms", type=SegmentType.NUMBER,
                description="ffprobe 读到的 mp4 时长(毫秒)",
            ),
            OutputVar(
                name="file_size", type=SegmentType.NUMBER,
                description="mp4 文件字节数",
            ),
        ]

    async def _run(self) -> NodeRunResult:
        assert isinstance(self._data, VideoComposeNodeData)
        d: VideoComposeNodeData = self._data

        if self.db is None or self.tenant_id is None:
            raise ValueError(
                "VideoComposeNode 必须在工作流执行上下文(带 db + tenant_id)里运行"
            )
        if not d.source_images:
            raise ValueError("source_images 不能为空")

        # 1. 解析图像:每一项经过 VariableTemplateParser(把 {{node.x}} 替换成
        #    上游输出字符串),再 _resolve_image_to_local_path 查 DB 转本地路径。
        resolved_images: List[str] = []
        for raw in d.source_images:
            text = VariableTemplateParser(raw).format(self.pool)
            if not text or not text.strip():
                continue
            local = _resolve_image_to_local_path(
                self.db, self.tenant_id, text,  # type: ignore[arg-type]
            )
            if local is None:
                raise ValueError(
                    f"image '{text}' 无法解析到本地路径(可能 url-id 找不到、"
                    f"或路径不存在)"
                )
            resolved_images.append(local)
        if not resolved_images:
            raise ValueError("source_images 解析后为空")

        # 2. 解析 audio / subtitle — 这两个交给 service 内部的
        #    _resolve_asset_to_path 来做(支持空/数字 id/字面路径)。
        #    node 层只做模板替换,不做实质转换。
        audio_path = (
            VariableTemplateParser(d.audio_path).format(self.pool).strip()
            if d.audio_path else None
        )
        subtitle_path = (
            VariableTemplateParser(d.subtitle_path).format(self.pool).strip()
            if d.subtitle_path else None
        )
        bgm_path = (
            VariableTemplateParser(d.background_music_path).format(self.pool).strip()
            if d.background_music_path else None
        )
        # 模板替换后空字符串 → None(避免把空字串传进 service,导致后续
        # _resolve_asset_to_path 走到 isdigit 分支报错)
        if audio_path == "":
            audio_path = None
        if subtitle_path == "":
            subtitle_path = None
        if bgm_path == "":
            bgm_path = None

        # 3. 同步调用 VideoComposeService.create_sync_for_workflow。
        from lumen_services.video_compose_service import VideoComposeService

        service = VideoComposeService()
        payload = VideoComposeCreate(
            source_images=resolved_images,
            audio_path=audio_path,
            subtitle_path=subtitle_path,
            background_music_path=bgm_path,
            background_music_volume=d.background_music_volume,
            resolution=d.resolution,
            fps=d.fps,
            audio_fade_in=d.audio_fade_in,
            audio_fade_out=d.audio_fade_out,
            subtitle_font=d.subtitle_font,
            per_image_seconds=d.per_image_seconds,
        )
        row, err = service.create_sync_for_workflow(
            self.db,
            tenant_id=self.tenant_id,
            user_id=_resolve_user_id(self.db, self.tenant_id),  # type: ignore[arg-type]
            payload=payload,
        )
        if err:
            raise ValueError(f"Video compose failed: {err}")
        assert row is not None
        return NodeRunResult(
            node_id=self.node_id,
            output_values={
                "video_id": row.id,
                "video_url": f"/api/v1/videos/{row.id}/download",
                "status": row.status,
                "duration_ms": row.duration_ms or 0,
                "file_size": row.file_size or 0,
            },
        )


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _resolve_user_id(db, tenant_id: int) -> int:
    """挑一个 active user 当 GeneratedVideo.user_id。

    workflow executor 不直接传 user_id 进 node;写 DB 的 node 挑
    tenant 的 primary user。这跟 TTSNode 的策略保持一致。
    """
    from lumen_models.user import User
    u = (
        db.query(User)
        .filter(User.tenant_id == tenant_id, User.is_active.is_(True))
        .order_by(User.id.asc())
        .first()
    )
    if u is None:
        raise ValueError(f"No active user in tenant {tenant_id} for video job")
    return u.id
