export interface ApiResponse<T = any> {
  code: number;
  message: string;
  data?: T;
}

export interface PaginatedResponse<T = any> {
  code: number;
  message: string;
  data: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
}

export interface User {
  id: number;
  username: string;
  email: string;
  full_name?: string;
  tenant_id: number;
  is_active: boolean;
  is_superuser: boolean;
  created_at: string;
}

export interface KnowledgeBase {
  id: number;
  name: string;
  description?: string;
  // Legacy string identifier. Backend still returns it for old KBs;
  // new code should read embedding_model_config_id instead.
  embedding_model: string;
  // FK to the ModelConfig row that backs this KB's embeddings.
  // Optional during the migration window; after migration completes
  // every KB has this set and it's locked.
  embedding_model_config_id?: number | null;
  search_weights?: Record<string, number>;
  tenant_id: number;
  status: string;
  created_at: string;
  default_parser?: string;
  chunk_size?: number;
  chunk_overlap?: number;
  document_count?: number;
}

export interface Agent {
  id: number;
  name: string;
  description?: string;
  prompt_template: string;
  model_name: string;
  temperature: number;
  tenant_id: number;
  is_active: boolean;
  created_at: string;
  // Memory policy (Task 8)
  memory_policy?: string;
  memory_window_size?: number;
  memory_max_tokens?: number;
  memory_compression?: boolean;
  // Tool choice (Task 8)
  tool_choice?: string;
  tool_choice_required?: boolean;
  allowed_tools?: string[] | null;
  // Knowledge base binding (M21)
  knowledge_bases?: KBRef[];
  kb_retrieval_config?: KbRetrievalConfig;
}

// === M21: Agent 知识库绑定 ===

export type KBStatus = "active" | "inactive" | "deleted";

export interface KBRef {
  id: number;
  name: string;
  status: KBStatus;
}

export interface KbRetrievalConfig {
  top_k: number;       // 1-10, default 3
  rrf_k: number;       // 10-100, default 30
}

export interface AgentCreatePayload {
  name: string;
  description?: string;
  prompt_template: string;
  model_name?: string;
  temperature?: number;
  // Memory policy (Task 8)
  memory_policy?: string;
  memory_window_size?: number;
  memory_max_tokens?: number;
  memory_compression?: boolean;
  // Tool choice (Task 8)
  tool_choice?: string;
  tool_choice_required?: boolean;
  allowed_tools?: string[];
  // Knowledge base binding (M21)
  knowledge_base_ids?: number[];
  kb_retrieval_config?: KbRetrievalConfig;
}

// PATCH-style partial update. All Agent fields are Optional;
// adds the M21 knowledge_base_ids + kb_retrieval_config pair.
export interface AgentUpdatePayload {
  name?: string;
  description?: string;
  prompt_template?: string;
  model_name?: string;
  temperature?: number;
  is_active?: boolean;
  // Memory policy (Task 8)
  memory_policy?: string;
  memory_window_size?: number;
  memory_max_tokens?: number;
  memory_compression?: boolean;
  // Tool choice (Task 8)
  tool_choice?: string;
  tool_choice_required?: boolean;
  allowed_tools?: string[] | null;
  // Knowledge base binding (M21)
  knowledge_base_ids?: number[];
  kb_retrieval_config?: KbRetrievalConfig;
}

/** External widget application (admin CRUD). */
export interface ExternalApp {
  id: number;
  tenant_id: number;
  name: string;
  app_key: string;
  allowed_origins: string[];
  allowed_agent_ids: number[];
  allowed_team_ids: number[];
  scopes: string;
  rate_limit_per_min: number;
  is_active: boolean;
  description?: string | null;
  created_by?: number | null;
  last_used_at?: string | null;
  created_at: string;
  updated_at: string;
  allowed_agent_names: string[];
  allowed_team_names: string[];
}

export interface ExternalAppCreated extends ExternalApp {
  app_secret_plain: string;  // returned ONLY at create / regenerate
}

export interface ExternalAppUsage {
  last_used_at: string | null;
  active_visitors_7d: number;
  total_conversations: number;
  token_issues_7d: number;
  last_7d_daily: number[];
}

export interface ExternalAppCreateRequest {
  name: string;
  description?: string;
  allowed_origins: string[];
  allowed_agent_ids: number[];
  allowed_team_ids: number[];
  scopes?: string;
  rate_limit_per_min?: number;
}

export interface ExternalAppUpdateRequest {
  name?: string;
  description?: string;
  allowed_origins?: string[];
  allowed_agent_ids?: number[];
  allowed_team_ids?: number[];
  scopes?: string;
  rate_limit_per_min?: number;
  is_active?: boolean;
}
