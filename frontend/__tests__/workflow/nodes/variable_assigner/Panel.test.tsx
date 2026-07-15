import { render, screen } from "@testing-library/react";
import { ConfigProvider } from "antd";
import { VariableAssignerPanel } from "@/components/workflow/nodes/variable_assigner/Panel";
import type { WorkflowNode } from "@/services/workflow";

const wrap = (ui: React.ReactNode) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{ui}</ConfigProvider>
);

const baseNode: WorkflowNode = {
  id: "va1",
  type: "variable_assigner",
  position: { x: 0, y: 0 },
  data: {},
  config: { operations: [] },
};

describe("VariableAssignerPanel", () => {
  it("renders operations table", () => {
    render(
      wrap(
        <VariableAssignerPanel
          node={baseNode}
          nodes={[]}
          edges={[]}
          onChange={() => {}}
        />
      )
    );
    // "添加赋值" button + "变量名" column header confirm the operations table is rendered.
    expect(screen.getByText(/\+ 添加赋值/)).toBeInTheDocument();
    expect(screen.getByText("变量名")).toBeInTheDocument();
  });

  it("renders advanced options", () => {
    render(
      wrap(
        <VariableAssignerPanel
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
