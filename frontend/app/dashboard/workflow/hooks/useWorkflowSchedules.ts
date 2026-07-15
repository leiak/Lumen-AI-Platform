"use client";

import { useCallback, useState } from "react";
import { useAppMessage, extractErrorDetail } from "./useAppMessage";

export interface Schedule {
  id: number;
  name: string;
  cron_expression: string;
  is_active: boolean;
  next_run_at?: string | null;
  workflow_id: number;
  tenant_id: number;
  input_data?: Record<string, any> | null;
  last_run_at?: string | null;
  created_at: string;
}

const API_BASE = "/api/v1";

function authHeaders(): Record<string, string> {
  const token =
    typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * M30b: CRUD wrapper for the workflow schedule modal.
 *
 * Axios-izes the original raw-fetch handlers (which had inconsistent
 * error handling). All schedule state for a single workflow lives in
 * this hook.
 */
export function useWorkflowSchedules() {
  const { message } = useAppMessage();
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<number | null>(null);

  const fetchSchedules = useCallback(
    async (workflowId: number) => {
      try {
        const response = await fetch(
          `${API_BASE}/workflows/${workflowId}/schedules`,
          { headers: authHeaders() }
        );
        const data = await response.json();
        if (data.code === 200) {
          setSchedules(data.data || []);
        }
      } catch (error) {
        message.error(extractErrorDetail(error, "加载定时任务失败"));
      }
    },
    [message]
  );

  const openFor = useCallback(
    async (workflowId: number) => {
      setSelectedWorkflowId(workflowId);
      await fetchSchedules(workflowId);
    },
    [fetchSchedules]
  );

  const close = useCallback(() => {
    setSelectedWorkflowId(null);
    setSchedules([]);
  }, []);

  const create = useCallback(
    async (values: { name: string; cron_expression: string }) => {
      if (!selectedWorkflowId) return false;
      setSubmitting(true);
      try {
        const response = await fetch(
          `${API_BASE}/workflows/${selectedWorkflowId}/schedules`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json", ...authHeaders() },
            body: JSON.stringify(values),
          }
        );
        const data = await response.json();
        if (data.code === 200) {
          message.success("定时任务创建成功");
          await fetchSchedules(selectedWorkflowId);
          return true;
        }
        message.error(data.message || "创建失败");
        return false;
      } catch (error) {
        message.error(extractErrorDetail(error, "创建失败"));
        return false;
      } finally {
        setSubmitting(false);
      }
    },
    [selectedWorkflowId, fetchSchedules, message]
  );

  const remove = useCallback(
    async (scheduleId: number) => {
      if (!selectedWorkflowId) return;
      setDeletingId(scheduleId);
      try {
        const response = await fetch(
          `${API_BASE}/workflows/${selectedWorkflowId}/schedules/${scheduleId}`,
          { method: "DELETE", headers: authHeaders() }
        );
        const data = await response.json();
        if (data.code === 200) {
          message.success("定时任务已删除");
          await fetchSchedules(selectedWorkflowId);
        } else {
          message.error(data.message || "删除失败");
        }
      } catch (error) {
        message.error(extractErrorDetail(error, "删除失败"));
      } finally {
        setDeletingId(null);
      }
    },
    [selectedWorkflowId, fetchSchedules, message]
  );

  return {
    schedules,
    submitting,
    deletingId,
    selectedWorkflowId,
    openFor,
    close,
    create,
    remove,
  };
}
