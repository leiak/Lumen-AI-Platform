import api from "./auth";
import type { ApiResponse } from "@/types/api";
import type { PptSchema, PptTaskResponse } from "@/types/ppt";
import type { PptConfig } from "@/types/ppt";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:11335/api/v1";

export const pptApi = {
  /**
   * 生成 PPT。
   * - mode=frontend: 同步返回 PptSchema，前端自行渲染
   * - mode=backend: 异步返回 task_id，前端轮询
   */
  generate: (config: PptConfig, conversationId: number) =>
    api.post<ApiResponse<{ task_id?: string; schema?: PptSchema }>>("/ppt/generate", {
      conversation_id: conversationId,
      title: config.title || undefined,
      content_range: config.contentRange,
      include_charts: config.includeCharts,
      style: config.style,
      mode: config.mode,
    }),

  /** 轮询任务状态 */
  getTask: (taskId: string) =>
    api.get<ApiResponse<PptTaskResponse>>(`/ppt/tasks/${taskId}`),

  /** 获取下载 URL（baseUrl 已含 /api/v1 前缀，不要重复加） */
  getDownloadUrl: (taskId: string, baseUrl: string) =>
    `${baseUrl}/ppt/tasks/${taskId}/file`,
};
