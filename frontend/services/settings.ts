import api from "./auth";
import type { ApiResponse } from "@/types/api";

export interface SystemSettings {
  system_name: string;
  system_description?: string;
  default_model?: number | null;
  embedding_model?: number | null;
  chat_history_days: number;
}

export interface SecuritySettings {
  enforce_password_complexity: boolean;
  min_password_length: number;
  login_fail_lock_count: number;
  token_expire_minutes: number;
}

export const settingsApi = {
  get: () => api.get<ApiResponse<SystemSettings>>("/settings/"),
  update: (data: Partial<SystemSettings>) => api.put<ApiResponse<SystemSettings>>("/settings/", data),
  getSecuritySettings: () => api.get<ApiResponse<SecuritySettings>>("/settings/security"),
  updateSecuritySettings: (data: Partial<SecuritySettings>) => api.put<ApiResponse<SecuritySettings>>("/settings/security", data),
};