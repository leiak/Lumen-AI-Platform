import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ConfigProvider, App as AntdApp } from "antd";
import { InputValuesModal } from "@/components/workflow/designer/InputValuesModal";

function TestWrapper({ children }: { children: React.ReactNode }) {
  return <ConfigProvider><AntdApp>{children}</AntdApp></ConfigProvider>;
}

// All variables in the test sample are OPTIONAL so the submit-test only
// has to fill one field — if any were required: true, the modal's
// rules: [{required: true}] would block form submission and onConfirm
// would never fire, making the test green-by-zero-calls (deceptive).
const sampleVariables: { name: string; type: "string" | "number"; required: false }[] = [
  { name: "custom", type: "string", required: false },
  { name: "count", type: "number", required: false },
];

describe("InputValuesModal", () => {
  it("renders one labelled input per variable", () => {
    render(
      <TestWrapper>
        <InputValuesModal
          open
          variables={sampleVariables}
          onCancel={vi.fn()}
          onConfirm={vi.fn()}
        />
      </TestWrapper>
    );
    // AntD Form.Item labels
    expect(screen.getByText("custom")).toBeTruthy();
    expect(screen.getByText("count")).toBeTruthy();
  });

  it("calls onConfirm with the entered values when the user submits", async () => {
    const onConfirm = vi.fn();
    render(
      <TestWrapper>
        <InputValuesModal
          open
          variables={sampleVariables}
          onCancel={vi.fn()}
          onConfirm={onConfirm}
        />
      </TestWrapper>
    );
    // Use getByLabelText — AntD Form.Item wires label={v.name} → htmlFor
    // on the label and cloneElement-injects id={v.name} on the direct child
    // input, so getByLabelText("custom") finds it. The input is rendered
    // directly as a child of Form.Item (no wrapper component) so the
    // cloneElement reaches it.
    const customInput = screen.getByLabelText("custom") as HTMLInputElement;
    fireEvent.change(customInput, { target: { value: "hello" } });
    // Click the "确定" (OK) button. AntD autoInsertSpace renders this as
    // "确 定" (with space), so use getByRole with a regex to find by name.
    fireEvent.click(screen.getByRole("button", { name: /确\s*定/ }));
    await waitFor(() => {
      expect(onConfirm).toHaveBeenCalledTimes(1);
    });
    const arg = onConfirm.mock.calls[0][0];
    expect(arg).toMatchObject({ custom: "hello" });
  });

  it("calls onCancel when the user clicks 取消", () => {
    const onCancel = vi.fn();
    render(
      <TestWrapper>
        <InputValuesModal
          open
          variables={sampleVariables}
          onCancel={onCancel}
          onConfirm={vi.fn()}
        />
      </TestWrapper>
    );
    // AntD's autoInsertSpace inserts a space between adjacent Chinese
    // characters in button text ("取 消"). Use getByRole with a regex
    // matcher to find the button by name, robust to that whitespace.
    fireEvent.click(screen.getByRole("button", { name: /取\s*消/ }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
