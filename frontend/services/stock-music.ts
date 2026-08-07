// frontend/services/stock-music.ts
// M36.2.2 — stock background-music library
//
// Style B (independent functions + `import api from "./auth"`), mirroring
// `services/stock.ts`. The list endpoint returns a PaginatedResponse; the
// service unwraps it into a flat StockMusicListResult for callers.
//
// The audio proxy at /api/v1/stock-musics/{id}/file is Bearer-protected,
// so consumers (the picker modal's <audio> preview) must use
// fetch + Bearer + blob + createObjectURL (MEMORY 2026-06-20). For the
// compose flow we only need the id — backend resolves it via
// `_resolve_asset_to_path(kind="music")`.

import api from "./auth";
import type {
  StockMusicDetail,
  StockMusicListItem,
  StockMusicListParams,
  StockMusicListResult,
} from "@/types/stock-music";

export type { StockMusicListParams, StockMusicListResult };

const BASE = "/stock-musics";

export async function listStockMusics(
  params: StockMusicListParams = {},
): Promise<StockMusicListResult> {
  const res = await api.get(`${BASE}/`, { params });
  return {
    items: (res.data.data ?? []) as StockMusicListItem[],
    total: res.data.total ?? 0,
    page: res.data.page ?? params.page ?? 1,
    page_size: res.data.page_size ?? params.page_size ?? 24,
  };
}

export async function getStockMusic(id: number): Promise<StockMusicDetail> {
  const res = await api.get(`${BASE}/${id}`);
  return res.data.data as StockMusicDetail;
}

/**
 * Build the proxy URL the ComposeModal puts into
 * VideoComposeCreate.background_music_path. The backend reads bytes
 * directly from disk via stock_music_service.get_file_abs_path, so the
 * server-side composer doesn't go through this URL — but the picker
 * modal uses it to render an inline `<audio>` preview, which is why
 * we expose the helper.
 */
export function buildStockMusicUrl(id: number): string {
  return `${window.location.origin}/api/v1/stock-musics/${id}/file`;
}
