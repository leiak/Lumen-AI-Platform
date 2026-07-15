import api from "./auth";
import type { ApiResponse } from "@/types/api";

export interface ModelConfig {
  id: number;
  name: string;
  model_type: string;
  model_name: string;
  base_url?: string;
  api_key?: string;
  api_version?: string;
  temperature: number;
  max_tokens: number;
  timeout: number;
  is_default: boolean;
  is_active: boolean;
  is_chat: boolean;
  is_embedding: boolean;
  // M22 (image generation) — true when this config backs an image model.
  is_image_generation?: boolean;
  tenant_id?: number;
  description?: string;
  created_at: string;
  updated_at: string;
}

export interface OllamaModelInfo {
  name: string;
  size?: number;
  modified_at?: string;
  family?: string | null;
  capabilities: string[];
  is_embedding_capable: boolean;
  is_chat_capable: boolean;
  exists_in_db: boolean;
  existing_config_id: number | null;
}

export interface OllamaImportResult {
  base_url: string;
  reachable: boolean;
  models: OllamaModelInfo[];
  error_message?: string;
}

export interface BulkCreateRowInput {
  name: string;
  model_type: string;
  model_name: string;
  base_url?: string | null;
  is_chat: boolean;
  is_embedding: boolean;
  description?: string | null;
}

export interface BulkCreateResultEntry {
  requested_model_name: string;
  status: "created" | "skipped" | "error";
  config?: ModelConfig;
  existing_config_id?: number;
  reason?: string;
  error?: string;
}

export interface ListModelsOptions {
  model_type?: string;
  is_chat?: boolean;
  is_embedding?: boolean;
  is_image_generation?: boolean;
  is_tts?: boolean;  // M35
  is_subtitle_generation?: boolean;  // M35
  is_active?: boolean;
}

export const modelsApi = {
  list: (page = 1, pageSize = 10, typeOrOpts?: string | ListModelsOptions, maybeOpts?: ListModelsOptions) => {
    // Backwards-compatible overload: the third arg used to be a plain
    // model_type string. New callers should pass an options object.
    let type: string | undefined;
    let opts: ListModelsOptions | undefined;
    if (typeof typeOrOpts === "string") {
      type = typeOrOpts;
      opts = maybeOpts;
    } else {
      opts = typeOrOpts;
    }
    let url = `/models/?page=${page}&page_size=${pageSize}`;
    const t = type ?? opts?.model_type;
    if (t) url += `&model_type=${encodeURIComponent(t)}`;
    if (opts?.is_chat !== undefined) url += `&is_chat=${opts.is_chat}`;
    if (opts?.is_embedding !== undefined) url += `&is_embedding=${opts.is_embedding}`;
    if (opts?.is_image_generation !== undefined) { url += `&is_image_generation=${opts.is_image_generation}`; }  // M22
    if (opts?.is_tts !== undefined) { url += `&is_tts=${opts.is_tts}`; }  // M35
    if (opts?.is_subtitle_generation !== undefined) { url += `&is_subtitle_generation=${opts.is_subtitle_generation}`; }  // M35
    if (opts?.is_active !== undefined) { url += `&is_active=${opts.is_active}`; }
    return api.get<any>(url);
  },
  get: (id: number) => api.get<ApiResponse<ModelConfig>>(`/models/${id}`),
  create: (data: Partial<ModelConfig>) =>
    api.post<ApiResponse<ModelConfig>>("/models/", data),
  update: (id: number, data: Partial<ModelConfig>) =>
    api.put<ApiResponse<ModelConfig>>(`/models/${id}`, data),
  delete: (id: number) => api.delete(`/models/${id}`),
  listTypes: () => api.get<ApiResponse<any[]>>("/models/providers/list"),
  importFromOllama: (base_url?: string) =>
    api.post<ApiResponse<OllamaImportResult>>(
      "/models/import-from-ollama",
      base_url ? { base_url } : {}
    ),
  bulkCreate: (rows: BulkCreateRowInput[]) =>
    api.post<ApiResponse<{ results: BulkCreateResultEntry[] }>>(
      "/models/bulk-create",
      rows
    ),
};
