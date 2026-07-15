// frontend/types/video.ts
// M36.1 — video composition feature
//
// 1:1 mirror of backend lumen_schemas/video.py. The backend's status literal
// is `"composing"` (NOT `"running"`) — see backend pydantic literal at
// `lumen_schemas/video.py:20`.

export type VideoStatus = "pending" | "composing" | "completed" | "failed" | "cancelled";

/** Row returned by GET /api/v1/videos/ (list endpoint). */
export interface VideoListItem {
  id: number;
  resolution: string;
  fps: number;
  file_size: number;
  duration_ms: number | null;
  status: VideoStatus;
  image_count: number;
  created_at: string;
}

/** Full row returned by GET /api/v1/videos/{id}. */
export interface VideoDetail {
  id: number;
  tenant_id: number;
  user_id: number;
  conversation_id: number | null;
  model_config_id: number | null;
  playbook_id: number | null;
  source_audio_id: number | null;
  source_subtitle_id: number | null;
  source_images: string[] | null;
  resolution: string;
  fps: number;
  file_path: string;
  file_size: number;
  mime_type: string;
  duration_ms: number | null;
  status: VideoStatus;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
}

/** Body for POST /api/v1/videos/. */
export interface VideoComposeCreate {
  source_images: string[];
  audio_path?: string | null;
  subtitle_path?: string | null;
  source_audio_id?: number | null;
  source_subtitle_id?: number | null;
  playbook_id?: number | null;
  conversation_id?: number | null;
  resolution?: string;
  fps?: number;
  audio_fade_in?: number;
  audio_fade_out?: number;
  subtitle_font?: string | null;
  per_image_seconds?: number | null;
}

/** Query params for GET /api/v1/videos/. */
export interface VideoListParams {
  page?: number;
  page_size?: number;
  status?: VideoStatus | "";
}

/** Flat object returned by listVideos() — service unwraps PaginatedResponse. */
export interface VideoListResult {
  items: VideoListItem[];
  total: number;
  page: number;
  page_size: number;
}