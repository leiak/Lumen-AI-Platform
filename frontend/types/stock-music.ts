// frontend/types/stock-music.ts
// M36.2.2 — stock background-music library
//
// 1:1 mirror of backend lumen_schemas/stock_music.py. The proxy endpoint
// returns a FileResponse that requires Bearer auth, so the frontend must
// consume the audio bytes via `fetch + blob + createObjectURL` (see
// MEMORY 2026-06-20). For composition the service only needs the id
// (resolved by the backend's _resolve_asset_to_path), but the audio
// preview UI needs the full proxy URL.

export type StockMusicSource = "builtin" | "uploaded";

/** Row returned by GET /api/v1/stock-musics/ (list endpoint). */
export interface StockMusicListItem {
  id: number;
  name: string;
  category: string;
  description: string | null;
  mime_type: string;
  file_size: number;
  duration_seconds: number;
  source: StockMusicSource;
  created_at: string;
}

/** Full row returned by GET /api/v1/stock-musics/{id}. */
export interface StockMusicDetail extends StockMusicListItem {
  file_path: string;
  tenant_id: number | null;
}

/** Query params for GET /api/v1/stock-musics/. */
export interface StockMusicListParams {
  page?: number;
  page_size?: number;
  category?: string;
  search?: string;
}

/** Flat object returned by listStockMusics() — service unwraps PaginatedResponse. */
export interface StockMusicListResult {
  items: StockMusicListItem[];
  total: number;
  page: number;
  page_size: number;
}
