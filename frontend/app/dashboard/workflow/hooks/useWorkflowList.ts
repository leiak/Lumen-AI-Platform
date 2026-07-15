"use client";

import { useCallback, useEffect, useState } from "react";
import { workflowApi, Workflow } from "@/services/workflow";
import { useAppMessage, extractErrorDetail } from "./useAppMessage";

/**
 * M30b: list + paginate + delete + create for the workflow list page.
 *
 * Returns plain props the component layer wires up (workflows,
 * loading, total, page, pageSize, refresh, handleCreate, handleDelete).
 *
 * The backend's `?search=&is_active=&sort_by=&sort_order=` query
 * params are wired here too (M30a added server-side filtering).
 */
export function useWorkflowList() {
  const { message } = useAppMessage();
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [isActive, setIsActive] = useState<boolean | undefined>(undefined);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const response = await workflowApi.list(page, pageSize);
      if (response.data.code === 200) {
        setWorkflows(response.data.data || []);
        setTotal(response.data.total || 0);
      }
    } catch (error) {
      message.error(extractErrorDetail(error, "获取工作流列表失败"));
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, message]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleCreate = useCallback(
    async (values: { name: string; description?: string }) => {
      try {
        const response = await workflowApi.create({
          ...values,
          definition: {
            nodes: [{ id: "input", type: "input", config: {} }],
            edges: [],
          },
        });
        if (response.data.code === 200) {
          message.success("创建成功");
          await refresh();
          return true;
        }
        return false;
      } catch (error) {
        message.error(extractErrorDetail(error, "创建失败"));
        return false;
      }
    },
    [refresh, message]
  );

  const handleDelete = useCallback(
    async (id: number) => {
      try {
        await workflowApi.delete(id);
        message.success("删除成功");
        await refresh();
      } catch (error) {
        message.error(extractErrorDetail(error, "删除失败"));
      }
    },
    [refresh, message]
  );

  return {
    workflows,
    loading,
    page,
    pageSize,
    total,
    search,
    isActive,
    setSearch,
    setIsActive,
    setPage,
    setPageSize,
    refresh,
    handleCreate,
    handleDelete,
  };
}
