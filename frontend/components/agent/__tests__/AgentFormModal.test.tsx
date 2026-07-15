import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ConfigProvider } from "antd";

// Mock the services module so component-under-test never makes real HTTP calls.
vi.mock("@/services/agent", () => ({
  agentApi: {
    create: vi.fn(),
    update: vi.fn(),
  },
  MEMORY_POLICIES: [
    { value: "sliding_window", label: "滑动窗口" },
    { value: "token_limit", label: "Token 限制" },
    { value: "semantic_compression", label: "语义压缩" },
    { value: "none", label: "不使用记忆" },
  ],
  TOOL_CHOICE_MODES: [
    { value: "auto", label: "自动 (Auto)" },
    { value: "required", label: "必须调用 (Required)" },
    { value: "none", label: "不调用工具 (None)" },
    { value: "specific", label: "指定工具 (Specific)" },
  ],
}));

// Mock the knowledge service so MultiKBSelector (transitively used by the form)
// doesn't make real HTTP calls.
vi.mock("@/services/knowledge", () => ({
  knowledgeApi: {
    list: vi.fn().mockResolvedValue({
      data: {
        code: 200,
        data: [
          { id: 10, name: "KB1", status: "active" },
          { id: 20, name: "KB2", status: "active" },
        ],
        total: 2,
        page: 1,
        page_size: 100,
      },
    }),
  },
}));

// Mock antd's message so we can assert success/error toasts.
vi.mock("antd", async () => {
  const actual = await vi.importActual<typeof import("antd")>("antd");
  return {
    ...actual,
    message: {
      success: vi.fn(),
      error: vi.fn(),
      warning: vi.fn(),
    },
  };
});

import { agentApi } from "@/services/agent";
import { AgentFormModal } from "@/components/agent/AgentFormModal";
import type { Agent } from "@/types/api";

const Wrapper = ({ children }: { children: React.ReactNode }) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{children}</ConfigProvider>
);

const baseModelConfigs = [
  {
    id: 1,
    name: "GPT-4o",
    model_type: "openai",
    model_name: "gpt-4o",
    is_active: true,
  } as any,
];

const makeAgent = (overrides: Partial<Agent> = {}): Agent =>
  ({
    id: 42,
    name: "helper",
    description: "desc",
    prompt_template: "You are {'{input}'}",
    model_name: "gpt-4o",
    temperature: 0,
    is_active: true,
    memory_policy: "sliding_window",
    memory_window_size: 20,
    memory_max_tokens: 4000,
    memory_compression: false,
    tool_choice: "auto",
    tool_choice_required: false,
    allowed_tools: [],
    tenant_id: 1,
    created_at: "2026-06-06T00:00:00",
    ...overrides,
  } as Agent);

