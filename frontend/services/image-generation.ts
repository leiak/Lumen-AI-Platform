// frontend/services/image-generation.ts
// M22 — image generation feature (T14)
//
// Auth interceptor (services/auth.ts) sets `Authorization: Bearer <token>` on
// every axios request, so the JSON endpoints (list/get/create/regenerate/
// delete) work normally. The /image and /thumbnail endpoints stream binary
// bytes and are not safe to use as a plain `<img src>` — the browser does not
// send the Authorization header on image requests. Consumers should fetch +
// blob + URL.createObjectURL instead (see frontend/app/dashboard/document/page.tsx
// for the established pattern).
import api from "./auth";
import type {
  ImageGenerationListItem,
  ImageGenerationDetail,
  ImageGenerationCreateRequest,
  ImageGenerationCreateResponse,
} from "@/types/image-generation";

export interface ListParams {
  page?: number;
  page_size?: number;
  model_config_id?: number;
  status?: string;
  prompt?: string;
}

export interface ListResult {
  items: ImageGenerationListItem[];
  total: number;
  page: number;
  page_size: number;
}

export const imageGenerationApi = {
  /**
   * GET /api/v1/image-generation/
   * Unwraps the PaginatedResponse envelope (res.data.data is the items array;
   * total/page/page_size sit on res.data). Returns a flat object so callers
   * can destructure { items, total, page, page_size }.
   */
  async list(params: ListParams = {}): Promise<ListResult> {
    const res = await api.get("/image-generation/", { params });
    if (res.data?.code === 200) {
      const body = res.data;
      return {
        items: (body.data ?? []) as ImageGenerationListItem[],
        total: body.total ?? 0,
        page: body.page ?? params.page ?? 1,
        page_size: body.page_size ?? params.page_size ?? 12,
      };
    }
    throw new Error(res.data?.message || "list failed");
  },

  /** GET /api/v1/image-generation/{id} */
  async get(id: number): Promise<ImageGenerationDetail> {
    const res = await api.get(`/image-generation/${id}`);
    if (res.data?.code === 200) return res.data.data as ImageGenerationDetail;
    throw new Error(res.data?.message || "get failed");
  },

  /** POST /api/v1/image-generation/ */
  async create(
    data: ImageGenerationCreateRequest
  ): Promise<ImageGenerationCreateResponse> {
    const res = await api.post("/image-generation/", data);
    if (res.data?.code === 200) return res.data.data as ImageGenerationCreateResponse;
    throw new Error(res.data?.message || "create failed");
  },

  /** POST /api/v1/image-generation/{id}/regenerate */
  async regenerate(id: number): Promise<ImageGenerationCreateResponse> {
    const res = await api.post(`/image-generation/${id}/regenerate`);
    if (res.data?.code === 200) return res.data.data as ImageGenerationCreateResponse;
    throw new Error(res.data?.message || "regenerate failed");
  },

  /** DELETE /api/v1/image-generation/{id} — backend returns 204 No Content. */
  async delete(id: number): Promise<true> {
    const res = await api.delete(`/image-generation/${id}`);
    if (res.status === 204) return true;
    throw new Error(res.data?.message || "delete failed");
  },

  /**
   * Path to the full image bytes endpoint. The browser will not send the
   * Authorization header on a plain `<img src=...>`, so consumers must
   * fetch + blob + URL.createObjectURL (see module header).
   */
  imagePath(id: number): string {
    return `/image-generation/${id}/image`;
  },

  /** Path to the 256x256 JPEG thumbnail endpoint (see imagePath for auth). */
  thumbnailPath(id: number): string {
    return `/image-generation/${id}/thumbnail`;
  },
};
