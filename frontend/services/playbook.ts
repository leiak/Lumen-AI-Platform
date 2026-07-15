// frontend/services/playbook.ts
// M35: playbook service.

import api from "./auth";
import type {
  PlaybookCreateRequest,
  PlaybookDetail,
  PlaybookListItem,
} from "@/types/playbook";

const BASE = "/playbooks";

export interface PlaybookListParams {
  scope?: string;
  page?: number;
  page_size?: number;
}

export interface PlaybookListResult {
  items: PlaybookListItem[];
  total: number;
  page: number;
  page_size: number;
}

export async function listPlaybooks(
  params: PlaybookListParams = {}
): Promise<PlaybookListResult> {
  const res = await api.get(BASE, { params });
  return {
    items: res.data.data as PlaybookListItem[],
    total: res.data.total,
    page: res.data.page,
    page_size: res.data.page_size,
  };
}

export async function getPlaybook(id: number): Promise<PlaybookDetail> {
  const res = await api.get(`${BASE}/${id}`);
  return res.data.data as PlaybookDetail;
}

export async function createPlaybook(
  data: PlaybookCreateRequest
): Promise<PlaybookDetail> {
  const res = await api.post(BASE, data);
  return res.data.data as PlaybookDetail;
}

export async function importPlaybookYaml(
  data: PlaybookCreateRequest
): Promise<PlaybookDetail> {
  const res = await api.post(`${BASE}/import-yaml`, data);
  return res.data.data as PlaybookDetail;
}

export async function updatePlaybook(
  id: number,
  data: Partial<PlaybookCreateRequest>
): Promise<PlaybookDetail> {
  const res = await api.put(`${BASE}/${id}`, data);
  return res.data.data as PlaybookDetail;
}

export async function deletePlaybook(id: number): Promise<void> {
  await api.delete(`${BASE}/${id}`);
}
