import { render, screen } from "@testing-library/react";
import { ConfigProvider } from "antd";
import { TemplateTransformPanel } from "@/components/workflow/nodes/template_transform/Panel";
import type { WorkflowNode } from "@/services/workflow";

const wrap = (ui: React.ReactNode) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{ui}</ConfigProvider>
);

const baseNode: WorkflowNode = {
  id: "tt1", type: "template_transform", position: { x: 0, y: 0 }, data: {},
  config: { template: "Hello {{ llm.response }}" },
};

describe("TemplateTransformPanel", () => {
  it("renders template textarea with value", () => {
    render(wrap(<TemplateTransformPanel node={baseNode} nodes={[]} edges={[]} onChange={() => {}} />));
    expect(screen.getByDisplayValue("Hello {{ llm.response }}")).toBeInTheDocument();
  });

  it("shows Jinja2 syntax alert", () => {
    render(wrap(<TemplateTransformPanel node={baseNode} nodes={[]} edges={[]} onChange={() => {}} />));
    expect(screen.getByText(/Jinja2/)).toBeInTheDocument();
  });

  it("shows available vars sidebar", () => {
    render(wrap(<TemplateTransformPanel node={baseNode} nodes={[]} edges={[]} onChange={() => {}} />));
    expect(screen.getByText(/可用变量/)).toBeInTheDocument();
  });
});
