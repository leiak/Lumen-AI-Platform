import type { ComponentType } from "react";
import type { WorkflowNode, WorkflowEdge } from "@/services/workflow";
import { BlockEnum } from "../_base/variable/types";
import { InputPanel } from "./input/Panel";
import { AgentPanel } from "./agent/Panel";
import { ConditionPanel } from "./condition/Panel";
import { OutputPanel } from "./output/Panel";
import { ParallelPanel } from "./parallel/Panel";
import { FanOutPanel } from "./fan_out/Panel";
import { FanInPanel } from "./fan_in/Panel";
import { LLMPanel } from "./llm/Panel";
import { CodePanel } from "./code/Panel";
import { HTTPPanel } from "./http/Panel";
import { KBRetrievalPanel } from "./knowledge_retrieval/Panel";
import { ToolPanel } from "./tool/Panel";
import { TemplateTransformPanel } from "./template_transform/Panel";
import { ParameterExtractorPanel } from "./parameter_extractor/Panel";
import { QuestionClassifierPanel } from "./question_classifier/Panel";
import { VariableAssignerPanel } from "./variable_assigner/Panel";
import { VariableAggregatorPanel } from "./variable_aggregator/Panel";

export interface PanelProps {
  node: WorkflowNode;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  onChange: (newNode: WorkflowNode) => void;
}

/**
 * Read node data with backward compatibility: prefer v2 `config`, fall back to legacy `data`.
 * Once the migration script has run, `config` is the source of truth.
 */
export function nodeData(node: WorkflowNode): Record<string, any> {
  return (node.config as Record<string, any>) ?? (node.data as Record<string, any>) ?? {};
}

export const PanelComponentMap: Record<string, ComponentType<PanelProps>> = {
  [BlockEnum.Input]: InputPanel,
  [BlockEnum.Agent]: AgentPanel,
  [BlockEnum.LLM]: LLMPanel,
  [BlockEnum.Condition]: ConditionPanel,
  [BlockEnum.Output]: OutputPanel,
  [BlockEnum.Parallel]: ParallelPanel,
  [BlockEnum.FanOut]: FanOutPanel,
  [BlockEnum.FanIn]: FanInPanel,
  [BlockEnum.Code]: CodePanel,
  [BlockEnum.HTTP]: HTTPPanel,
  [BlockEnum.KnowledgeRetrieval]: KBRetrievalPanel,
  [BlockEnum.Tool]: ToolPanel,
  [BlockEnum.TemplateTransform]: TemplateTransformPanel,
  [BlockEnum.ParameterExtractor]: ParameterExtractorPanel,
  [BlockEnum.QuestionClassifier]: QuestionClassifierPanel,
  [BlockEnum.VariableAssigner]: VariableAssignerPanel,
  [BlockEnum.VariableAggregator]: VariableAggregatorPanel,
};

export function getPanelForType(type: string): ComponentType<PanelProps> | null {
  return PanelComponentMap[type] ?? null;
}
