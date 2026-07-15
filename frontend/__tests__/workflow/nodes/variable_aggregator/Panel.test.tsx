import { render, screen } from "@testing-library/react";
import { ConfigProvider } from "antd";
import { VariableAggregatorPanel } from "@/components/workflow/nodes/variable_aggregator/Panel";
import type { WorkflowNode } from "@/services/workflow";

const wrap = (ui: React.ReactNode) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{ui}</ConfigProvider>
);

const baseNode: WorkflowNode = {
  id: "vagg1", type: "variable_aggregator", position: { x: 0, y: 0 }, data: {},
  config: { source_node_id: "", source_var: "results", aggregation: "collect" },
};

describe("VariableAggregatorPanel", () => {
  it("renders aggregation radio", () => {
    render(wrap(<VariableAggregatorPanel node={baseNode} nodes={[]} edges={[]} onChange={() => {}} />));
    expect(screen.getByText("collect")).toBeInTheDocument();
    expect(screen.getByText("sum")).toBeInTheDocument();
    expect(screen.getByText("average")).toBeInTheDocument();
  });

  it("renders source_node Select", () => {
    render(wrap(<VariableAggregatorPanel node={baseNode} nodes={[]} edges={[]} onChange={() => {}} />));
    expect(screen.getByText(/源节点/)).toBeInTheDocument();
  });
});
