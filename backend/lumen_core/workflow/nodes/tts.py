"""M35: TTSNode — 在工作流里调度一次语音合成。

不阻塞工作流执行:节点把请求投递给 ``TTSService.create()``,立刻返回
job_id;音频生成由 FastAPI BackgroundTasks 异步完成。下游节点可以
通过 ``GET /api/v1/tts/jobs/{job_id}`` 轮询状态,或在 UI 里等待
``AUDIO_GENERATION_COMPLETED`` 通知。

设计取舍:不直接 await 整个 TTS(可能几十秒)是为了让工作流设计器
能把"派发 TTS + 后续处理"组合成一个 DAG;真正需要等结果的场景
可以通过 condition / parallel 节点 + 重试实现。

Spec: docs-internal/superpowers/specs/M35-tts-node.md
"""
from typing import Optional

from fastapi import BackgroundTasks
from pydantic import ConfigDict, Field

from lumen_core.workflow.entities import BaseNodeData, NodeRunResult, OutputVar
from lumen_core.workflow.nodes.base import BaseNode
from lumen_core.workflow.template_parser import VariableTemplateParser
from lumen_core.workflow.types import SegmentType


class TTSNodeData(BaseNodeData):
    model_config = ConfigDict(extra="ignore")
    # model_config_id intentionally NOT pre-rendered: it points at the
    # model's id in the DB and must be a static int. Downstream nodes
    # that need the audio row use job_id.
    model_config_id: int
    text: str = ""
    voice: str = "default"
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    format: str = "mp3"
    playbook_id: Optional[int] = None
    # Polling hint for downstream nodes / UI: how long to wait before
    # assuming the job is "done enough" (status=pending or running).
    poll_timeout_ms: int = 60000


class TTSNode(BaseNode):
    """Schedule a TTS job. Returns immediately with the job id and
    initial status; the audio bytes are produced by the background
    task and surfaced via the standard /tts/jobs/{id} endpoint.
    """

    metadata_type = "tts"
    metadata_label = "语音合成"
    metadata_description = "把一段文字转成语音(Edge TTS / Piper / OpenAI)"
    metadata_icon = "🔊"
    metadata_color = "volcano"
    metadata_category = "integration"

    def init_node_data(self, config: dict) -> BaseNodeData:
        return TTSNodeData.model_validate(
            {**config, "version": config.get("version", "1")}
        )

    def outputs(self) -> list[OutputVar]:
        return [
            OutputVar(name="job_id", type=SegmentType.NUMBER, description="TTS job id"),
            OutputVar(name="status", type=SegmentType.STRING, description="initial status (pending|running|completed|failed)"),
            OutputVar(name="text", type=SegmentType.STRING, description="最终合成的文本(playbook enrichment 后的)"),
            OutputVar(name="audio_url", type=SegmentType.STRING, description="GET /api/v1/tts/jobs/{job_id}/audio (Bearer auth required)"),
        ]

    async def _run(self) -> NodeRunResult:
        assert isinstance(self._data, TTSNodeData)
        d: TTSNodeData = self._data
        if d.model_config_id <= 0:
            raise ValueError("model_config_id 必须 > 0")
        text = VariableTemplateParser(d.text).format(self.pool)
        if not text:
            raise ValueError("text 不能为空")

        # We need a BackgroundTasks for the TTSService.create()
        # scheduling. The executor's per-node flow doesn't carry one
        # by default; build a local instance. FastAPI BackgroundTasks
        # has a no-op ``add_task`` when not invoked within a request,
        # so this is safe for the dry-run case (a unit test calling
        # node._run() directly won't dispatch anything).
        from lumen_services.tts_service import TTSService

        bg = BackgroundTasks()
        if self.db is None or self.tenant_id is None:
            raise ValueError("TTSNode 必须在工作流执行上下文(带 db + tenant_id)里运行")
        service = TTSService()
        row, err = service.create(
            self.db,
            tenant_id=self.tenant_id,
            user_id=_resolve_user_id(self.db, self.tenant_id),
            model_config_id=d.model_config_id,
            text=text,
            voice=d.voice,
            speed=d.speed,
            format=d.format,
            playbook_id=d.playbook_id,
            background_tasks=bg,
        )
        if err:
            raise ValueError(f"TTS job creation failed: {err}")
        assert row is not None
        audio_url = f"/api/v1/tts/jobs/{row.id}/audio"
        return NodeRunResult(
            node_id=self.node_id,
            output_values={
                "job_id": row.id,
                "status": row.status,
                "text": text,
                "audio_url": audio_url,
            },
        )


def _resolve_user_id(db, tenant_id: int) -> int:
    """Pick a user_id for the TTS row.

    The workflow executor doesn't pass a user_id directly to nodes;
    nodes that write to the DB pick the tenant's primary user. The
    billing / audit trail still tags the row with this user, but for
    workflow-driven jobs we accept "any user in this tenant" since the
    workflow itself is the actor.
    """
    from lumen_models.user import User
    u = db.query(User).filter(
        User.tenant_id == tenant_id, User.is_active.is_(True),
    ).order_by(User.id.asc()).first()
    if u is None:
        raise ValueError(f"No active user in tenant {tenant_id} for TTS job")
    return u.id
