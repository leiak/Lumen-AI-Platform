import api from "./auth";
import type { KnowledgeBase, ApiResponse, PaginatedResponse } from "@/types/api";

export interface ParserType {
  type: string;
  label: string;
  description: string;
}

export interface SearchOptions {
  k?: number;
  alpha?: number;
  rerank?: boolean;
  rerank_top_n?: number;
  field_weights?: string;
}

export interface KnowledgeBaseUpdate {
  name?: string;
  description?: string;
  // embedding_model is a legacy string field (e.g. "nomic-embed-text").
  // New code should rely on embedding_model_config_id on the response
  // shape, not send this on update. The PUT endpoint ignores it.
  embedding_model?: string;
  // Note: embedding_model_config_id is intentionally NOT in the
  // update payload — the embedding model is locked once a KB is
  // created. Sending it has no effect (the API strips it).
  search_weights?: Record<string, number>;
  default_parser?: string;
  chunk_size?: number;
  chunk_overlap?: number;
}

export interface KnowledgeBaseCreate {
  name: string;
  description?: string;
  // The ModelConfig.id of the embedding model to use. Required on
  // create; the API rejects requests without it with a 422.
  embedding_model_config_id: number;
  // Legacy string kept for backward compat with old API responses
  // (read-only on the response shape). The frontend form no longer
  // collects this.
  embedding_model?: string;
  search_weights?: Record<string, number>;
  default_parser?: string;
  chunk_size?: number;
  chunk_overlap?: number;
}

export interface DocumentResponse {
  id: number;
  filename: string;
  file_type: string;
  file_size: number;
  status: string;
  chunk_count?: number;
  error_message?: string;
  created_at: string;
  knowledge_base_id?: number;
  doc_metadata?: {
    doc_type?: string;
  };
}

export interface DocumentChunk {
  id: number;
  chunk_index: number;
  content: string;
  vector_id?: string;
}

export interface RechunkParams {
  chunking_strategy?: string;
  chunk_size?: number;
  chunk_overlap?: number;
  doc_type?: string;
}

// ----------------------------------------------------------------- M31: FAQ Q&A
//
// The Q&A tab on the KB detail page is driven by these
// types. The API is 1:1 with the backend FAQService
// (see backend/app/services/faq_service.py).

export interface FAQEntry {
  id: number;
  knowledge_base_id: number;
  question: string;
  answer: string;
  category?: string;
  tags?: string[];
  vector_id?: string;
  document_id: number;
  chunk_id: number;
  created_at: string;
  updated_at: string;
}

export interface FAQEntryCreate {
  question: string;
  answer: string;
  category?: string;
  tags?: string[];
}

export interface FAQEntryUpdate {
  question?: string;
  answer?: string;
  category?: string;
  tags?: string[];
}

export interface FAQBulkImportRequest {
  format: "json" | "csv";
  content: string;
}

export interface FAQBulkImportResult {
  inserted: number;
  failed: { row_index: string; reason: string }[];
}

