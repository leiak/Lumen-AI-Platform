// frontend/__tests__/workflow/_base/variable/VarReferencePicker.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigProvider } from "antd";
import { describe, expect, it, vi } from "vitest";
import type { WorkflowNode, WorkflowEdge } from "@/services/workflow";
import { VarReferencePicker } from "@/components/workflow/_base/variable/VarReferencePicker";
import { BlockEnum, VarType } from "@/components/workflow/_base/variable/types";

const nodes: WorkflowNode[] = [
  { id: "input_1", type: BlockEnum.Input, config: { title: "Input" }, position: { x: 0, y: 0 } },
  { id: "llm_1", type: BlockEnum.LLM, config: { title: "LLM" }, position: { x: 0, y: 0 } },
];
const edges: WorkflowEdge[] = [{ id: "e1", source: "input_1", target: "llm_1" }];

// AntD Button with non-English text requires this ConfigProvider setting to avoid
// a console.error about needing to set `autoInsertSpace` to false.
const TestWrapper = ({ children }: { children: React.ReactNode }) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{children}</ConfigProvider>
);

describe("VarReferencePicker", () => {
  it("renders the current value placeholder", () => {
    render(
      <VarReferencePicker
        nodeId="llm_1"
        nodes={nodes}
        edges={edges}
        value={["input_1", "value"]}
        onChange={() => {}}
      />,
      { wrapper: TestWrapper }
    );
    // Placeholder text uses {{ node_id.var_name }} form
    expect(screen.getByDisplayValue(/input_1\.value/)).toBeTruthy();
  });

  it("opens the popup on click and shows upstream vars", async () => {
    const user = userEvent.setup();
    render(
      <VarReferencePicker
        nodeId="llm_1"
        nodes={nodes}
        edges={edges}
        value={null}
        onChange={() => {}}
      />,
      { wrapper: TestWrapper }
    );
    // Click the picker button (the "选择" button)
    await user.click(screen.getByTestId("var-picker-button"));
    // Popup shows the Input node's "value" var
    expect(screen.getByText("Input")).toBeTruthy();
    expect(screen.getByText("value")).toBeTruthy();
  });

  it("calls onChange with selector + type when a var is selected", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <VarReferencePicker
        nodeId="llm_1"
        nodes={nodes}
        edges={edges}
        value={null}
        onChange={onChange}
      />,
      { wrapper: TestWrapper }
    );
    await user.click(screen.getByTestId("var-picker-button"));
    // Click on the "value" var item (rendered by VarReferenceVars with data-testid)
    await user.click(screen.getByTestId("var-input_1-value"));
    expect(onChange).toHaveBeenCalledWith(["input_1", "value"], VarType.object);
  });

  it("applies filterVar — only string vars appear", async () => {
    const user = userEvent.setup();
    render(
      <VarReferencePicker
        nodeId="llm_1"
        nodes={[
          { id: "input_1", type: BlockEnum.Input, config: { variables: [{ name: "q", type: "string" }, { name: "n", type: "number" }] }, position: { x: 0, y: 0 } },
          { id: "llm_1", type: BlockEnum.LLM, config: { title: "LLM" }, position: { x: 0, y: 0 } },
        ]}
        edges={[{ id: "e1", source: "input_1", target: "llm_1" }]}
        value={null}
        onChange={() => {}}
        filterVar={(v) => v.type === "string"}
      />,
      { wrapper: TestWrapper }
    );
    await user.click(screen.getByTestId("var-picker-button"));
    expect(screen.getByText("q")).toBeTruthy();
    expect(screen.queryByText("n")).toBeNull();
  });
});
