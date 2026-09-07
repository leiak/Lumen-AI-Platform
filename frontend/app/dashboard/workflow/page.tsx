"use client";

import { useState } from "react";
import { Button, App as AntdApp } from "antd";
import { PlusOutlined, AppstoreOutlined } from "@ant-design/icons";
import { useRouter } from "next/navigation";

import { useWorkflowList } from "./hooks/useWorkflowList";
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
import { SearchFilterBar } from "./components/SearchFilterBar";

/**
 * M30b 2.0 (2026-09-07): 工作流列表 page。
 *
 * 之前是 268 行的 wiring + RunHistoryDrawer / RunDetailDrawer 状态机;
 * M30b 把历史 / 详情 / 版本拆到 4 个子路由,本页只剩:
 *   - 列表 + 搜索 / 过滤
 *   - 创建 / 执行 / 调度 / 模板发布 modal
 *   - RunResultDrawer(执行完后的立即反馈,留在本页)
 *   - 跳子页按钮(运行历史 / 版本快照)
 *
 * 子页:
 *   - /dashboard/workflow/runs         — 运行历史(全 workflow 视图)
 *   - /dashboard/workflow/runs/[id]    — 单次 run 详情
 *   - /dashboard/workflow/versions     — 版本快照列表
 *   - /dashboard/workflow/versions/[id]— 单版本详情
 *   - /dashboard/workflow/templates    — 模板中心(sibling 删除,本菜单第 3 子项)
 */
export default function WorkflowPage() {
  const { message } = useAppMessage();
  // useAppMessage() already wraps App.useApp(); AntdApp is unused now but
  // kept as a "no-op" for tsc to track the import side-effect.
  void AntdApp;
  const router = useRouter();

  const list = useWorkflowList();
  const schedules = useWorkflowSchedules();
  const publish = useTemplatePublish();

  // Run result drawer state (immediate feedback after pressing 执行).
  const [runResult, setRunResult] = useState<WorkflowRun | null>(null);
  const [runDrawerOpen, setRunDrawerOpen] = useState(false);
  const [runningId, setRunningId] = useState<number | null>(null);

  const [createModalOpen, setCreateModalOpen] = useState(false);

  // Input variables collection before execution (M30 follow-up):
  // workflows that declare an input node ask the user to fill values
  // before running. 0 variables → skip the modal.
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
      const resp = await workflowApi.get(id);
      if (resp.data.code !== 200 || !resp.data.data) {
        message.error("无法加载工作流定义");
        return;
      }
      const wf = resp.data.data;
      const inputNode = (wf.definition?.nodes ?? []).find(
        (n) => n.type === "input"
      );
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

  // M30b 2.0: history / versions 跳子路由,不再开 drawer。
  // 带 workflow_id query 让子页预选当前 workflow。
  const handleViewHistory = (id: number, _name: string) => {
    router.push(`/dashboard/workflow/runs?workflow_id=${id}`);
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
        onViewHistory={handleViewHistory}
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

      <InputValuesModal
        open={pendingInputRun !== null}
        variables={pendingInputRun?.variables ?? []}
        onCancel={handleInputCancel}
        onConfirm={handleInputConfirm}
      />
    </div>
  );
}
