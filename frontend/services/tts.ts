// frontend/services/tts.ts
// M35: TTS service. Mirrors image-generation.ts pattern.

import api from "./auth";
import type {
  TTSJobCreateRequest,
  TTSJobCreateResponse,
  TTSJobDetail,
  TTSJobListItem,
  TTSVoice,
} from "@/types/tts";

const BASE = "/tts";

export interface TTSListParams {
  page?: number;
  page_size?: number;
  status?: string;
  model_config_id?: number;
}

export interface TTSListResult {
  items: TTSJobListItem[];
  total: number;
  page: number;
  page_size: number;
}

export async function createTTSJob(
  data: TTSJobCreateRequest
): Promise<TTSJobCreateResponse> {
  const res = await api.post(`${BASE}/jobs`, data);
  return res.data.data as TTSJobCreateResponse;
}

export async function listTTSJobs(
  params: TTSListParams = {}
): Promise<TTSListResult> {
  const res = await api.get(`${BASE}/jobs`, { params });
  return {
    items: res.data.data as TTSJobListItem[],
    total: res.data.total,
    page: res.data.page,
    page_size: res.data.page_size,
  };
}

export async function getTTSJob(id: number): Promise<TTSJobDetail> {
  const res = await api.get(`${BASE}/jobs/${id}`);
  return res.data.data as TTSJobDetail;
}

export async function cancelTTSJob(id: number): Promise<{ id: number; status: string }> {
  const res = await api.post(`${BASE}/jobs/${id}/cancel`);
  return res.data.data;
}

export async function deleteTTSJob(id: number): Promise<void> {
  await api.delete(`${BASE}/jobs/${id}`);
}

export async function listTTSVoices(
  modelConfigId: number,
  language?: string
): Promise<TTSVoice[]> {
  const res = await api.get(`${BASE}/voices`, {
    params: { model_config_id: modelConfigId, language },
  });
  return (res.data.data as TTSVoice[]) || [];
}

/** Build a URL that hits the audio streaming endpoint with the
 * caller's Bearer token. The frontend wraps this in a fetch+blob
 * and creates an object URL — see MEMORY 2026-06-20 for the
 * <img>/<audio> Bearer auth bug pattern. */
export function buildAudioUrl(id: number): string {
  // Build absolute URL from window.location.origin so the fetch
  // works in dev (localhost:11334) and prod without re-config.
  return `${window.location.origin}/api/v1/tts/jobs/${id}/audio`;
}
