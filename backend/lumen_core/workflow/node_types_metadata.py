"""M30d: per-type metadata registry.

Each entry pairs the node's runtime class (from
``node_mapping.NODE_TYPE_CLASSES_MAPPING``) with a static
``NodeMetadata`` block describing the type to the designer
(``/api/v1/workflow/node-types``). The runtime class is the source
of truth for inputs / outputs; the static block is the source of
truth for display strings (label / description / icon / color) +
the default_config used when the user adds a fresh node.

The static block lives here (not on the BaseNode class) because
some metadata is best expressed once and shared (e.g. the "📚
知识库检索" icon should be the same for every version of the
node), and because adding the entries here doesn't require
modifying each node's runtime class — keeping the runtime /
display split clean.
"""

from lumen_core.workflow.nodes.base import NodeMetadata


# (type, version) → NodeMetadata. version="1" is the default.
_NODE_TYPE_METADATA: dict[tuple[str, str], NodeMetadata] = {
    ("input", "1"): NodeMetadata(
        type="input", label="输入", description="工作流的输入参数",
        icon="📥", color="blue", category="input",
        default_config={"variables": []},
        inputs=[],
        outputs=[{"name": "value", "type": "any"}],
    ),
    ("agent", "1"): NodeMetadata(
        type="agent", label="Agent", description="调用 AI Agent 执行任务",
        icon="🤖", color="cyan", category="process",
        default_config={"prompt": ""},
        inputs=[{"name": "input", "type": "any", "required": True}],
        outputs=[{"name": "response", "type": "string"}],
    ),
    ("llm", "1"): NodeMetadata(
        type="llm", label="LLM 调用", description="调用 LLM 模型生成文本",
        icon="🧠", color="purple", category="process",
        default_config={"prompt": "", "temperature": 0.7, "max_tokens": None},
        inputs=[{"name": "prompt", "type": "string", "required": True}],
        outputs=[{"name": "response", "type": "string"},
                 {"name": "model", "type": "string"}],
    ),
    ("code", "1"): NodeMetadata(
        type="code", label="代码执行", description="在沙盒里执行 Python 代码",
        icon="💻", color="magenta", category="process",
        default_config={"code": "RESULT = 1", "output_var": "RESULT"},
        inputs=[{"name": "input", "type": "any"}],
        outputs=[{"name": "result", "type": "any"}],
    ),
    ("condition", "1"): NodeMetadata(
        type="condition", label="条件分支",
        description="根据条件决定下游分支", icon="🔀", color="orange",
        category="control",
        default_config={"cases": []},
        inputs=[{"name": "input", "type": "any"}],
        outputs=[],
    ),
    ("output", "1"): NodeMetadata(
        type="output", label="输出", description="工作流的最终输出",
        icon="📤", color="green", category="output",
        default_config={"field": "value"},
        inputs=[{"name": "value", "type": "any"}],
        outputs=[],
    ),
    ("parallel", "1"): NodeMetadata(
        type="parallel", label="并行执行", description="并行运行多个分支",
        icon="⫮", color="geekblue", category="control",
        default_config={"branches": []},
        inputs=[{"name": "input", "type": "any"}],
        outputs=[{"name": "results", "type": "array"}],
    ),
    ("fan_out", "1"): NodeMetadata(
        type="fan_out", label="扇出", description="对集合的每个元素跑下游",
        icon="↗", color="orange", category="control",
        default_config={"items": []},
        inputs=[{"name": "items", "type": "array"}],
        outputs=[],
    ),
    ("fan_in", "1"): NodeMetadata(
        type="fan_in", label="扇入", description="把多条分支合并成一个集合",
        icon="↘", color="green", category="control",
        default_config={"aggregation": "collect"},
        inputs=[{"name": "items", "type": "array"}],
        outputs=[{"name": "result", "type": "array"}],
    ),
    ("http", "1"): NodeMetadata(
        type="http", label="HTTP 请求", description="调用外部 HTTP API",
        icon="🌐", color="geekblue", category="integration",
        default_config={"method": "GET", "url": "",
                        "headers": {}, "query_params": {},
                        "body_type": "none", "body": "",
                        "auth_type": "none", "auth_config": {},
                        "verify_ssl": True, "follow_redirects": True},
        inputs=[{"name": "input", "type": "any"}],
        outputs=[{"name": "response", "type": "object"},
                 {"name": "status_code", "type": "number"}],
    ),
    ("start", "1"): NodeMetadata(
        type="start", label="起点", description="工作流入口(占位)",
        icon="▶", color="default", category="control",
        default_config={}, inputs=[], outputs=[],
    ),
    ("end", "1"): NodeMetadata(
        type="end", label="终点", description="工作流出口(占位)",
        icon="■", color="default", category="control",
        default_config={}, inputs=[{"name": "value", "type": "any"}],
        outputs=[],
    ),
    ("tool", "1"): NodeMetadata(
        type="tool", label="工具调用", description="调用已安装的脚本/HTTP 工具",
        icon="🔧", color="volcano", category="process",
        default_config={"tool_id": 0, "arguments": {}},
        inputs=[{"name": "input", "type": "any"}],
        outputs=[{"name": "result", "type": "any"}],
    ),
    ("knowledge_retrieval", "1"): NodeMetadata(
        type="knowledge_retrieval", label="知识库检索",
        description="从知识库检索相关 chunk", icon="📚", color="gold",
        category="process",
        default_config={"kb_id": 0, "query": "", "top_k": 5,
                        "score_threshold": 0,
                        "rerank_enabled": True, "hybrid_search": True},
        inputs=[{"name": "query", "type": "string", "required": True}],
        outputs=[{"name": "chunks", "type": "array"}],
    ),
    ("template_transform", "1"): NodeMetadata(
        type="template_transform", label="模板转换",
        description="Jinja2 模板渲染字符串", icon="🔄", color="lime",
        category="process",
        default_config={"template": ""},
        inputs=[{"name": "input", "type": "any"}],
        outputs=[{"name": "result", "type": "string"}],
    ),
    ("parameter_extractor", "1"): NodeMetadata(
        type="parameter_extractor", label="参数提取",
        description="用 LLM 从文本提取结构化参数", icon="🔍", color="red",
        category="process",
        default_config={"input_text": "", "parameters": [],
                        "instruction": "请从以下文本中提取参数,以 JSON 格式输出:",
                        "temperature": 0},
        inputs=[{"name": "input_text", "type": "string"}],
        outputs=[{"name": "parameters", "type": "object"}],
    ),
    ("question_classifier", "1"): NodeMetadata(
        type="question_classifier", label="问题分类",
        description="用 LLM 把问题路由到不同分支", icon="🏷️", color="pink",
        category="process",
        default_config={"input_text": "", "categories": [],
                        "instruction": "请把以下问题分类到最合适的类别,只输出类别 ID:",
                        "temperature": 0},
        inputs=[{"name": "input_text", "type": "string"}],
        outputs=[{"name": "category", "type": "string"}],
    ),
    ("variable_assigner", "1"): NodeMetadata(
        type="variable_assigner", label="变量赋值",
        description="把表达式结果赋给一个变量", icon="📝", color="purple",
        category="variable",
        default_config={"operations": []},
        inputs=[{"name": "input", "type": "any"}],
        outputs=[{"name": "value", "type": "any"}],
    ),
    ("variable_aggregator", "1"): NodeMetadata(
        type="variable_aggregator", label="变量聚合",
        description="把多个变量聚合成一个集合", icon="🗂️", color="cyan",
        category="variable",
        default_config={"aggregation": "collect"},
        inputs=[{"name": "items", "type": "array"}],
        outputs=[{"name": "result", "type": "array"}],
    ),
    # M35: 多模态创作节点
    ("tts", "1"): NodeMetadata(
        type="tts", label="语音合成",
        description="调用 TTS 服务合成语音(Edge/Piper/OpenAI)。"
                    "返回 job_id,音频在后台异步生成。",
        icon="🔊", color="volcano", category="integration",
        default_config={
            "model_config_id": 0,
            "text": "",
            "voice": "default",
            "speed": 1.0,
            "format": "mp3",
            "playbook_id": None,
        },
        inputs=[{"name": "text", "type": "string", "required": True}],
        outputs=[
            {"name": "job_id", "type": "number"},
            {"name": "status", "type": "string"},
            {"name": "text", "type": "string"},
            {"name": "audio_url", "type": "string"},
        ],
    ),
    ("playbook_inject", "1"): NodeMetadata(
        type="playbook_inject", label="风格注入",
        description="把 playbook 的关键词/调色/语速等风格 token 拼接到输入文本。",
        icon="🎨", color="magenta", category="process",
        default_config={
            "text": "",
            "playbook_id": None,
            "target": "image_prompt",
        },
        inputs=[{"name": "text", "type": "string"}],
        outputs=[
            {"name": "enriched_text", "type": "string"},
            {"name": "playbook_id", "type": "number"},
        ],
    ),
    # M36: 视频合成(图+音+字 → mp4,同步阻塞)
    ("video_compose", "1"): NodeMetadata(
        type="video_compose", label="视频合成",
        description="把图像+音频+字幕合成 mp4(同步等待)。"
                    "下游可拿 video_url。",
        icon="🎬", color="magenta", category="integration",
        default_config={
            "source_images": [],
            "audio_path": None,
            "subtitle_path": None,
            "resolution": "1280x720",
            "fps": 24,
            "audio_fade_in": 0.0,
            "audio_fade_out": 0.0,
            "subtitle_font": None,
            "per_image_seconds": None,
        },
        inputs=[{"name": "source_images", "type": "array", "required": True}],
        outputs=[
            {"name": "video_id", "type": "number"},
            {"name": "video_url", "type": "string"},
            {"name": "status", "type": "string"},
            {"name": "duration_ms", "type": "number"},
            {"name": "file_size", "type": "number"},
        ],
    ),
}


def get_node_type_metadata(node_type: str, version: str = "1") -> NodeMetadata | None:
    return _NODE_TYPE_METADATA.get((node_type, version))


def all_node_types_metadata() -> list[NodeMetadata]:
    """Return metadata for every (type, version) we know about. Deduplicated
    by type — the latest version wins for the canonical list view.
    """
    seen: set[str] = set()
    out: list[NodeMetadata] = []
    # Sort by type for stable output.
    for key in sorted(_NODE_TYPE_METADATA.keys()):
        meta = _NODE_TYPE_METADATA[key]
        if meta.type in seen:
            continue
        seen.add(meta.type)
        out.append(meta)
    return out
