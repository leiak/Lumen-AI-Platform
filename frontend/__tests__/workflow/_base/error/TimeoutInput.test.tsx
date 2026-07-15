import { render, screen, fireEvent } from "@testing-library/react";
import { ConfigProvider } from "antd";
import { describe, expect, it, vi } from "vitest";
import { TimeoutInput } from "@/components/workflow/_base/error/TimeoutInput";

const wrap = (ui: React.ReactNode) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{ui}</ConfigProvider>
);

describe("TimeoutInput", () => {
  it("renders default 30s placeholder", () => {
    render(wrap(<TimeoutInput value={null} onChange={() => {}} />));
    expect(screen.getByText("超时(秒)")).toBeInTheDocument();
  });

  it("calls onChange with number", () => {
    const onChange = vi.fn();
    render(wrap(<TimeoutInput value={null} onChange={onChange} />));
    const input = screen.getByRole("spinbutton");
    fireEvent.change(input, { target: { value: "10" } });
    expect(onChange).toHaveBeenCalledWith(10);
  });
});
