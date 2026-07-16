// frontend/services/stock.ts
// M36.2.1 — stock footage library
//
// Style B (independent functions + `import api from "./auth"`), mirroring
// `services/video.ts`. The list endpoint returns a PaginatedResponse; the
// service unwraps it into a flat StockListResult for callers.

import api from "./auth";
import type {
  StockAssetDetail,
  StockAssetListItem,
  StockListParams,
  StockListResult,
} from "@/types/stock";

export type { StockListParams, StockListResult };

const BASE = "/stock-assets";

export async function listStockAssets(
  params: StockListParams = {},
): Promise<StockListResult> {
  const res = await api.get(`${BASE}/`, { params });
  return {
    items: (res.data.data ?? []) as StockAssetListItem[],
    total: res.data.total ?? 0,
    page: res.data.page ?? params.page ?? 1,
    page_size: res.data.page_size ?? params.page_size ?? 24,
  };
}

export async function getStockAsset(id: number): Promise<StockAssetDetail> {
  const res = await api.get(`${BASE}/${id}`);
  return res.data.data as StockAssetDetail;
}

/**
 * Build the proxy URL the ComposeModal should put into
 * VideoComposeCreate.source_images. The backend streams the bytes with
 * Bearer auth — consumers must wrap this in
 * `fetch + Bearer + blob + createObjectURL` for `<img>` rendering
 * (MEMORY 2026-06-20). The video composition service itself reads bytes
 * from the URL server-side, so a plain string is fine for that path.
 */
export function buildStockImageUrl(id: number): string {
  return `${window.location.origin}/api/v1/stock-assets/${id}/image`;
}
