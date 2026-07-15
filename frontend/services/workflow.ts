import api from "./auth";
import type { ApiResponse } from "@/types/api";
import type { OutputVar } from "@/components/workflow/_base/variable/types";

export interface WorkflowNode {
  id: string;
  type: string;
  config: Record<string, any>;
  position?: { x: number; y: number };
  data?: Record<string, any>;
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string;  // NEW: condition case_id, or "default", or "false"
  condition?: string;     // DEPRECATED: kept for legacy audit; replaced by sourceHandle
}

export interface WorkflowDefinition {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}

export interface Workflow {
  id: number;
  name: string;
  description?: string;
  definition: WorkflowDefinition;
  tenant_id: number;
  is_active: boolean;
  created_at: string;
}

export interface WorkflowRun {
  id: number;
  workflow_id: number;
  status: string;
  trigger_source?: "manual" | "scheduled" | null;
  input_data?: Record<string, any>;
  output_data?: Record<string, any>;
  error_message?: string;
  started_at?: string;
  finished_at?: string;
}

export interface WorkflowNodeRun {
  id: number;
  run_id: number;
  node_id: string;
  node_type: string;
  status: string;
  input_data?: Record<string, any> | null;
  output_data?: Record<string, any> | null;
  error_message?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  execution_order?: number | null;
}

export interface WorkflowRunResult {
  status: string;
  results: Record<
    string,
    {
      status: string;
      output?: any;
      error?: string;
      timestamp?: string;
    }
  >;
  final_output?: any;
  execution_order?: string[];
  error?: string;
}

export interface LLMNodeConfig {
  label?: string;
  prompt?: string;
  model_name?: string;
  temperature?: number;
  max_tokens?: number | null;
  system_prompt?: string;
  variables?: Record<string, any>;
}

export interface WorkflowDesignerData {
  name: string;
  definition: {
    nodes: Array<{
      id: string;
      type: string;
      config: Record<string, any>;
      position?: { x: number; y: number };
      data?: Record<string, any>;
    }>;
    edges: Array<{
      id: string;
      source: string;
      target: string;
      sourceHandle?: string;
      condition?: string;
    }>;
  };
}

export const workflowApi = {
  list: (page = 1, pageSize = 10) =>
    api.get<any>(`/workflows/?page=${page}&page_size=${pageSize}`),
  get: (id: number) => api.get<ApiResponse<Workflow>>(`/workflows/${id}`),
  create: (data: { name: string; description?: string; definition: WorkflowDefinition }) =>
    api.post<ApiResponse<Workflow>>("/workflows/", data),
  update: (id: number, data: Partial<Workflow>) =>
    api.put<ApiResponse<Workflow>>(`/workflows/${id}`, data),
  saveDesigner: (id: number, data: WorkflowDesignerData) =>
    api.put<ApiResponse<Workflow>>(`/workflows/${id}`, data),
  delete: (id: number) => api.delete(`/workflows/${id}`),
  run: (id: number, inputData: Record<string, any> = {}) =>
    // M30 ship follow-up (2026-06-18): the backend schema is
    // WorkflowRunRequest { input_data: dict } (schemas/workflow.py:77-79),
    // so the POST body MUST be wrapped. Previously this method passed
    // inputData directly as the body, which FastAPI's Pydantic parser
    // silently rejected with 400 "There was an error parsing the body"
    // because the unknown top-level keys (user_name / order_id / etc.)
    // didn't match the input_data field. The 2 callers (list page
    // handleRun + designer handleRun) both pass user-collected values
    // from InputValuesModal onConfirm — so the wrap belongs here, not
    // at the call sites.
    api.post<ApiResponse<WorkflowRun>>(`/workflows/${id}/run`, { input_data: inputData }),
  execute: (id: number, inputData: Record<string, any> = {}) =>
    api.post<ApiResponse<WorkflowRun>>(
      `/workflows/${id}/execute`,
      inputData
    ),
  listRuns: (id: number, page = 1, pageSize = 10) =>
    api.get<any>(`/workflows/${id}/runs?page=${page}&page_size=${pageSize}`),
  listRunNodes: (workflowId: number, runId: number) =>
    api.get<ApiResponse<WorkflowNodeRun[]>>(
      `/workflows/${workflowId}/runs/${runId}/nodes`
    ),
};

/** v2 node config — the structured shape that BaseNodeData expects. */
export interface NodeConfigV2 {
  title?: string;
  desc?: string;
  version?: string;
  error_strategy?: "fail_branch" | "default_value" | "ignore" | null;
  retry_config?: { max_retries: number; retry_interval: number };
  outputs?: OutputVar[];
  // Per-node-type fields (all optional, validated server-side):
  variables?: Array<{ name: string; type: string; required?: boolean }>;  // input
  agent_id?: number;            // agent
  model_config_id?: number | null;
  model_name?: string;
  prompt?: string;
  system_prompt?: string;
  temperature?: number;
  max_tokens?: number | null;
  cases?: Array<{              // condition
    case_id: string;
    logical_operator: "and" | "or";
    conditions: Array<{
      variable_selector: string[];
      comparison_operator: string;
      value?: unknown;
    }>;
  }>;
  field?: string;              // output
  parallel?: { branches: unknown[] };
  fan_out?: { items?: string[]; sub_workflow?: unknown };
  fan_in?: { source?: string; aggregation?: "collect" | "sum" | "average" };
  condition?: string;          // LEGACY: kept for runtime safe_eval
}
