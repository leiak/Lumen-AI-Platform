import { render, screen, fireEvent } from "@testing-library/react";
import { ConfigProvider } from "antd";
import { describe, expect, it, vi } from "vitest";
import { ErrorStrategyPicker } from "@/components/workflow/_base/error/ErrorStrategyPicker";

const wrap = (ui: React.ReactNode) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{ui}</ConfigProvider>
);

describe("ErrorStrategyPicker", () => {
  it("renders 3 radio buttons", () => {
    render(wrap(<ErrorStrategyPicker value={null} onChange={() => {}} />));
    expect(screen.getByText("失败时停止分支")).toBeInTheDocument();
    expect(screen.getByText("使用默认值")).toBeInTheDocument();
    expect(screen.getByText("忽略错误")).toBeInTheDocument();
  });

  it("calls onChange when fail_branch selected", () => {
    const onChange = vi.fn();
    // value starts as "ignore" so clicking "失败时停止分支" triggers a real change.
    // AntD Radio.Group does not fire onChange when clicking the already-selected option.
    render(wrap(<ErrorStrategyPicker value="ignore" onChange={onChange} />));
    fireEvent.click(screen.getByText("失败时停止分支"));
    expect(onChange).toHaveBeenCalledWith("fail_branch", undefined);
  });

  it("shows default_value TextArea when strategy is default_value", () => {
    render(
      wrap(
        <ErrorStrategyPicker
          value="default_value"
          onChange={() => {}}
          defaultValue={{ x: 1 }}
        />
      )
    );
    // The component pretty-prints JSON with 2-space indentation. Compare
    // the raw textarea value directly to avoid getByDisplayValue's
    // whitespace-collapsing normalizer.
    const expectedText = JSON.stringify({ x: 1 }, null, 2);
    expect(screen.getByRole("textbox")).toHaveValue(expectedText);
  });

  it("parses JSON in default_value and calls onChange", () => {
    const onChange = vi.fn();
    render(
      wrap(
        <ErrorStrategyPicker
          value="default_value"
          onChange={onChange}
          defaultValue={{}}
        />
      )
    );
    fireEvent.change(screen.getByRole("textbox"), { target: { value: '{"a":2}' } });
    expect(onChange).toHaveBeenCalledWith("default_value", { a: 2 });
  });
});
