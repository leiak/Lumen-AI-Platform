import api from "./auth";
import type { ApiResponse } from "@/types/api";
import type { WorkflowDefinition } from "./workflow";

export interface WorkflowTemplate {
  id: number;
  name: string;
  description?: string;
  category: string;
  tags?: string[];
  author_id: number;
  author_name?: string;
  downloads: number;
  created_at: string;
}

export interface WorkflowTemplateDetail extends WorkflowTemplate {
  workflow_json: WorkflowDefinition;
}

export interface ImportResult {
  workflow_id: number;
  name: string;
}

export const workflowTemplateApi = {
  list: (params: { page?: number; page_size?: number; category?: string; tag?: string; search?: string } = {}) => {
    const qs = new URLSearchParams();
    if (params.page) qs.append("page", String(params.page));
    if (params.page_size) qs.append("page_size", String(params.page_size));
    if (params.category) qs.append("category", params.category);
    if (params.tag) qs.append("tag", params.tag);
    if (params.search) qs.append("search", params.search);
    const q = qs.toString();
    return api.get<any>(`/workflow-templates/${q ? `?${q}` : ""}`);
  },
  detail: (id: number) =>
    api.get<ApiResponse<WorkflowTemplateDetail>>(`/workflow-templates/${id}`),
  publish: (data: {
    name: string;
    description?: string;
    category?: string;
    tags?: string[];
    workflow_id?: number;
    workflow_json?: WorkflowDefinition;
  }) => api.post<ApiResponse<WorkflowTemplate>>("/workflow-templates/", data),
  import: (id: number) =>
    api.post<ApiResponse<ImportResult>>(`/workflow-templates/${id}/import`, {}),
  categories: () => api.get<ApiResponse<{ value: string; count: number }[]>>("/workflow-templates/categories"),
};
