import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ConfigProvider } from "antd";
import { ToolPanel } from "@/components/workflow/nodes/tool/Panel";
import type { WorkflowNode } from "@/services/workflow";

vi.mock("@/components/workflow/ToolSelector", () => ({
  ToolSelector: ({ value, onChange }: any) => (
    <div>
      <div data-testid="tool-selector-value">{value ?? "null"}</div>
      <button
        data-testid="tool-selector"
        onClick={() => onChange(5, "search")}
      >
        pick
      </button>
      <button
        data-testid="tool-selector-clear"
        onClick={() => onChange(null, "")}
      >
        clear
      </button>
    </div>
  ),
}));

const wrap = (ui: React.ReactNode) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{ui}</ConfigProvider>
);

const baseNode: WorkflowNode = {
  id: "t1",
  type: "tool",
  position: { x: 0, y: 0 },
  data: {},
  config: { tool_id: 0, tool_name_cache: "", arguments: {} },
};

describe("ToolPanel", () => {
  it("renders ToolSelector", () => {
    render(
      wrap(
        <ToolPanel
          node={baseNode}
          nodes={[]}
          edges={[]}
          onChange={() => {}}
        />
      )
    );
    expect(screen.getByTestId("tool-selector")).toBeInTheDocument();
  });

  it("hides arguments table when no tool selected", () => {
    render(
      wrap(
        <ToolPanel
          node={baseNode}
          nodes={[]}
          edges={[]}
          onChange={() => {}}
        />
      )
    );
    expect(screen.queryByText("参数")).not.toBeInTheDocument();
  });

  it("shows arguments table when tool selected", () => {
    const node = {
      ...baseNode,
      config: {
        ...baseNode.config,
        tool_id: 5,
        tool_name_cache: "search",
        arguments: { q: "x" },
      },
    };
    render(
      wrap(
        <ToolPanel
          node={node}
          nodes={[]}
          edges={[]}
          onChange={() => {}}
        />
      )
    );
    // Form.Item label is "参数"
    expect(screen.getByText("参数")).toBeInTheDocument();
    // Existing argument row key is rendered in the table.
    expect(screen.getByText("q")).toBeInTheDocument();
  });

  it("calls onChange when tool is picked", () => {
    const onChange = vi.fn();
    render(
      wrap(
        <ToolPanel
          node={baseNode}
          nodes={[]}
          edges={[]}
          onChange={onChange}
        />
      )
    );
    fireEvent.click(screen.getByTestId("tool-selector"));
    expect(onChange).toHaveBeenCalled();
    const cfg = onChange.mock.calls[0][0].config;
    expect(cfg.tool_id).toBe(5);
    expect(cfg.tool_name_cache).toBe("search");
  });

  it("shows advanced options", () => {
    render(
      wrap(
        <ToolPanel
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
