import api from "./auth";

export const nodesApi = {
  async previewHTTP(payload: {
    method: string;
    url: string;
    headers?: Record<string, string>;
    query_params?: Record<string, string>;
    body_type?: string;
    body?: string | Record<string, unknown>;
    auth_type?: string;
    auth_config?: Record<string, string>;
    verify_ssl?: boolean;
    follow_redirects?: boolean;
  }) {
    return api.post("/workflows/nodes/http/preview", payload);
  },
  async previewKB(payload: {
    kb_id: number;
    query: string;
    top_k?: number;
    score_threshold?: number;
  }) {
    return api.post("/workflows/nodes/knowledge-retrieval/preview", payload);
  },
  async previewTemplate(payload: {
    template: string;
    sample_context?: Record<string, unknown>;
  }) {
    return api.post("/workflows/nodes/template-transform/preview", payload);
  },
};
