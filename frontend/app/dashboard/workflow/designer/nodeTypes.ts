"use client";

/**
 * M30c: central registry of all 17 workflow node types used by the
 * designer canvas. Before M30c, only 8 of the 17 were registered
 * (the P1 set: input, agent, llm, condition, output, parallel,
 * fan_out, fan_in). The 9 P2 nodes (Code/HTTP/Tool/Knowledge
 * Retrieval/Template Transform/Parameter Extractor/Question
 * Classifier/Variable Assigner/Variable Aggregator) had their
 * Node.tsx files in `components/workflow/nodes/<type>/` but were
 * never wired into the canvas, so users couldn't add them.
 *
 * Each entry pairs the node's `BlockEnum` key with metadata used
 * by the NodeLibraryPanel (label / description / icon / color /
 * category) plus the React component used to render it on the
 * canvas.
 *
 * The P1 nodes (input / agent / llm / condition / output / parallel
 * / fan_out / fan_in) are still defined inline in
 * `designer/page.tsx` for backwards-compat with the rest of the
 * designer. We expose a `p2NodeComponents` map for the canvas to
 * merge with the P1 inline map.
 */

import { BlockEnum } from "@/components/workflow/_base/variable/types";
import type { ComponentType } from "react";

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

export const P2_NODE_REGISTRY: Record<string, NodeMeta> = {
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
 * P2-only React Flow node-types map. Merge with the P1 inline
 * components in designer/page.tsx:
 *
 *   const nodeTypes = { ...p2NodeComponents, input: InputNode, ... };
 */
export const p2NodeComponents: Record<string, ComponentType<any>> = (() => {
  const out: Record<string, ComponentType<any>> = {};
  for (const meta of P2_NODE_REGISTRY_LIST) {
    out[meta.type as string] = meta.component;
  }
  return out;
})();
