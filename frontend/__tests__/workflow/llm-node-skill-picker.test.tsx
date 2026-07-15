// frontend/__tests__/workflow/llm-node-skill-picker.test.tsx
// Verifies the "已安装技能" multi-select in the LLMPanel:
//  1. loads installed skills on mount via skillsApi.listInstalled(1, 50)
//  2. renders the Select in mode="multiple"
//  3. reflects the node's skill_ids as the Select's current value
//  4. shows the placeholder when no skills are selected
//
// This is a strong-coverage alternative to the plan's soft-target
// try/catch. LLMPanel is already its own module (named export from
// @/components/workflow/nodes/llm/Panel), so we render it directly with
// minimal PanelProps — much lighter than mounting the full designer page.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { ConfigProvider } from "antd";

// Replace ModelSelector and VarReferencePicker with stubs. They pull in
// heavy dependency trees (ModelSelector -> CreateModelInlineModal ->
// modelsApi; VarReferencePicker -> useAvailableVarList hook that needs a
// real ReactFlow context) and are not in scope for the skill picker.
vi.mock("@/components/workflow/ModelSelector", () => ({
  ModelSelector: () => <div data-testid="model-selector" />,
}));
vi.mock("@/components/workflow/_base/variable/VarReferencePicker", () => ({
  VarReferencePicker: () => <div data-testid="var-reference-picker" />,
}));

// Mock skills API. The LLMPanel reads res.data.data.data (3-level envelope).
const mockListInstalled = vi.fn();
vi.mock("@/services/skills", () => ({
  skillsApi: {
    listInstalled: (...args: unknown[]) => mockListInstalled(...args),
  },
}));

import { LLMPanel } from "@/components/workflow/nodes/llm/Panel";
import type { WorkflowNode } from "@/services/workflow";

const TestWrapper = ({ children }: { children: React.ReactNode }) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{children}</ConfigProvider>
);

const installedResponse = {
  data: {
    code: 200,
    data: [
      { id: 1, skill_id: 11, name: "代码优化专家", category: "code" },
      { id: 2, skill_id: 12, name: "文档写作助手", category: "writing" },
    ],
    total: 2,
    page: 1,
    page_size: 50,
  },
};

const baseNode: WorkflowNode = {
  id: "llm-1",
  type: "llm",
  config: { prompt: "hi" },
  position: { x: 0, y: 0 },
};

describe("LLMPanel — skill picker", () => {
  beforeEach(() => {
    mockListInstalled.mockReset();
    mockListInstalled.mockResolvedValue(installedResponse);
  });

  it("renders the '已安装技能 (可选)' Form.Item label", async () => {
    render(
      <LLMPanel node={baseNode} nodes={[]} edges={[]} onChange={() => {}} />,
      { wrapper: TestWrapper }
    );
    // Async wait so the LLMPanel's useEffect-driven API call settles
    // inside act() and we don't get a React act() warning.
    await waitFor(() => {
      expect(screen.getByText(/已安装技能/)).toBeTruthy();
    });
  });

  it("calls skillsApi.listInstalled(1, 50) on mount", async () => {
    render(
      <LLMPanel node={baseNode} nodes={[]} edges={[]} onChange={() => {}} />,
      { wrapper: TestWrapper }
    );
    await waitFor(() => {
      expect(mockListInstalled).toHaveBeenCalledWith(1, 50);
    });
  });

  it("renders the Select as a multi-select", async () => {
    render(
      <LLMPanel node={baseNode} nodes={[]} edges={[]} onChange={() => {}} />,
      { wrapper: TestWrapper }
    );
    // AntD applies .ant-select-multiple to the host element when
    // mode="multiple" is set on the Select. Wait for the API call to
    // resolve so any post-mount state updates land in act().
    await waitFor(() => {
      expect(mockListInstalled).toHaveBeenCalled();
    });
    expect(document.querySelector(".ant-select-multiple")).toBeTruthy();
  });

  it("reflects the node's skill_ids as the Select's current value", async () => {
    const nodeWithSkill: WorkflowNode = {
      ...baseNode,
      config: { ...baseNode.config, skill_ids: [11, 12] },
    };
    render(
      <LLMPanel
        node={nodeWithSkill}
        nodes={[]}
        edges={[]}
        onChange={() => {}}
      />,
      { wrapper: TestWrapper }
    );
    await waitFor(() => {
      expect(mockListInstalled).toHaveBeenCalled();
    });
    // Two selection tags rendered for the two pre-selected skill ids.
    expect(
      document.querySelectorAll(".ant-select-selection-item").length
    ).toBe(2);
  });

  it("shows the multi-select placeholder when no skills are selected", async () => {
    render(
      <LLMPanel node={baseNode} nodes={[]} edges={[]} onChange={() => {}} />,
      { wrapper: TestWrapper }
    );
    await waitFor(() => {
      expect(screen.getByText("从本租户已装技能中选择")).toBeTruthy();
    });
  });
});
