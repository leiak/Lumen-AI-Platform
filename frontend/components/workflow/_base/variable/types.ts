// frontend/components/workflow/_base/variable/types.ts

export enum VarType {
  string = "string",
  number = "number",
  boolean = "boolean",
  object = "object",
  arrayString = "array[string]",
  arrayNumber = "array[number]",
  arrayObject = "array[object]",
  file = "file",
  secret = "secret",
  none = "none",
}

export interface OutputVar {
  name: string;
  type: VarType;
  description?: string;
  children?: OutputVar[];
}

export type ValueSelector = string[]; // ["node_3", "text"]

export interface Var {
  variable: string;
  type: VarType;
  children?: Var[];
  nodeId: string;
  nodeTitle: string;
  isLoopVariable?: boolean;
  description?: string;
}

export type NodeOutPutVar = Var;

export enum BlockEnum {
  Input = "input",
  Agent = "agent",
  LLM = "llm",
  Condition = "condition",
  Output = "output",
  Parallel = "parallel",
  FanOut = "fan_out",
  FanIn = "fan_in",
  Start = "start",
  End = "end",
  // P2 nodes
  Code = "code",
  HTTP = "http",
  Tool = "tool",
  KnowledgeRetrieval = "knowledge_retrieval",
  TemplateTransform = "template_transform",
  ParameterExtractor = "parameter_extractor",
  QuestionClassifier = "question_classifier",
  VariableAssigner = "variable_assigner",
  VariableAggregator = "variable_aggregator",
  // M30c 2.0 (2026-09-07): M35/M36 nodes
  TTS = "tts",
  PlaybookInject = "playbook_inject",
  VideoCompose = "video_compose",
}
