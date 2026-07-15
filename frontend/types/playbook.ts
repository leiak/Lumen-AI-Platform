// frontend/types/playbook.ts
// M35: playbook types.

export interface PlaybookListItem {
  id: number;
  name: string;
  description: string | null;
  scope: string[] | null;
  is_builtin: boolean;
  created_at: string;
  updated_at: string;
}

export interface PlaybookDetail extends PlaybookListItem {
  tenant_id: number;
  yaml_content: string;
  style_tokens: Record<string, unknown> | null;
  created_by: number | null;
}

export interface PlaybookCreateRequest {
  name: string;
  description?: string | null;
  yaml_content: string;
  scope?: string[];
}