describe("AgentFormModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(agentApi.create).mockResolvedValue({ data: { code: 200, data: makeAgent() } } as any);
    vi.mocked(agentApi.update).mockResolvedValue({ data: { code: 200, data: makeAgent() } } as any);
  });

  it("create mode: submitting calls agentApi.create, then onSubmitted", async () => {
    const onSubmitted = vi.fn();
    const onCancel = vi.fn();
    render(
      <AgentFormModal
        open
        mode="create"
        modelConfigs={baseModelConfigs}
        onCancel={onCancel}
        onSubmitted={onSubmitted}
      />,
      { wrapper: Wrapper }
    );

    // Fill required fields
    fireEvent.change(screen.getByPlaceholderText("请输入Agent名称"), {
      target: { value: "new-agent" },
    });
    fireEvent.change(screen.getByPlaceholderText(/请输入提示词模板/), {
      target: { value: "Be helpful. {'{input}'}" },
    });

    // Select the model (required field)
    fireEvent.mouseDown(screen.getByLabelText("模型"));
    fireEvent.click(screen.getByText("GPT-4o (openai - gpt-4o)"));

    // Submit
    fireEvent.click(screen.getByRole("button", { name: "创建" }));

    await waitFor(() => {
      expect(agentApi.create).toHaveBeenCalledTimes(1);
    });
    expect(agentApi.update).not.toHaveBeenCalled();
    expect(onSubmitted).toHaveBeenCalledTimes(1);
  });

  it("edit mode: initialValues pre-fill all fields and submit calls agentApi.update", async () => {
    const onSubmitted = vi.fn();
    const editing = makeAgent({
      id: 99,
      name: "to-edit",
      prompt_template: "old prompt {'{input}'}",
      memory_policy: "token_limit",
      memory_max_tokens: 8000,
      tool_choice: "specific",
      allowed_tools: ["web_search"],
    });

    render(
      <AgentFormModal
        open
        mode="edit"
        initialValues={editing}
        modelConfigs={baseModelConfigs}
        onCancel={vi.fn()}
        onSubmitted={onSubmitted}
      />,
      { wrapper: Wrapper }
    );

    // Name input pre-filled
    const nameInput = screen.getByPlaceholderText("请输入Agent名称") as HTMLInputElement;
    expect(nameInput.value).toBe("to-edit");

    // Submit (no field changes)
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(agentApi.update).toHaveBeenCalledTimes(1);
    });
    const [calledId, calledBody] = vi.mocked(agentApi.update).mock.calls[0];
    expect(calledId).toBe(99);
    expect(calledBody.name).toBe("to-edit");
    expect(calledBody.memory_policy).toBe("token_limit");
    expect(calledBody.tool_choice).toBe("specific");
    expect(calledBody.allowed_tools).toEqual(["web_search"]);
    expect(calledBody.memory_max_tokens).toBe(8000);
    expect(agentApi.create).not.toHaveBeenCalled();
    expect(onSubmitted).toHaveBeenCalledTimes(1);
  });

  it("edit mode: switching memory_policy to sliding_window shows memory_window_size input", async () => {
    const editing = makeAgent({
      memory_policy: "token_limit",
      memory_max_tokens: 8000,
    });
    render(
      <AgentFormModal
        open
        mode="edit"
        initialValues={editing}
        modelConfigs={baseModelConfigs}
        onCancel={vi.fn()}
        onSubmitted={vi.fn()}
      />,
      { wrapper: Wrapper }
    );

    // token_limit initial state: max_tokens label visible
    expect(screen.getByText("最大 Token 数")).toBeTruthy();

    // Open the memory_policy select via the form label
    const policySelect = screen.getByLabelText("策略");
    fireEvent.mouseDown(policySelect);

    // Click the "滑动窗口" option
    const option = screen.getByText("滑动窗口");
    fireEvent.click(option);

    // After re-render, memory_window_size label should be visible, max_tokens gone
    await waitFor(() => {
      expect(screen.getByText("窗口大小 (轮)")).toBeTruthy();
    });
    expect(screen.queryByText("最大 Token 数")).toBeNull();
  });

  it("cancel button triggers onCancel", () => {
    const onCancel = vi.fn();
    render(
      <AgentFormModal
        open
        mode="create"
        modelConfigs={baseModelConfigs}
        onCancel={onCancel}
        onSubmitted={vi.fn()}
      />,
      { wrapper: Wrapper }
    );
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(agentApi.create).not.toHaveBeenCalled();
  });

  // === M21 T17: 知识库 (Knowledge Base) 分区 ===

  it("edit mode: KB section pre-fills with knowledge_bases + kb_retrieval_config", async () => {
    const editing = makeAgent({
      knowledge_bases: [
        { id: 10, name: "KB1", status: "active" },
        { id: 20, name: "KB2", status: "active" },
      ],
      kb_retrieval_config: { top_k: 5, rrf_k: 30 },
    });

    render(
      <AgentFormModal
        open
        mode="edit"
        initialValues={editing}
        modelConfigs={baseModelConfigs}
        onCancel={vi.fn()}
        onSubmitted={vi.fn()}
      />,
      { wrapper: Wrapper }
    );

    // 验证 KB 分区 Divider 出现
    expect(screen.getByText(/知识库 \(Knowledge Base\)/)).toBeTruthy();

    // 验证 "绑定的知识库" label 出现
    expect(screen.getByText("绑定的知识库")).toBeTruthy();

    // 验证 "检索设置" label 出现
    expect(screen.getByText("检索设置")).toBeTruthy();

    // 验证 KbRetrievalConfigFields 的 top_k 输入预填(从 5 而不是默认 3)
    // Inner Form.Item 没 name,label 不通过 for 关联控件,改用 querySelector 抓 InputNumber
    await waitFor(() => {
      const inputs = document.querySelectorAll<HTMLInputElement>(
        'input[role="spinbutton"][aria-valuenow="5"]'
      );
      expect(inputs.length).toBeGreaterThan(0);
    });
  });

  it("create mode: submit payload includes knowledge_base_ids and kb_retrieval_config", async () => {
    render(
      <AgentFormModal
        open
        mode="create"
        modelConfigs={baseModelConfigs}
        onCancel={vi.fn()}
        onSubmitted={vi.fn()}
      />,
      { wrapper: Wrapper }
    );

    // 填必填字段
    fireEvent.change(screen.getByPlaceholderText("请输入Agent名称"), {
      target: { value: "kb-agent" },
    });
    fireEvent.change(screen.getByPlaceholderText(/请输入提示词模板/), {
      target: { value: "Use KB. {'{input}'}" },
    });

    // 选模型
    fireEvent.mouseDown(screen.getByLabelText("模型"));
    fireEvent.click(screen.getByText("GPT-4o (openai - gpt-4o)"));

    // 提交 —— KB 字段都是默认值 (空 [] + { top_k: 3, rrf_k: 30 }),
    // 我们验证默认值会出现在 payload 里
    fireEvent.click(screen.getByRole("button", { name: "创建" }));

    await waitFor(() => {
      expect(agentApi.create).toHaveBeenCalledTimes(1);
    });

    const payload = vi.mocked(agentApi.create).mock.calls[0][0];
    // 关键 assertion:payload 包含 KB 字段(默认值)
    expect(payload.knowledge_base_ids).toEqual([]);
    expect(payload.kb_retrieval_config).toEqual({ top_k: 3, rrf_k: 30 });
  });
});