export const knowledgeApi = {
  list: (page = 1, pageSize = 10, workspaceId?: number) => {
    let url = `/knowledge/?page=${page}&page_size=${pageSize}`;
    // M38.2: workspace filter. ``workspaceId === 0`` means "tenant root
    // (no workspace)" — backend uses ``0`` as the sentinel.
    if (workspaceId !== undefined && workspaceId !== -1) {
      url += `&workspace_id=${workspaceId}`;
    }
    return api.get<PaginatedResponse<KnowledgeBase>>(url);
  },
  get: (id: number) => api.get<ApiResponse<KnowledgeBase>>(`/knowledge/${id}`),
  getDocuments: (kbId: number, folderId?: number) => {
    // M38.2: ``folder_id`` filter — 0 = KB root, -1/None = all, >0 = that folder.
    let url = `/knowledge/${kbId}/documents`;
    if (folderId !== undefined) {
      url += `?folder_id=${folderId}`;
    }
    return api.get<ApiResponse<DocumentResponse[]>>(url);
  },
  create: (data: KnowledgeBaseCreate, workspaceId?: number) => {
    // M38.2: optional workspace binding at create.
    let url = "/knowledge/";
    if (workspaceId !== undefined && workspaceId !== null) {
      url += `?workspace_id=${workspaceId}`;
    }
    return api.post<ApiResponse<KnowledgeBase>>(url, data);
  },
  update: (id: number, data: KnowledgeBaseUpdate) =>
    api.put<ApiResponse<KnowledgeBase>>(`/knowledge/${id}`, data),
  delete: (id: number) => api.delete(`/knowledge/${id}`),
  deleteDocument: (docId: number) =>
    api.delete<
      ApiResponse<{
        document_id: number;
        deleted_chunks: number;
        vector_cleanup_failed: boolean;
      }>
    >(`/knowledge/documents/${docId}`),
  upload: (kbId: number, file: File, docType?: string, folderId?: number) => {
    const formData = new FormData();
    formData.append("file", file);
    if (docType) {
      formData.append("doc_type", docType);
    }
    // M38.2: optional folder_id for upload.
    if (folderId !== undefined && folderId !== null) {
      formData.append("folder_id", String(folderId));
    }
    return api.post(`/knowledge/${kbId}/documents`, formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },
  search: (kbId: number, query: string, options?: SearchOptions) => {
    let url = `/knowledge/${kbId}/search?query=${encodeURIComponent(query)}`;
    if (options) {
      if (options.k !== undefined) url += `&k=${options.k}`;
      if (options.alpha !== undefined) url += `&alpha=${options.alpha}`;
      if (options.rerank !== undefined) url += `&rerank=${options.rerank}`;
      if (options.rerank_top_n !== undefined) url += `&rerank_top_n=${options.rerank_top_n}`;
      if (options.field_weights) url += `&field_weights=${encodeURIComponent(options.field_weights)}`;
    }
    return api.get<ApiResponse<any[]>>(url);
  },
  getParserTypes: () =>
    api.get<ApiResponse<{ parser_types: ParserType[]; chunking_strategies: any[] }>>("/knowledge/parser-types"),
  getDocumentStatus: (docId: number) =>
    api.get<ApiResponse<{ document_id: number; status: string; chunk_count?: number; error_message?: string }>>(`/knowledge/documents/${docId}/status`),
  retry: (docId: number) =>
    api.post<ApiResponse<DocumentResponse>>(`/knowledge/documents/${docId}/retry`),
  listChunks: (docId: number, page = 1, pageSize = 50) =>
    api.get<ApiResponse<DocumentChunk[]>>(
      `/knowledge/documents/${docId}/chunks?page=${page}&page_size=${pageSize}`
    ),
  rechunk: (docId: number, params: RechunkParams) =>
    api.post<ApiResponse<DocumentResponse>>(
      `/knowledge/documents/${docId}/rechunk`,
      params
    ),
  // M31: FAQ Q&A endpoints. The list endpoint returns a
  // PaginatedResponse (with the standard envelope), so the
  // generic is `PaginatedResponse<FAQEntry>`. The single
  // create / update / delete endpoints use the standard
  // SingleResponse envelope.
  listFaqs: (
    kbId: number,
    params?: {
      page?: number;
      page_size?: number;
      category?: string;
      search?: string;
    }
  ) => {
    const usp = new URLSearchParams();
    if (params?.page) usp.set("page", String(params.page));
    if (params?.page_size) usp.set("page_size", String(params.page_size));
    if (params?.category) usp.set("category", params.category);
    if (params?.search) usp.set("search", params.search);
    const qs = usp.toString();
    return api.get<PaginatedResponse<FAQEntry>>(
      `/knowledge/${kbId}/faq-entries${qs ? `?${qs}` : ""}`
    );
  },
  createFaq: (kbId: number, data: FAQEntryCreate) =>
    api.post<ApiResponse<FAQEntry>>(
      `/knowledge/${kbId}/faq-entries`,
      data
    ),
  updateFaq: (kbId: number, id: number, data: FAQEntryUpdate) =>
    api.put<ApiResponse<FAQEntry>>(
      `/knowledge/${kbId}/faq-entries/${id}`,
      data
    ),
  deleteFaq: (kbId: number, id: number) =>
    api.delete<ApiResponse<{ entry_id: number; deleted: boolean }>>(
      `/knowledge/${kbId}/faq-entries/${id}`
    ),
  bulkImportFaqs: (kbId: number, data: FAQBulkImportRequest) =>
    api.post<ApiResponse<FAQBulkImportResult>>(
      `/knowledge/${kbId}/faq-entries/bulk`,
      data
    ),
};
