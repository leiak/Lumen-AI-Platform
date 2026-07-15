import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ConfigProvider } from "antd";
import { KBRetrievalPanel } from "@/components/workflow/nodes/knowledge_retrieval/Panel";
import type { WorkflowNode } from "@/services/workflow";

vi.mock("@/components/workflow/KBSelector", () => ({
  KBSelector: () => <div data-testid="kb-selector" />,
}));

vi.mock("@/services/nodes", () => ({
  nodesApi: { previewKB: vi.fn() },
}));

const wrap = (ui: React.ReactNode) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{ui}</ConfigProvider>
);

const baseNode: WorkflowNode = {
  id: "k1",
  type: "knowledge_retrieval",
  position: { x: 0, y: 0 },
  data: {},
  config: { kb_id: 0, kb_name_cache: "", query: "", top_k: 5 },
};

describe("KBRetrievalPanel", () => {
  it("renders KB selector", () => {
    render(
      wrap(
        <KBRetrievalPanel
          node={baseNode}
          nodes={[]}
          edges={[]}
          onChange={() => {}}
        />
      )
    );
    expect(screen.getByTestId("kb-selector")).toBeInTheDocument();
  });

  it("renders top_k input with default 5", () => {
    render(
      wrap(
        <KBRetrievalPanel
          node={baseNode}
          nodes={[]}
          edges={[]}
          onChange={() => {}}
        />
      )
    );
    expect(screen.getByDisplayValue("5")).toBeInTheDocument();
  });

  it("shows advanced options", () => {
    render(
      wrap(
        <KBRetrievalPanel
          node={baseNode}
          nodes={[]}
          edges={[]}
          onChange={() => {}}
        />
      )
    );
    expect(screen.getByText(/高级选项/)).toBeInTheDocument();
  });
});
