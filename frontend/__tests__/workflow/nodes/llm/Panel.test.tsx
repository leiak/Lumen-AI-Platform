import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { LLMPanel } from "@/components/workflow/nodes/llm/Panel";

// Mock ModelSelector so we don't hit the network
vi.mock("@/components/workflow/ModelSelector", () => ({
  ModelSelector: ({ onChange }: any) => (
    <button data-testid="model-selector" onClick={() => onChange({ model_config_id: 1, model_name: "glm-4" })}>
      pick-model
    </button>
  ),
}));

// Mock skills service so the panel's useEffect doesn't hit the network.
// Without this, every test run pollutes stderr with an AxiosError: Network Error
// (the panel swallows the throw in try/catch but logs to console.error).
const mockListInstalled = vi.fn();
vi.mock("@/services/skills", () => ({
  skillsApi: {
    listInstalled: (...args: any[]) => mockListInstalled(...args),
  },
}));

const baseNode = {
  id: "llm_1",
  type: "llm",
  position: { x: 0, y: 0 },
  config: { title: "LLM", prompt: "Hello" },
};

describe("LLMPanel", () => {
  beforeEach(() => {
    mockListInstalled.mockReset();
    mockListInstalled.mockResolvedValue({
      data: { code: 200, data: { data: [], total: 0, page: 1, page_size: 50 } },
    });
  });

  it("renders node name + prompt", () => {
    render(<LLMPanel node={baseNode} nodes={[baseNode]} edges={[]} onChange={() => {}} />);
    expect(screen.getByDisplayValue("LLM")).toBeTruthy();
    expect(screen.getByDisplayValue("Hello")).toBeTruthy();
  });

  it("updates config on name change (debounced 200ms)", async () => {
    const onChange = vi.fn();
    render(<LLMPanel node={baseNode} nodes={[baseNode]} edges={[]} onChange={onChange} />);
    const nameInput = screen.getByDisplayValue("LLM") as HTMLInputElement;
    // AntD Input is a controlled component; in jsdom, user.type after clear() is
    // unreliable (React re-renders the value back before subsequent keystrokes).
    // fireEvent.change mirrors the same contract: "input value is now X".
    fireEvent.change(nameInput, { target: { value: "MyLLM" } });
    // 收口-A: debounced onChange — wait up to 500ms for the
    // 200ms debounce to fire.
    await waitFor(() => expect(onChange).toHaveBeenCalled(), { timeout: 500 });
    const lastCall = onChange.mock.calls[onChange.mock.calls.length - 1][0];
    expect(lastCall.config.title).toBe("MyLLM");
  });

  it("updates model_config_id + model_name on ModelSelector change (debounced 200ms)", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<LLMPanel node={baseNode} nodes={[baseNode]} edges={[]} onChange={onChange} />);
    await user.click(screen.getByTestId("model-selector"));
    // 收口-A: debounced onChange — wait for the 200ms timer to fire.
    await waitFor(() => expect(onChange).toHaveBeenCalled(), { timeout: 500 });
    const lastCall = onChange.mock.calls[onChange.mock.calls.length - 1][0];
    expect(lastCall.config.model_config_id).toBe(1);
    expect(lastCall.config.model_name).toBe("glm-4");
  });

  it("renders AdvancedOptions collapse section with timeout input", async () => {
    const user = userEvent.setup();
    render(<LLMPanel node={baseNode} nodes={[baseNode]} edges={[]} onChange={() => {}} />);
    // AdvancedOptions 用 antd <Collapse>,label 是折叠头
    expect(screen.getByText("高级选项")).toBeInTheDocument();
    await user.click(screen.getByText("高级选项"));
    // AdvancedOptions 内层 Collapse 自带 "高级选项(错误处理 / 重试 / 超时)" label
    // 展开外层后,内层默认也是折叠的,需要再点一次才能看到 timeout
    await user.click(screen.getByText("高级选项(错误处理 / 重试 / 超时)"));
    expect(await screen.findByText("超时(秒)")).toBeInTheDocument();
  });

  it("propagates AdvancedOptions timeout to config (debounced 200ms)", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<LLMPanel node={baseNode} nodes={[baseNode]} edges={[]} onChange={onChange} />);
    await user.click(screen.getByText("高级选项"));
    await user.click(screen.getByText("高级选项(错误处理 / 重试 / 超时)"));
    // TimeoutInput 的 InputNumber placeholder 是 "默认 30 秒",跟 model 段
    // Temperature / Max Tokens 的 spinbutton 不冲突。
    const numInput = (await screen.findByPlaceholderText("默认 30 秒")) as HTMLInputElement;
    fireEvent.change(numInput, { target: { value: "90" } });
    await waitFor(() => expect(onChange).toHaveBeenCalled(), { timeout: 500 });
    const last = onChange.mock.calls[onChange.mock.calls.length - 1][0];
    expect(last.config.timeout).toBe(90);
  });
});
