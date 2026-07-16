// frontend/types/stock.ts
// M36.2.1 — stock footage library
//
// 1:1 mirror of backend lumen_schemas/stock_asset.py. The proxy endpoint
// returns a FileResponse that requires Bearer auth, so the frontend must
// consume the bytes via `fetch + blob + createObjectURL` (see MEMORY
// 2026-06-20). For composition we only need the URL, not the bytes.

export type StockSource = "builtin" | "pexels" | "uploaded";

/** Row returned by GET /api/v1/stock-assets/ (list endpoint). */
export interface StockAssetListItem {
  id: number;
  name: string;
  category: string;
  tags: string[] | null;
  mime_type: string;
  width: number | null;
  height: number | null;
  file_size: number;
  source: StockSource;
  created_at: string;
}

/** Full row returned by GET /api/v1/stock-assets/{id}. */
export interface StockAssetDetail extends StockAssetListItem {
  file_path: string;
  description: string | null;
  pexels_id: number | null;
  tenant_id: number | null;
}

/** Query params for GET /api/v1/stock-assets/. */
export interface StockListParams {
  page?: number;
  page_size?: number;
  category?: string;
  search?: string;
}

/** Flat object returned by listStockAssets() — service unwraps PaginatedResponse. */
export interface StockListResult {
  items: StockAssetListItem[];
  total: number;
  page: number;
  page_size: number;
}
