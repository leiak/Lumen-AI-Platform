// frontend/services/video.ts
// M36.1 — video composition feature
//
// Style B (independent functions + `import api from "./auth"`), mirroring
// `services/tts.ts` rather than the image-generation.ts object literal.
// CRUD is small enough that named functions read cleaner than an object.
//
// Auth: the Bearer token is injected by the axios interceptor in
// `services/auth.ts`. The `/videos/{id}/download` endpoint streams binary
// bytes, so consumers MUST use fetch + blob + createObjectURL (see
// `buildVideoUrl` docstring and MEMORY 2026-06-20).

import api from "./auth";
import type {
  VideoComposeCreate,
  VideoDetail,
  VideoListItem,
  VideoListParams,
  VideoListResult,
} from "@/types/video";

// Re-export so callers can `import { type VideoListParams } from "@/services/video"`.
export type { VideoListParams, VideoListResult };

const BASE = "/videos";

export async function createVideoCompose(data: VideoComposeCreate): Promise<VideoDetail> {
  const res = await api.post(`${BASE}/`, data);
  return res.data.data as VideoDetail;
}

export async function listVideos(params: VideoListParams = {}): Promise<VideoListResult> {
  const res = await api.get(`${BASE}/`, { params });
  return {
    items: (res.data.data ?? []) as VideoListItem[],
    total: res.data.total ?? 0,
    page: res.data.page ?? params.page ?? 1,
    page_size: res.data.page_size ?? params.page_size ?? 12,
  };
}

export async function getVideo(id: number): Promise<VideoDetail> {
  const res = await api.get(`${BASE}/${id}`);
  return res.data.data as VideoDetail;
}

export async function cancelVideo(id: number): Promise<{ id: number; status: string }> {
  const res = await api.post(`${BASE}/${id}/cancel`);
  // Backend returns SingleResponse[dict] — pull the inner payload.
  return (res.data.data ?? res.data) as { id: number; status: string };
}

export async function deleteVideo(id: number): Promise<void> {
  await api.delete(`${BASE}/${id}`);
}

/**
 * Build a URL that hits the video streaming endpoint. The frontend MUST wrap
 * this in `fetch + Bearer + blob + createObjectURL` — `<video src=...>` does
 * not pass Authorization headers natively, so a direct src would 401.
 * See MEMORY 2026-06-20 for the established image/audio pattern.
 */
export function buildVideoUrl(id: number): string {
  // Build absolute URL from window.location.origin so the fetch works in dev
  // (localhost:11334) and prod without re-config.
  return `${window.location.origin}/api/v1/videos/${id}/download`;
}