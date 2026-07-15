import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ConfigProvider } from "antd";
import { CodePanel } from "@/components/workflow/nodes/code/Panel";
import type { WorkflowNode } from "@/services/workflow";

const wrap = (ui: React.ReactNode) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{ui}</ConfigProvider>
);

const baseNode: WorkflowNode = {
  id: "n1",
  type: "code",
  position: { x: 0, y: 0 },
  data: {},
  config: { code: "RESULT = 1", inputs_mapping: {}, output_var: "RESULT" },
};

describe("CodePanel", () => {
  it("renders code editor with existing code", () => {
    render(
      wrap(
        <CodePanel
          node={baseNode}
          nodes={[]}
          edges={[]}
          onChange={() => {}}
        />
      )
    );
    expect(screen.getByDisplayValue("RESULT = 1")).toBeInTheDocument();
  });

  it("calls onChange when code edited (debounced 200ms)", async () => {
    const onChange = vi.fn();
    render(
      wrap(
        <CodePanel
          node={baseNode}
          nodes={[]}
          edges={[]}
          onChange={onChange}
        />
      )
    );
    // First textbox is the code editor (the JSON one is second).
    const editors = screen.getAllByRole("textbox");
    fireEvent.change(editors[0], { target: { value: "RESULT = 2" } });
    // 收口-A: the onChange propagates after the 200ms debounce
    // window. We use waitFor (real timers) to assert the eventual
    // commit rather than faking timers — faking makes the test
    // brittle to other debounce-driven hooks the panel may pull in.
    await waitFor(() => expect(onChange).toHaveBeenCalled(), { timeout: 500 });
    const call = onChange.mock.calls[0][0];
    expect(call.config.code).toBe("RESULT = 2");
  });

  it("shows sandbox warning alert", () => {
    render(
      wrap(
        <CodePanel
          node={baseNode}
          nodes={[]}
          edges={[]}
          onChange={() => {}}
        />
      )
    );
    expect(screen.getByText(/沙箱/)).toBeInTheDocument();
  });
});
