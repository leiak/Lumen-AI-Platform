import { render, screen, fireEvent } from "@testing-library/react";
import { ConfigProvider } from "antd";
import { describe, expect, it, vi } from "vitest";
import { RetryConfigForm } from "@/components/workflow/_base/error/RetryConfigForm";

const wrap = (ui: React.ReactNode) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{ui}</ConfigProvider>
);

describe("RetryConfigForm", () => {
  it("renders max_retries and retry_interval inputs", () => {
    render(wrap(<RetryConfigForm value={null} onChange={() => {}} />));
    expect(screen.getByText("最大重试次数")).toBeInTheDocument();
    expect(screen.getByText("重试间隔(秒)")).toBeInTheDocument();
  });

  it("calls onChange with new max_retries", () => {
    const onChange = vi.fn();
    render(wrap(<RetryConfigForm value={null} onChange={onChange} />));
    const input = screen.getByDisplayValue("0");
    fireEvent.change(input, { target: { value: "3" } });
    expect(onChange).toHaveBeenCalledWith({ max_retries: 3, retry_interval: 1.0 });
  });
});
