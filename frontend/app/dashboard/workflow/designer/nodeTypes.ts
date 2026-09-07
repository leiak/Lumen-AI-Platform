"use client";

/**
 * M30c 2.0 (2026-09-07): central registry of all 20 workflow node types.
 *
 * 20 nodes = 8 P1 (input/agent/llm/condition/output/parallel/fan_out/fan_in)
 *          + 9 P2 (code/http/tool/knowledge_retrieval/template_transform/
 *                  parameter_extractor/question_classifier/variable_assigner/
 *                  variable_aggregator)
 *          + 2 M35 (tts/playbook_inject)
 *          + 1 M36 (video_compose)
 *
 * Note: 2.0 spec A6 + this header previously said "22" — actual count
 * is 20 (8+9+2+1).
 *
 * 2 start/end placeholder nodes are NOT exposed in this registry —
 * they're handled by the executor's start-node search, not the canvas.
 *
 * Each entry pairs the node's `BlockEnum` key with metadata used
 * by the NodeLibraryPanel (label / description / icon / color /
 * category) plus the React component used to render it on the
 * canvas.
 *
 * P1 + M35/M36 (11 entries) used to live as inline components in
 * `designer/page.tsx`; M30c 2.0 extracted them into
 * `components/workflow/nodes/<type>/Node.tsx` for consistency with
 * the P2 set (which shipped that way in M30 / 2026-06-05).
 */

import { BlockEnum } from "@/components/workflow/_base/variable/types";
import type { ComponentType } from "react";

// P1 Node components — extracted from designer/page.tsx in M30c 2.0.
import { InputNode } from "@/components/workflow/nodes/input/Node";
import { AgentNode } from "@/components/workflow/nodes/agent/Node";
import { LLMNode } from "@/components/workflow/nodes/llm/Node";
import { ConditionNode } from "@/components/workflow/nodes/condition/Node";
import { OutputNode } from "@/components/workflow/nodes/output/Node";
import { ParallelNode } from "@/components/workflow/nodes/parallel/Node";
import { FanOutNode } from "@/components/workflow/nodes/fan_out/Node";
import { FanInNode } from "@/components/workflow/nodes/fan_in/Node";
// P2 Node components — each has a Node.tsx file shipped with P2.
import { CodeNode } from "@/components/workflow/nodes/code/Node";
import { HTTPNode } from "@/components/workflow/nodes/http/Node";
import { ToolNode } from "@/components/workflow/nodes/tool/Node";
import { KBRetrievalNode } from "@/components/workflow/nodes/knowledge_retrieval/Node";
import { TemplateTransformNode } from "@/components/workflow/nodes/template_transform/Node";
import { ParameterExtractorNode } from "@/components/workflow/nodes/parameter_extractor/Node";
import { QuestionClassifierNode } from "@/components/workflow/nodes/question_classifier/Node";
import { VariableAssignerNode } from "@/components/workflow/nodes/variable_assigner/Node";
import { VariableAggregatorNode } from "@/components/workflow/nodes/variable_aggregator/Node";
// M35/M36 Node components — M30c 2.0.
import { TTSNode } from "@/components/workflow/nodes/tts/Node";
import { PlaybookInjectNode } from "@/components/workflow/nodes/playbook_inject/Node";
import { VideoComposeNode } from "@/components/workflow/nodes/video_compose/Node";

export type NodeCategory =
  | "input"
  | "process"
  | "control"
  | "output"
  | "integration"
  | "variable";

export interface NodeMeta {
  type: BlockEnum;
  label: string;
  description: string;
  icon: string;
  color: string;
  category: NodeCategory;
  component: ComponentType<any>;
}

// P1: 8 nodes (input / agent / llm / condition / output / parallel / fan_out / fan_in)
const P1_NODE_REGISTRY: Record<string, NodeMeta> = {
  [BlockEnum.Input]: {
    type: BlockEnum.Input,
    label: "输入",
    description: "工作流的输入参数",
    icon: "📥",
    color: "blue",
    category: "input",
    component: InputNode,
  },
  [BlockEnum.Agent]: {
    type: BlockEnum.Agent,
    label: "Agent",
    description: "调用 AI Agent 执行任务",
    icon: "🤖",
    color: "cyan",
    category: "process",
    component: AgentNode,
  },
  [BlockEnum.LLM]: {
    type: BlockEnum.LLM,
    label: "LLM 调用",
    description: "调用 LLM 模型生成文本",
    icon: "🧠",
    color: "purple",
    category: "process",
    component: LLMNode,
  },
  [BlockEnum.Condition]: {
    type: BlockEnum.Condition,
    label: "条件分支",
    description: "根据表达式分流到不同下游",
    icon: "🔀",
    color: "orange",
    category: "control",
    component: ConditionNode,
  },
  [BlockEnum.Output]: {
    type: BlockEnum.Output,
    label: "输出",
    description: "工作流的输出参数",
    icon: "📤",
    color: "green",
    category: "output",
    component: OutputNode,
  },
  [BlockEnum.Parallel]: {
    type: BlockEnum.Parallel,
    label: "并行",
    description: "并行执行下游多个分支",
    icon: "⚡",
    color: "magenta",
    category: "control",
    component: ParallelNode,
  },
  [BlockEnum.FanOut]: {
    type: BlockEnum.FanOut,
    label: "扇出",
    description: "把单个输入分发到多个下游分支",
    icon: "🔱",
    color: "geekblue",
    category: "control",
    component: FanOutNode,
  },
  [BlockEnum.FanIn]: {
    type: BlockEnum.FanIn,
    label: "扇入",
    description: "汇聚多个上游分支的输出",
    icon: "🔻",
    color: "gold",
    category: "control",
    component: FanInNode,
  },
};

