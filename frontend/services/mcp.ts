import api from "./auth";
import type { ApiResponse, PaginatedResponse } from "@/types/api";

export interface MCPServer {
  name: string;
  url: string;
  status: string;
}

export interface MCPTool {
  id: number;
  name: string;
  description?: string | null;
  input_schema: Record<string, any>;
  output_schema?: Record<string, any> | null;
  server_name?: string | null;
  is_enabled?: number;
}

export interface MarketplaceTool {
  name: string;
  description: string;
  server: string;
  category: string;
}

export const mcpApi = {
  listServers: (page = 1, pageSize = 10) =>
    api.get<PaginatedResponse<MCPServer>>(`/mcp/servers?page=${page}&page_size=${pageSize}`),
  registerServer: (name: string, url: string) =>
    api.post<ApiResponse<MCPServer>>("/mcp/servers", { name, url }),
  unregisterServer: (name: string) =>
    api.delete(`/mcp/servers/${name}`),
  listTools: (page = 1, pageSize = 10) =>
    api.get<PaginatedResponse<MCPTool>>(`/mcp/tools?page=${page}&page_size=${pageSize}`),
  registerTool: (data: { name: string; description: string; input_schema: Record<string, any>; server_name: string }) =>
    api.post<ApiResponse<MCPTool>>("/mcp/tools", data),
  executeTool: (toolName: string, inputData: Record<string, any>) =>
    api.post<ApiResponse<{ result: any }>>("/mcp/tools/execute", {
      tool_name: toolName,
      input_data: inputData,
    }),
  listMarketplaceTools: () =>
    api.get<ApiResponse<MarketplaceTool[]>>("/mcp/marketplace/tools"),
  installMarketplaceTool: (toolName: string) =>
    api.post<ApiResponse<{ message: string }>>(`/mcp/marketplace/tools/${toolName}/install`),
};
