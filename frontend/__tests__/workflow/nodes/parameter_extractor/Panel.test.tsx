import { render, screen } from "@testing-library/react";
import { ConfigProvider } from "antd";
import { ParameterExtractorPanel } from "@/components/workflow/nodes/parameter_extractor/Panel";
import type { WorkflowNode } from "@/services/workflow";

vi.mock("@/components/workflow/ModelSelector", () => ({
  ModelSelector: () => <div data-testid="model-selector" />,
}));

const wrap = (ui: React.ReactNode) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{ui}</ConfigProvider>
);

const baseNode: WorkflowNode = {
  id: "pe1", type: "parameter_extractor", position: { x: 0, y: 0 }, data: {},
  config: { model_config_id: 0, input_text: "x", parameters: [] },
};

describe("ParameterExtractorPanel", () => {
  it("renders ModelSelector", () => {
    render(wrap(<ParameterExtractorPanel node={baseNode} nodes={[]} edges={[]} onChange={() => {}} />));
    expect(screen.getByTestId("model-selector")).toBeInTheDocument();
  });

  it("renders input_text area", () => {
    render(wrap(<ParameterExtractorPanel node={baseNode} nodes={[]} edges={[]} onChange={() => {}} />));
    expect(screen.getByDisplayValue("x")).toBeInTheDocument();
  });

  it("shows parameters table", () => {
    render(wrap(<ParameterExtractorPanel node={baseNode} nodes={[]} edges={[]} onChange={() => {}} />));
    expect(screen.getByText(/参数/)).toBeInTheDocument();
  });
});
