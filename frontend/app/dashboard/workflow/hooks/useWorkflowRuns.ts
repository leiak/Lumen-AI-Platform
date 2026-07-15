"use client";

import { useCallback, useEffect, useState } from "react";
import { workflowApi, WorkflowRun, WorkflowNodeRun } from "@/services/workflow";
import { useAppMessage, extractErrorDetail } from "./useAppMessage";

/**
 * M30b: state + side effects for the run-history + run-detail drawers.
 *
 * One instance of the hook lives at the page level and gets passed
 * into the drawers as props. The hook is a thin orchestrator on top
 * of `workflowApi.listRuns` / `listRunNodes`.
 */
export function useWorkflowRuns() {
  const { message } = useAppMessage();
  const [historyWorkflowId, setHistoryWorkflowId] = useState<number | null>(null);
  const [historyWorkflowName, setHistoryWorkflowName] = useState<string>("");
  const [historyRuns, setHistoryRuns] = useState<WorkflowRun[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyPage, setHistoryPage] = useState(1);
  const [historyPageSize, setHistoryPageSize] = useState(10);
  const [historyTotal, setHistoryTotal] = useState(0);

  const [detailRun, setDetailRun] = useState<WorkflowRun | null>(null);
  const [detailNodeRuns, setDetailNodeRuns] = useState<WorkflowNodeRun[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);

  const openHistory = useCallback((workflowId: number, workflowName: string) => {
    setHistoryWorkflowId(workflowId);
    setHistoryWorkflowName(workflowName);
    setHistoryPage(1);
  }, []);

  const closeHistory = useCallback(() => {
    setHistoryWorkflowId(null);
    setHistoryWorkflowName("");
  }, []);

  const fetchHistory = useCallback(
    async (wfId: number, p: number, ps: number) => {
      setHistoryLoading(true);
      try {
        const response = await workflowApi.listRuns(wfId, p, ps);
        if (response.data.code === 200) {
          setHistoryRuns(response.data.data || []);
          setHistoryTotal(response.data.total || 0);
        }
      } catch (error) {
        message.error(extractErrorDetail(error, "获取执行历史失败"));
        setHistoryRuns([]);
        setHistoryTotal(0);
      } finally {
        setHistoryLoading(false);
      }
    },
    [message]
  );

  useEffect(() => {
    if (historyWorkflowId !== null) {
      fetchHistory(historyWorkflowId, historyPage, historyPageSize);
    }
  }, [historyWorkflowId, historyPage, historyPageSize, fetchHistory]);

  const openRunDetail = useCallback(
    async (run: WorkflowRun) => {
      if (!historyWorkflowId) return;
      setDetailRun(run);
      setDetailNodeRuns([]);
      setDetailLoading(true);
      try {
        const response = await workflowApi.listRunNodes(historyWorkflowId, run.id);
        if (response.data.code === 200) {
          setDetailNodeRuns(response.data.data || []);
        }
      } catch (error) {
        message.error(extractErrorDetail(error, "获取节点执行记录失败"));
      } finally {
        setDetailLoading(false);
      }
    },
    [historyWorkflowId, message]
  );

  const closeRunDetail = useCallback(() => {
    setDetailRun(null);
    setDetailNodeRuns([]);
  }, []);

  return {
    historyWorkflowId,
    historyWorkflowName,
    historyRuns,
    historyLoading,
    historyPage,
    historyPageSize,
    historyTotal,
    setHistoryPage,
    setHistoryPageSize,
    openHistory,
    closeHistory,

    detailRun,
    detailNodeRuns,
    detailLoading,
    openRunDetail,
    closeRunDetail,
  };
}
