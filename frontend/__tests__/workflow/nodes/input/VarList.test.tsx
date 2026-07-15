import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigProvider, App as AntdApp } from "antd";
import { describe, expect, it, vi } from "vitest";
import { VarList } from "@/components/workflow/nodes/input/VarList";
import { VarType } from "@/components/workflow/_base/variable/types";

function TestWrapper({ children }: { children: React.ReactNode }) {
  // App.useApp() inside AntD Select (the type column uses Switch which can
  // warn in some setups) is not strictly needed here, but keep parity with
  // the rest of the workflow test suite.
  return <ConfigProvider><AntdApp>{children}</AntdApp></ConfigProvider>;
}

describe("VarList", () => {
  it("renders one row per input variable", () => {
    const onChange = vi.fn();
    render(
      <TestWrapper>
        <VarList
          value={[
            { name: "user_query", type: VarType.string, required: true },
            { name: "count", type: VarType.number, required: false },
          ]}
          onChange={onChange}
        />
      </TestWrapper>
    );
    expect(screen.getByDisplayValue("user_query")).toBeTruthy();
    expect(screen.getByDisplayValue("count")).toBeTruthy();
  });

  // Regression for 2026-06-11 bug: in the 320px-wide left toolbar the 名称
  // column had no explicit width, so the other fixed columns (类型 140,
  // 必填 60, delete 40) crowded it down to ~56px and the AntD Input inside
  // visually clipped the placeholder/value. The fix sets explicit widths
  // on every column; this test confirms the rendered AntD <col> elements
  // carry style="width: Xpx" (the DOM evidence AntD produces) so the
  // 名称 column gets the space it needs.
  it("uses explicit pixel widths on every column (no auto-sizing in narrow toolbars)", () => {
    const { container } = render(
      <TestWrapper>
        <VarList
          value={[{ name: "x", type: VarType.string, required: false }]}
          onChange={vi.fn()}
        />
      </TestWrapper>
    );
    // AntD Table renders <colgroup><col style="width: ...px"></colgroup>.
    // Find the colgroup; expect 4 cols, all with an explicit width in px.
    const cols = container.querySelectorAll("colgroup col");
    expect(cols.length).toBe(4);
    for (const col of Array.from(cols)) {
      const style = (col as HTMLElement).getAttribute("style") ?? "";
      // The width value is emitted as e.g. `width: 120px`. Reject any
      // col whose width comes from auto-sizing (no px width declared).
      expect(style, `col missing explicit px width: ${style}`).toMatch(
        /width:\s*\d+px/
      );
    }
  });

  it("typing into the 名称 input propagates to onChange (regression for clipped input)", () => {
    const onChange = vi.fn();
    render(
      <TestWrapper>
        <VarList
          value={[{ name: "", type: VarType.string, required: false }]}
          onChange={onChange}
        />
      </TestWrapper>
    );
    // The 名称 input uses placeholder="user_query" (see VarList.tsx) so
    // it's uniquely targetable even when value is empty.
    const nameInput = screen.getByPlaceholderText("user_query");
    fireEvent.change(nameInput, { target: { value: "user_query" } });
    expect(onChange).toHaveBeenCalled();
    const last = onChange.mock.calls[onChange.mock.calls.length - 1][0];
    expect(last[0].name).toBe("user_query");
  });

  it("clicking 添加变量 appends a new row with empty name + string type", () => {
    const onChange = vi.fn();
    render(
      <TestWrapper>
        <VarList
          value={[{ name: "first", type: VarType.string, required: false }]}
          onChange={onChange}
        />
      </TestWrapper>
    );
    screen.getByText("添加变量").click();
    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0];
    expect(next).toHaveLength(2);
    expect(next[1]).toEqual({ name: "", type: VarType.string, required: false });
  });
});
