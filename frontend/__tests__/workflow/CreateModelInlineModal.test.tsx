import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigProvider } from "antd";
import { CreateModelInlineModal } from "@/components/workflow/CreateModelInlineModal";

vi.mock("@/services/models", () => ({
  modelsApi: {
    create: vi.fn(),
  },
}));

import { modelsApi } from "@/services/models";

// Disable AntD's auto-insert-space-in-button for Chinese characters in tests.
// Otherwise "取消" → "取 消", "创建" → "创 建", and getByRole({name: /取消/i}) fails.
const TestWrapper = ({ children }: { children: React.ReactNode }) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{children}</ConfigProvider>
);

describe("CreateModelInlineModal", () => {
  const defaultProps = {
    open: true,
    initialModelName: "glm-4",
    onCancel: vi.fn(),
    onCreated: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("pre-fills model_name with initialModelName", () => {
    render(<CreateModelInlineModal {...defaultProps} />, { wrapper: TestWrapper });
    const modelNameInput = screen.getByLabelText(/模型名称/i) as HTMLInputElement;
    expect(modelNameInput.value).toBe("glm-4");
  });

  it("calls modelsApi.create with the form values on submit", async () => {
    const user = userEvent.setup();
    (modelsApi.create as any).mockResolvedValue({
      data: { code: 200, data: { id: 99, model_name: "glm-4", model_type: "zhipu" } },
    });
    render(<CreateModelInlineModal {...defaultProps} />, { wrapper: TestWrapper });
    // Fill in display name
    fireEvent.change(screen.getByLabelText(/配置名称/i), {
      target: { value: "Zhipu Test" },
    });
    // Pick the zhipu provider
    await user.click(screen.getByLabelText(/Provider/i));
    await user.click(await screen.findByText(/智谱 GLM/));
    // Fill in base_url and api_key
    fireEvent.change(screen.getByLabelText(/Base URL/i), {
      target: { value: "https://api.zhipu.example" },
    });
    fireEvent.change(screen.getByLabelText(/API Key/i), {
      target: { value: "secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: /创建/i }));
    await waitFor(() => {
      expect(modelsApi.create).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Zhipu Test",
          model_name: "glm-4",
          model_type: "zhipu",
          base_url: "https://api.zhipu.example",
          api_key: "secret",
        })
      );
    });
  });

  it("calls onCreated with the new id on success", async () => {
    const user = userEvent.setup();
    (modelsApi.create as any).mockResolvedValue({
      data: { code: 200, data: { id: 99, model_name: "glm-4", model_type: "zhipu" } },
    });
    render(<CreateModelInlineModal {...defaultProps} />, { wrapper: TestWrapper });
    fireEvent.change(screen.getByLabelText(/配置名称/i), { target: { value: "Zhipu Test" } });
    await user.click(screen.getByLabelText(/Provider/i));
    await user.click(await screen.findByText(/智谱 GLM/));
    fireEvent.change(screen.getByLabelText(/Base URL/i), { target: { value: "https://x" } });
    fireEvent.change(screen.getByLabelText(/API Key/i), { target: { value: "k" } });
    fireEvent.click(screen.getByRole("button", { name: /创建/i }));
    await waitFor(() => {
      expect(defaultProps.onCreated).toHaveBeenCalledWith(
        expect.objectContaining({ id: 99, model_name: "glm-4" })
      );
    });
  });

  it("calls onCancel when Cancel is clicked", () => {
    render(<CreateModelInlineModal {...defaultProps} />, { wrapper: TestWrapper });
    fireEvent.click(screen.getByRole("button", { name: /取消/i }));
    expect(defaultProps.onCancel).toHaveBeenCalled();
  });
});
