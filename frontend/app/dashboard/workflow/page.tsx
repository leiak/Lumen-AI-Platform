"use client";

import { useState } from "react";
import { Button, App as AntdApp } from "antd";
import { PlusOutlined, AppstoreOutlined } from "@ant-design/icons";
import { useRouter } from "next/navigation";

import { useWorkflowList } from "./hooks/useWorkflowList";
import { useWorkflowRuns } from "./hooks/useWorkflowRuns";
import { useWorkflowSchedules } from "./hooks/useWorkflowSchedules";
import { useTemplatePublish } from "./hooks/useTemplatePublish";
import { useAppMessage, extractErrorDetail } from "./hooks/useAppMessage";
import { workflowApi, WorkflowRun } from "@/services/workflow";
import { InputValuesModal, InputVarSpec } from "@/components/workflow/designer/InputValuesModal";

import { WorkflowTable } from "./components/WorkflowTable";
import { CreateWorkflowModal } from "./components/CreateWorkflowModal";
import { ScheduleModal } from "./components/ScheduleModal";
import { PublishTemplateModal } from "./components/PublishTemplateModal";
import { RunResultDrawer } from "./components/RunResultDrawer";
import { RunHistoryDrawer } from "./components/RunHistoryDrawer";
import { RunDetailDrawer } from "./components/RunDetailDrawer";
import { SearchFilterBar } from "./components/SearchFilterBar";

/**
 * M30b: orchestrator layer. Wires hooks → components.
 *
 * The pre-M30b god component was 866 lines with 29 useState hooks and
 * 3 Modals + 3 Drawers + axios/fetch mixed. After M30b:
 *   - 4 hooks own the data (useWorkflowList, useWorkflowRuns,
 *     useWorkflowSchedules, useTemplatePublish)
 *   - 8 child components own the presentation
 *   - page.tsx is the wiring layer (~140 lines)
 *   - 0 static `message` imports (B2: App.useApp() everywhere)
 */
