import type { ErrorStrategy, RetryConfig } from "../../_base/error/types";

export type HTTPMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
export type BodyType = "none" | "json" | "form" | "raw";
export type AuthType = "none" | "bearer" | "basic" | "api_key" | "custom_header";

export interface HTTPNodeConfig {
  method?: HTTPMethod;
  url?: string;
  headers?: Record<string, string>;
  query_params?: Record<string, string>;
  body_type?: BodyType;
  body?: string | Record<string, unknown>;
  auth_type?: AuthType;
  auth_config?: Record<string, string>;
  verify_ssl?: boolean;
  follow_redirects?: boolean;
  error_strategy?: ErrorStrategy | null;
  default_value?: Record<string, unknown> | null;
  retry_config?: RetryConfig | null;
  timeout?: number | null;
}
