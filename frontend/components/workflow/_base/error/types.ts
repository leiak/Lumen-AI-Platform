// P2 共享:error_strategy / retry_config / timeout 的 TypeScript 镜像

export type ErrorStrategy = "fail_branch" | "default_value" | "ignore";

export interface RetryConfig {
  max_retries: number;
  retry_interval: number;
  retry_on?: string[] | null;
}

export const DEFAULT_RETRY: RetryConfig = {
  max_retries: 0,
  retry_interval: 1.0,
};

export const DEFAULT_TIMEOUT_SECONDS = 30;
