"use client";

import { useCallback, useState } from "react";
import { workflowApi } from "@/services/workflow";
import { workflowTemplateApi } from "@/services/workflowTemplate";
import { useAppMessage, extractErrorDetail } from "./useAppMessage";

/**
 * M30b: state + actions for the "publish workflow as template" modal.
 *
 * Loads the workflow (to prefill name / description) and posts the
 * publish form to /workflow-templates/. The modal closes on success
 * and the parent (the WorkflowTable row) refetches the list so the
 * user can see the new template in the marketplace.
 */
export function useTemplatePublish() {
  const { message } = useAppMessage();
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [loadingWorkflowId, setLoadingWorkflowId] = useState<number | null>(null);
  const [initialValues, setInitialValues] = useState<{
    name: string;
    description?: string;
  }>({ name: "" });
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<number | null>(null);

  const openFor = useCallback(
    async (workflowId: number) => {
      setLoadingWorkflowId(workflowId);
      try {
        const wf = await workflowApi.get(workflowId);
        const wfData: any = wf.data.data;
        setInitialValues({
          name: wfData?.name ? `${wfData.name} (模板)` : "",
          description: wfData?.description || "",
        });
        setSelectedWorkflowId(workflowId);
        setOpen(true);
      } catch (err) {
        message.error(extractErrorDetail(err, "加载工作流失败"));
      } finally {
        setLoadingWorkflowId(workflowId === null ? null : null);
        setLoadingWorkflowId(null);
      }
    },
    [message]
  );

  const close = useCallback(() => {
    setOpen(false);
    setSelectedWorkflowId(null);
    setInitialValues({ name: "" });
  }, []);

  const submit = useCallback(
    async (values: { name: string; description?: string; category?: string }) => {
      if (!selectedWorkflowId) return false;
      setSubmitting(true);
      try {
        const res = await workflowTemplateApi.publish({
          name: values.name,
          description: values.description,
          category: values.category || "general",
          workflow_id: selectedWorkflowId,
        });
        if (res.data.code === 200) {
          message.success("已发布为模板");
          setOpen(false);
          setSelectedWorkflowId(null);
          setInitialValues({ name: "" });
          return true;
        }
        message.error(res.data.message || "发布失败");
        return false;
      } catch (err) {
        message.error(extractErrorDetail(err, "发布失败"));
        return false;
      } finally {
        setSubmitting(false);
      }
    },
    [selectedWorkflowId, message]
  );

  return {
    open,
    submitting,
    loadingWorkflowId,
    initialValues,
    openFor,
    close,
    submit,
  };
}