export default function WorkflowPage() {
  // M30b B2: App.useApp() for instance-method messages, not the
  // static import. The static import doesn't render under antd v5 +
  // Next.js 15 strict mode (MEMORY M14 quirk).
  const { message } = useAppMessage();
  // useAppMessage() already wraps App.useApp() — we only need the raw
  // <App> context (from AntdApp) to ensure the wrapper hook gets the
  // instance. The wrapped `message` is the same one, so a single
  // declaration is enough.
  void AntdApp;
  // M30 ship follow-up (2026-06-18): the sidebar entry "工作流" used
  // to nest "模板中心" as a child, which AntD ProLayout treats as a
  // collapse toggle — clicking "工作流" never navigated. Promote
  // templates to a sibling menu item and link the two pages directly
  // (one button each direction) so users can switch without going
  // through the sidebar.
  const router = useRouter();

  const list = useWorkflowList();
  const runs = useWorkflowRuns();
  const schedules = useWorkflowSchedules();
  const publish = useTemplatePublish();

  // Run result drawer state (immediate feedback after pressing 执行).
  const [runResult, setRunResult] = useState<WorkflowRun | null>(null);
  const [runDrawerOpen, setRunDrawerOpen] = useState(false);
  const [runningId, setRunningId] = useState<number | null>(null);

  const [createModalOpen, setCreateModalOpen] = useState(false);

  // M30 ship follow-up (2026-06-18): list page's "执行" button used
  // to call workflowApi.run(id, {}) directly, which meant any
  // workflow that declared an input node (e.g. the 4 of 8 seed
  // templates that ask for variables like user_name / order_id)
  // would always fail with a Jinja2 "is undefined" error from the
  // downstream template node. The fix has two parts:
  //   (a) services/workflow.ts:120 now wraps the body as
  //       { input_data: values } so the backend schema accepts it.
  //   (b) here in the list page, the row's onRun click now fetches
  //       the workflow definition, collects the input node's
  //       variables, and routes through the same InputValuesModal
  //       the designer uses. If the workflow has zero input
  //       variables the modal is skipped (mirrors designer behavior
  //       in designer/page.tsx:609-616).
  const [pendingInputRun, setPendingInputRun] = useState<{
    id: number;
    variables: InputVarSpec[];
  } | null>(null);

  const doRun = async (id: number, inputData: Record<string, any>) => {
    setRunningId(id);
    setRunResult(null);
    setRunDrawerOpen(true);
    try {
      const response = await workflowApi.run(id, inputData);
      const payload: WorkflowRun | undefined = response.data.data;
      if (response.data.code === 200 && payload) {
        setRunResult(payload);
        if (payload.status === "failed") {
          message.error("工作流执行失败");
        } else {
          message.success("工作流执行成功");
        }
      }
    } catch (error) {
      message.error(extractErrorDetail(error, "执行失败"));
    } finally {
      setRunningId(null);
    }
  };

  const handleRunClick = async (id: number) => {
    try {
      // Need the full definition to read the input node's variables.
      // The list endpoint intentionally omits the definition (saves
      // bandwidth on long tables), so we do a single targeted GET.
      const resp = await workflowApi.get(id);
      if (resp.data.code !== 200 || !resp.data.data) {
        message.error("无法加载工作流定义");
        return;
      }
      const wf = resp.data.data;
      const inputNode = (wf.definition?.nodes ?? []).find(
        (n) => n.type === "input"
      );
      // config.variables is the persisted shape; React Flow's `data`
      // would be the in-memory mirror but we read the API shape so
      // the list page doesn't depend on the designer's local state.
      const rawVars = (inputNode?.config?.variables ?? []) as Array<{
        name: string;
        type?: string;
        required?: boolean;
      }>;
      const variables: InputVarSpec[] = rawVars.map((v) => ({
        name: v.name,
        type: (v.type ?? "string") as InputVarSpec["type"],
        required: v.required ?? false,
      }));
      if (variables.length === 0) {
        void doRun(id, {});
        return;
      }
      setPendingInputRun({ id, variables });
    } catch (error) {
      message.error(extractErrorDetail(error, "加载工作流定义失败"));
    }
  };

  const handleInputConfirm = (values: Record<string, any>) => {
    const id = pendingInputRun?.id;
    setPendingInputRun(null);
    if (id !== undefined) void doRun(id, values);
  };

  const handleInputCancel = () => {
    setPendingInputRun(null);
  };

  return (
    <div style={{ padding: 24 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 16,
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <div style={{ display: "flex", gap: 8 }}>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setCreateModalOpen(true)}
          >
            创建工作流
          </Button>
          <Button
            icon={<AppstoreOutlined />}
            onClick={() => router.push("/dashboard/workflow/templates")}
          >
            浏览模板中心
          </Button>
        </div>
        <SearchFilterBar
          search={list.search}
          isActive={list.isActive}
          onSearchChange={list.setSearch}
          onActiveChange={list.setIsActive}
          onRefresh={list.refresh}
        />
      </div>

      <WorkflowTable
        workflows={list.workflows}
        loading={list.loading}
        page={list.page}
        pageSize={list.pageSize}
        total={list.total}
        runningId={runningId}
        publishingId={publish.loadingWorkflowId}
        onPageChange={list.setPage}
        onRun={handleRunClick}
        onEditSchedules={(id) => schedules.openFor(id)}
        onViewHistory={runs.openHistory}
        onPublishTemplate={publish.openFor}
        onDelete={list.handleDelete}
      />

      <CreateWorkflowModal
        open={createModalOpen}
        onCancel={() => setCreateModalOpen(false)}
        onSubmit={list.handleCreate}
      />

      <ScheduleModal
        open={schedules.selectedWorkflowId !== null}
        schedules={schedules.schedules}
        submitting={schedules.submitting}
        deletingId={schedules.deletingId}
        onCancel={schedules.close}
        onCreate={schedules.create}
        onDelete={schedules.remove}
      />

      <PublishTemplateModal
        open={publish.open}
        submitting={publish.submitting}
        initialValues={publish.initialValues}
        onCancel={publish.close}
        onSubmit={publish.submit}
      />

      <RunResultDrawer
        open={runDrawerOpen}
        run={runResult}
        onClose={() => setRunDrawerOpen(false)}
      />

      <RunHistoryDrawer
        open={runs.historyWorkflowId !== null}
        workflowName={runs.historyWorkflowName}
        runs={runs.historyRuns}
        loading={runs.historyLoading}
        page={runs.historyPage}
        pageSize={runs.historyPageSize}
        total={runs.historyTotal}
        onClose={runs.closeHistory}
        onPageChange={(p, ps) => {
          runs.setHistoryPage(p);
          runs.setHistoryPageSize(ps);
        }}
        onSelectRun={runs.openRunDetail}
      />

      <RunDetailDrawer
        open={runs.detailRun !== null}
        run={runs.detailRun}
        nodeRuns={runs.detailNodeRuns}
        loading={runs.detailLoading}
        onClose={runs.closeRunDetail}
      />

      <InputValuesModal
        open={pendingInputRun !== null}
        variables={pendingInputRun?.variables ?? []}
        onCancel={handleInputCancel}
        onConfirm={handleInputConfirm}
      />
    </div>
  );
}
