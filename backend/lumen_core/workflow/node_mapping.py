"""节点类型 → 类的注册表。

每个节点类型 (input / agent / llm / ... / end) 维护一个版本号 → 类的 dict。
版本未知时,`resolve_node_class` 静默回退到 v1,这样老的 workflow JSON 即使存了
新版本号也能继续工作(在 v1 仍可用的前提下)。v1 必须存在;否则视为配置错误。
"""

from lumen_core.workflow.nodes.agent import AgentNode
from lumen_core.workflow.nodes.base import BaseNode
from lumen_core.workflow.nodes.code import CodeNode
from lumen_core.workflow.nodes.condition import ConditionNode
from lumen_core.workflow.nodes.end import EndNode
from lumen_core.workflow.nodes.fan_in import FanInNode
from lumen_core.workflow.nodes.fan_out import FanOutNode
from lumen_core.workflow.nodes.http import HTTPNode
from lumen_core.workflow.nodes.input import InputNode
from lumen_core.workflow.nodes.knowledge_retrieval import KnowledgeRetrievalNode
from lumen_core.workflow.nodes.llm import LLMNode
from lumen_core.workflow.nodes.output import OutputNode
from lumen_core.workflow.nodes.parallel import ParallelNode
from lumen_core.workflow.nodes.parameter_extractor import ParameterExtractorNode
from lumen_core.workflow.nodes.playbook_inject import PlaybookInjectNode  # M35
from lumen_core.workflow.nodes.question_classifier import QuestionClassifierNode
from lumen_core.workflow.nodes.start import StartNode
from lumen_core.workflow.nodes.template_transform import TemplateTransformNode
from lumen_core.workflow.nodes.tool import ToolNode
from lumen_core.workflow.nodes.tts import TTSNode  # M35
from lumen_core.workflow.nodes.variable_assigner import VariableAssignerNode
from lumen_core.workflow.nodes.variable_aggregator import VariableAggregatorNode
from lumen_core.workflow.nodes.video_compose import VideoComposeNode  # M36

DEFAULT_VERSION = "1"

NODE_TYPE_CLASSES_MAPPING: dict[str, dict[str, type[BaseNode]]] = {
    "input":     {DEFAULT_VERSION: InputNode},
    "agent":     {DEFAULT_VERSION: AgentNode},
    "code":      {DEFAULT_VERSION: CodeNode},
    "llm":       {DEFAULT_VERSION: LLMNode},
    "condition": {DEFAULT_VERSION: ConditionNode},
    "output":    {DEFAULT_VERSION: OutputNode},
    "parallel":  {DEFAULT_VERSION: ParallelNode},
    "parameter_extractor": {DEFAULT_VERSION: ParameterExtractorNode},
    "question_classifier": {DEFAULT_VERSION: QuestionClassifierNode},
    "fan_out":   {DEFAULT_VERSION: FanOutNode},
    "fan_in":    {DEFAULT_VERSION: FanInNode},
    "http":      {DEFAULT_VERSION: HTTPNode},
    "start":     {DEFAULT_VERSION: StartNode},
    "end":       {DEFAULT_VERSION: EndNode},
    "tool":      {DEFAULT_VERSION: ToolNode},
    "knowledge_retrieval": {DEFAULT_VERSION: KnowledgeRetrievalNode},
    "template_transform": {DEFAULT_VERSION: TemplateTransformNode},
    "variable_assigner": {DEFAULT_VERSION: VariableAssignerNode},
    "variable_aggregator": {DEFAULT_VERSION: VariableAggregatorNode},
    # M35: 多模态节点
    "tts":             {DEFAULT_VERSION: TTSNode},
    "playbook_inject": {DEFAULT_VERSION: PlaybookInjectNode},
    # M36: 视频合成节点(同步)
    "video_compose":   {DEFAULT_VERSION: VideoComposeNode},
}


def resolve_node_class(node_type: str, version: str = DEFAULT_VERSION) -> type[BaseNode]:
    """根据 type + version 解析节点类。

    - 未知 type → 抛 ``ValueError("未知节点类型: ...")``。
    - 未知 version → 静默回退到 v1(``DEFAULT_VERSION``)。
    - v1 也不存在 → 抛 ``ValueError("未知节点版本: ...")``(配置错误)。
    """
    by_version = NODE_TYPE_CLASSES_MAPPING.get(node_type)
    if not by_version:
        raise ValueError(f"未知节点类型: {node_type}")
    cls = by_version.get(version) or by_version.get(DEFAULT_VERSION)
    if not cls:
        raise ValueError(f"未知节点版本: {node_type}@v{version}")
    return cls
