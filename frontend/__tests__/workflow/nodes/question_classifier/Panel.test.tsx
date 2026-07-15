import { render, screen } from "@testing-library/react";
import { ConfigProvider } from "antd";
import { QuestionClassifierPanel } from "@/components/workflow/nodes/question_classifier/Panel";
import type { WorkflowNode } from "@/services/workflow";

vi.mock("@/components/workflow/ModelSelector", () => ({
  ModelSelector: () => <div data-testid="model-selector" />,
}));

const wrap = (ui: React.ReactNode) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{ui}</ConfigProvider>
);

const baseNode: WorkflowNode = {
  id: "qc1", type: "question_classifier", position: { x: 0, y: 0 }, data: {},
  config: { model_config_id: 0, input_text: "x", categories: [] },
};

describe("QuestionClassifierPanel", () => {
  it("renders ModelSelector", () => {
    render(wrap(<QuestionClassifierPanel node={baseNode} nodes={[]} edges={[]} onChange={() => {}} />));
    expect(screen.getByTestId("model-selector")).toBeInTheDocument();
  });

  it("renders categories table", () => {
    render(wrap(<QuestionClassifierPanel node={baseNode} nodes={[]} edges={[]} onChange={() => {}} />));
    expect(screen.getByText(/类别/)).toBeInTheDocument();
  });
});