const P2_NODE_REGISTRY: Record<string, NodeMeta> = {
  [BlockEnum.Code]: {
    type: BlockEnum.Code,
    label: "代码执行",
    description: "在沙盒里执行 Python 代码",
    icon: "💻",
    color: "magenta",
    category: "process",
    component: CodeNode,
  },
  [BlockEnum.HTTP]: {
    type: BlockEnum.HTTP,
    label: "HTTP 请求",
    description: "调用外部 HTTP API",
    icon: "🌐",
    color: "geekblue",
    category: "integration",
    component: HTTPNode,
  },
  [BlockEnum.Tool]: {
    type: BlockEnum.Tool,
    label: "工具调用",
    description: "调用已安装的脚本/HTTP 工具",
    icon: "🔧",
    color: "volcano",
    category: "process",
    component: ToolNode,
  },
  [BlockEnum.KnowledgeRetrieval]: {
    type: BlockEnum.KnowledgeRetrieval,
    label: "知识库检索",
    description: "从知识库检索相关 chunk",
    icon: "📚",
    color: "gold",
    category: "process",
    component: KBRetrievalNode,
  },
  [BlockEnum.TemplateTransform]: {
    type: BlockEnum.TemplateTransform,
    label: "模板转换",
    description: "Jinja2 模板渲染字符串",
    icon: "🔄",
    color: "lime",
    category: "process",
    component: TemplateTransformNode,
  },
  [BlockEnum.ParameterExtractor]: {
    type: BlockEnum.ParameterExtractor,
    label: "参数提取",
    description: "用 LLM 从文本提取结构化参数",
    icon: "🔍",
    color: "red",
    category: "process",
    component: ParameterExtractorNode,
  },
  [BlockEnum.QuestionClassifier]: {
    type: BlockEnum.QuestionClassifier,
    label: "问题分类",
    description: "用 LLM 把问题路由到不同分支",
    icon: "🏷️",
    color: "pink",
    category: "process",
    component: QuestionClassifierNode,
  },
  [BlockEnum.VariableAssigner]: {
    type: BlockEnum.VariableAssigner,
    label: "变量赋值",
    description: "把表达式结果赋给一个变量",
    icon: "📝",
    color: "purple",
    category: "variable",
    component: VariableAssignerNode,
  },
  [BlockEnum.VariableAggregator]: {
    type: BlockEnum.VariableAggregator,
    label: "变量聚合",
    description: "把多个变量聚合成一个集合",
    icon: "🗂️",
    color: "cyan",
    category: "variable",
    component: VariableAggregatorNode,
  },
};

// M35/M36 (3 nodes) — tts / playbook_inject / video_compose.
const M35_M36_NODE_REGISTRY: Record<string, NodeMeta> = {
  [BlockEnum.TTS]: {
    type: BlockEnum.TTS,
    label: "语音合成",
    description: "调用 TTS 服务合成语音(Edge/Piper/OpenAI)",
    icon: "🔊",
    color: "volcano",
    category: "integration",
    component: TTSNode,
  },
  [BlockEnum.PlaybookInject]: {
    type: BlockEnum.PlaybookInject,
    label: "风格注入",
    description: "把 playbook 的关键词/调色/语速等 token 拼接到输入文本",
    icon: "🎨",
    color: "magenta",
    category: "process",
    component: PlaybookInjectNode,
  },
  [BlockEnum.VideoCompose]: {
    type: BlockEnum.VideoCompose,
    label: "视频合成",
    description: "把图像+音频+字幕合成 mp4 (同步等待)",
    icon: "🎬",
    color: "magenta",
    category: "integration",
    component: VideoComposeNode,
  },
};

// M30c 2.0: 20 nodes total. P1 (8) + P2 (9) + M35 (2) + M36 (1).
export const ALL_NODE_REGISTRY: Record<string, NodeMeta> = {
  ...P1_NODE_REGISTRY,
  ...P2_NODE_REGISTRY,
  ...M35_M36_NODE_REGISTRY,
};

export const ALL_NODE_REGISTRY_LIST: NodeMeta[] = Object.values(ALL_NODE_REGISTRY);

// Backwards-compat: P2-only list still exported (used by some
// NodeLibraryPanel views that group P2 separately).
export const P2_NODE_REGISTRY_LIST: NodeMeta[] = Object.values(P2_NODE_REGISTRY);

/**
 * Categories in display order for the NodeLibraryPanel.
 */
export const CATEGORY_LABELS: Record<NodeCategory, string> = {
  input: "输入/输出",
  process: "处理",
  control: "控制流",
  variable: "变量",
  integration: "集成",
  output: "输入/输出",
};

/**
 * M30c 2.0 (2026-09-07): all 20 React Flow node-types map.
 * Replaces the old `p2NodeComponents` (P2-only) and the inline P1
 * components in designer/page.tsx.
 */
export const allNodeComponents: Record<string, ComponentType<any>> = (() => {
  const out: Record<string, ComponentType<any>> = {};
  for (const meta of ALL_NODE_REGISTRY_LIST) {
    out[meta.type as string] = meta.component;
  }
  return out;
})();

// Backwards-compat: keep the old P2-only export so any 3rd-party
// caller that imported p2NodeComponents keeps working.
export const p2NodeComponents: Record<string, ComponentType<any>> = (() => {
  const out: Record<string, ComponentType<any>> = {};
  for (const meta of P2_NODE_REGISTRY_LIST) {
    out[meta.type as string] = meta.component;
  }
  return out;
})();
