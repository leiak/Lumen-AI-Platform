// frontend/services/subtitle.ts
// M35: subtitle service.

import api from "./auth";
import type {
  SubtitleCreateRequest,
  SubtitleDetail,
  SubtitleListItem,
} from "@/types/subtitle";

const BASE = "/subtitles";

export interface SubtitleListParams {
  page?: number;
  page_size?: number;
}

export interface SubtitleListResult {
  items: SubtitleListItem[];
  total: number;
  page: number;
  page_size: number;
}

export async function createSubtitle(
  data: SubtitleCreateRequest
): Promise<SubtitleDetail> {
  const res = await api.post(BASE, data);
  return res.data.data as SubtitleDetail;
}

export async function listSubtitles(
  params: SubtitleListParams = {}
): Promise<SubtitleListResult> {
  const res = await api.get(BASE, { params });
  return {
    items: res.data.data as SubtitleListItem[],
    total: res.data.total,
    page: res.data.page,
    page_size: res.data.page_size,
  };
}

export async function getSubtitle(id: number): Promise<SubtitleDetail> {
  const res = await api.get(`${BASE}/${id}`);
  return res.data.data as SubtitleDetail;
}

export function downloadSubtitleUrl(id: number): string {
  // Same Bearer-auth-as-blob pattern as the TTS audio endpoint.
  return `${window.location.origin}/api/v1/subtitles/${id}/download`;
}

export async function deleteSubtitle(id: number): Promise<void> {
  await api.delete(`${BASE}/${id}`);
}
