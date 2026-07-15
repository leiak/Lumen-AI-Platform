import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ModelSelector } from "@/components/workflow/ModelSelector";

vi.mock("@/services/models", () => ({
  modelsApi: {
    list: vi.fn(),
    create: vi.fn(),
  },
}));

import { modelsApi } from "@/services/models";

const MOCK_MODELS = [
  { id: 1, name: "智谱生产", model_type: "zhipu", model_name: "glm-4", is_active: true },
  { id: 2, name: "OpenAI GPT-4o", model_type: "openai", model_name: "gpt-4o", is_active: true },
];

describe("ModelSelector", () => {
  const defaultProps = {
    value: undefined as { model_config_id: number | null; model_name: string } | undefined,
    onChange: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
    (modelsApi.list as any).mockResolvedValue({
      data: { code: 200, data: MOCK_MODELS, total: 2, page: 1, page_size: 10 },
    });
  });

  it("renders options from modelsApi.list", async () => {
    render(<ModelSelector {...defaultProps} />);
    // Open the dropdown
    const select = screen.getByRole("combobox");
    fireEvent.mouseDown(select);
    await waitFor(() => {
      expect(screen.getByText("智谱生产")).toBeInTheDocument();
      expect(screen.getByText("OpenAI GPT-4o")).toBeInTheDocument();
    });
  });

  it("calls onChange with the picked model", async () => {
    render(<ModelSelector {...defaultProps} />);
    fireEvent.mouseDown(screen.getByRole("combobox"));
    await waitFor(() => screen.getByText("智谱生产"));
    fireEvent.click(screen.getByText("智谱生产"));
    await waitFor(() => {
      expect(defaultProps.onChange).toHaveBeenCalledWith(
        expect.objectContaining({ model_config_id: 1, model_name: "glm-4" })
      );
    });
  });

  it("shows the missing yellow entry when value references a deleted config", async () => {
    render(
      <ModelSelector
        {...defaultProps}
        value={{ model_config_id: 999, model_name: "old-glm" }}
      />
    );
    const select = screen.getByRole("combobox");
    fireEvent.mouseDown(select);
    await waitFor(() => {
      expect(screen.getByText(/原配置已失效/)).toBeInTheDocument();
    });
  });

  it("shows an error Alert when modelsApi.list fails", async () => {
    (modelsApi.list as any).mockRejectedValue(new Error("network"));
    render(<ModelSelector {...defaultProps} />);
    await waitFor(() => {
      expect(screen.getByText(/模型管理数据加载失败/i)).toBeInTheDocument();
    });
  });

  // ---- Auto-heal tests (M33-bug: 老工作流 reload 时 model_name 缺失) ----

  it("auto-heals value with model_config_id but missing model_name", async () => {
    render(
      <ModelSelector
        {...defaultProps}
        value={{ model_config_id: 1, model_name: "" }}
      />
    );
    await waitFor(() =>
      expect(defaultProps.onChange).toHaveBeenCalledWith(
        expect.objectContaining({ model_config_id: 1, model_name: "glm-4" })
      )
    );
  });

  it("does not auto-heal when value already has model_name", async () => {
    render(
      <ModelSelector
        {...defaultProps}
        value={{ model_config_id: 1, model_name: "glm-4" }}
      />
    );
    // 等 models 加载完,再等额外的 tick 确保 effect 都跑过
    await waitFor(() => screen.getByRole("combobox"));
    await new Promise((r) => setTimeout(r, 50));
    expect(defaultProps.onChange).not.toHaveBeenCalled();
  });

  it("does not auto-heal when model_config_id references deleted/inactive model", async () => {
    render(
      <ModelSelector
        {...defaultProps}
        value={{ model_config_id: 999, model_name: "" }}
      />
    );
    await waitFor(() => screen.getByText(/原配置已失效/));
    await new Promise((r) => setTimeout(r, 50));
    expect(defaultProps.onChange).not.toHaveBeenCalled();
  });
});
