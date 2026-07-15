"""M35: PlaybookInjectNode — 在工作流里把 playbook 风格注入到文本。

典型用法:
  input node (text)  →  playbook_inject (选 clean-professional)  →
  llm / tts / image node

`text` 字段是 base input(支持 {{ node_id.var }} 模板);`playbook_id`
是可选的 playbook ID,空则直通。`target` 选择注入目标
(image_prompt / tts_prompt),影响注入哪些 token。

Spec: docs-internal/superpowers/specs/M35-playbook-inject-node.md
"""
from typing import Literal

from pydantic import ConfigDict, Field

from lumen_core.workflow.entities import BaseNodeData, NodeRunResult, OutputVar
from lumen_core.workflow.nodes.base import BaseNode
from lumen_core.workflow.template_parser import VariableTemplateParser
from lumen_core.workflow.types import SegmentType

InjectTarget = Literal["image_prompt", "tts_prompt"]


class PlaybookInjectNodeData(BaseNodeData):
    model_config = ConfigDict(extra="ignore")
    text: str = ""
    playbook_id: int | None = None
    target: InjectTarget = "image_prompt"


class PlaybookInjectNode(BaseNode):
    """Inject a Playbook's style tokens into a base text.

    Outputs:
    - enriched_text: the base text with the playbook's keywords /
      palette / voice direction appended
    - playbook_id:   the playbook id used (echoed so downstream nodes
                     can reference it without re-resolving)
    """

    metadata_type = "playbook_inject"
    metadata_label = "风格注入"
    metadata_description = "把 playbook 的关键词/调色/语速等风格 token 拼接到输入文本"
    metadata_icon = "🎨"
    metadata_color = "magenta"
    metadata_category = "process"

    def init_node_data(self, config: dict) -> BaseNodeData:
        return PlaybookInjectNodeData.model_validate(
            {**config, "version": config.get("version", "1")}
        )

    def outputs(self) -> list[OutputVar]:
        return [
            OutputVar(name="enriched_text", type=SegmentType.STRING, description="注入风格后的文本"),
            OutputVar(name="playbook_id", type=SegmentType.NUMBER, description="playbook id (透传)"),
        ]

    async def _run(self) -> NodeRunResult:
        assert isinstance(self._data, PlaybookInjectNodeData)
        d: PlaybookInjectNodeData = self._data

        base_text = VariableTemplateParser(d.text).format(self.pool)

        # Lazy import to avoid pulling PlaybookService at module load
        # (keeps workflow designer import time fast).
        from lumen_services.playbook_service import (
            get_for_tenant as get_playbook_for_tenant,
            inject_into_prompt,
        )

        pb = None
        if d.playbook_id is not None and self.db is not None and self.tenant_id is not None:
            pb = get_playbook_for_tenant(
                self.db,
                tenant_id=self.tenant_id,
                playbook_id=d.playbook_id,
            )
        enriched = inject_into_prompt(pb or {}, base_text, d.target) if pb else base_text
        return NodeRunResult(
            node_id=self.node_id,
            output_values={
                "enriched_text": enriched,
                "playbook_id": d.playbook_id,
            },
        )
