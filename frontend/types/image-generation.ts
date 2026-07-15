// frontend/types/image-generation.ts
// M22 — image generation feature (T14)
// Spec: docs/superpowers/specs/2026-06-11-image-generation-design.md §4.3
// Backend envelopes (PaginatedResponse / SingleResponse) live in
// app/schemas/common.py; the frontend reads them via `res.data.data` then
// `res.data.total/page/page_size` (see CLAUDE.md §3).

export type ImageGenStatus = "pending" | "generating" | "completed" | "failed";

/** Subset returned by GET /image-generation/ (list endpoint). */
export interface ImageGenerationListItem {
  id: number;
  prompt_preview: string;
  model_config_id: number;
  model_name: string;
  model_type: string;
  size: string;
  status: ImageGenStatus;
  has_thumbnail: boolean;
  file_size: number | null;
  width: number | null;
  height: number | null;
  duration_ms: number | null;
  created_at: string;
}

/** Full row returned by GET /image-generation/{id}. */
export interface ImageGenerationDetail extends ImageGenerationListItem {
  prompt: string;
  negative_prompt: string | null;
  quality: string | null;
  style: string | null;
  n: number;
  params: Record<string, unknown> | null;
  error_message: string | null;
  updated_at: string;
}

/** Body for POST /image-generation/. */
export interface ImageGenerationCreateRequest {
  model_config_id: number;
  prompt: string;
  negative_prompt?: string;
  size?: "1024x1024" | "1024x1792" | "1792x1024" | "512x512";
  n?: number;
  quality?: "standard" | "hd";
  style?: "vivid" | "natural";
  extra_params?: Record<string, unknown>;
  // M35: optional playbook id to inject style keywords into the prompt
  playbook_id?: number | null;
}

/** Body returned by POST /image-generation/ and /{id}/regenerate. */
export interface ImageGenerationCreateResponse {
  id: number;
  status: ImageGenStatus;
  batch_id: string | null;
  model_config_id: number;
  created_at: string;
}
