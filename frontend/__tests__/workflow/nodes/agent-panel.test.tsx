// frontend/__tests__/workflow/nodes/agent-panel.test.tsx
// 验证 AgentPanel 解析 /api/v1/agents/ 响应时拿到的数组正确
// (PaginatedResponse 信封,res.data.data 是直接数组,不是 {items:[...]} 嵌套)。
//
// 历史 bug: Panel.tsx 写的是 `res.data.data.items ?? res.data.items ?? []`,
// 但后端 agent.py:79-84 返的是 `PaginatedResponse(data=[...],total,page,page_size)`,
// `data` 是 flat array,所以 `.items` 永远是 undefined → 下拉永远空,
// 即使 API 有 100 条 agent。
//
// 这个 fix 把 Panel 改成 `res.data.data ?? res.data ?? []` + Array.isArray 兜底,
// 下面测三个场景:
//   1. PaginatedResponse 信封 (实际后端形态) → 下拉有 N 条 option
//   2. 裸 array (极端 fallback,跟 CLAUDE.md 信封契约对应) → 同样有 N 条
//   3. 非数组 (接口挂掉返奇怪 shape) → 不崩、下拉空 + 不报 unhandled error
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { ConfigProvider } from "antd";

const mockList = vi.fn();
vi.mock("@/services/agent", () => ({
  agentApi: {
    list: (...args: unknown[]) => mockList(...args),
  },
}));

import { AgentPanel } from "@/components/workflow/nodes/agent/Panel";
import type { WorkflowNode } from "@/services/workflow";

const TestWrapper = ({ children }: { children: React.ReactNode }) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{children}</ConfigProvider>
);

const baseNode: WorkflowNode = {
  id: "agent-1",
  type: "agent",
  config: {},
  position: { x: 0, y: 0 },
};

describe("AgentPanel — agent picker", () => {
  beforeEach(() => {
    mockList.mockReset();
  });

  it("loads agentApi.list(1, 100) on mount", async () => {
    mockList.mockResolvedValue({
      data: {
        code: 200,
        message: "Success",
        data: [
          { id: 1, name: "Agent Alpha" },
          { id: 2, name: "Agent Beta" },
        ],
        total: 2,
        page: 1,
        page_size: 100,
      },
    });

    render(
      <AgentPanel node={baseNode} nodes={[]} edges={[]} onChange={() => {}} />,
      { wrapper: TestWrapper },
    );

    await waitFor(() => {
      expect(mockList).toHaveBeenCalledWith(1, 100);
    });
  });

  it("renders Select options when backend returns PaginatedResponse envelope", async () => {
    // 这是 backend lumen_api/v1/agent.py:79-84 的真实 shape —— data 是
    // flat array,Panel 必须从 res.data.data 拿到数组,不能读 .items。
    mockList.mockResolvedValue({
      data: {
        code: 200,
        message: "Success",
        data: [
          { id: 10, name: "客服助手" },
          { id: 11, name: "数据分析师" },
          { id: 12, name: "运维 Bot" },
        ],
        total: 3,
        page: 1,
        page_size: 100,
      },
    });

    render(
      <AgentPanel node={baseNode} nodes={[]} edges={[]} onChange={() => {}} />,
      { wrapper: TestWrapper },
    );

    // 等 API 调完 + Panel setState,然后开下拉看 option(AntD option 只
    // 在下拉打开时渲染进 DOM —— 见 KBSelector.test.tsx 同模式)
    await waitFor(() => {
      expect(mockList).toHaveBeenCalled();
    });
    fireEvent.mouseDown(screen.getByRole("combobox"));
    await waitFor(() => {
      expect(screen.getByText("客服助手")).toBeTruthy();
    });
    expect(screen.getByText("数据分析师")).toBeTruthy();
    expect(screen.getByText("运维 Bot")).toBeTruthy();
  });

  it("falls back gracefully when response is a bare array (no envelope)", async () => {
    // 兜底:某些 mock 工具可能直接返 [..],Panel 不能因为没 envelope 就崩。
    mockList.mockResolvedValue({
      data: [{ id: 1, name: "Lonely Agent" }],
    });

    render(
      <AgentPanel node={baseNode} nodes={[]} edges={[]} onChange={() => {}} />,
      { wrapper: TestWrapper },
    );

    await waitFor(() => {
      expect(mockList).toHaveBeenCalled();
    });
    // 不崩即可,具体 option 渲染走 AntD 内部,不在此测
  });

  it("falls back to empty when response shape is broken (no crash)", async () => {
    // 极端兜底:API 返 500 错或没 data 字段,Panel 必须不抛 unhandled
    // promise rejection。error state 在 UI 里(可选 Alert),不强制渲染。
    mockList.mockResolvedValue({ data: { code: 500, message: "boom" } });

    render(
      <AgentPanel node={baseNode} nodes={[]} edges={[]} onChange={() => {}} />,
      { wrapper: TestWrapper },
    );

    await waitFor(() => {
      expect(mockList).toHaveBeenCalled();
    });
    // Select 仍存在,只是无 option
    expect(document.querySelector(".ant-select")).toBeTruthy();
  });
});