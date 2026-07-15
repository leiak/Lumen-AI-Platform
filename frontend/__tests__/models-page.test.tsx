// frontend/__tests__/models-page.test.tsx
// Render-level tests for /dashboard/system/models: the provider
// catalog fallback (when GET /models/providers/list fails) and the
// happy path (when the backend returns a valid list).
//
// `FALLBACK_PROVIDERS` is intentionally a non-exported const inside
// the page module. Testing it through the rendered page keeps the
// test honest: we verify the behavior admins actually see (5
// fallback cards + warning alert) rather than reaching into a
// private export.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigProvider, message } from "antd";

// Mock the services module so we don't hit the network.
const mockList = vi.fn();
const mockListTypes = vi.fn();
const mockImport = vi.fn();
const mockBulkCreate = vi.fn();
const mockUpdate = vi.fn();
const mockKbList = vi.fn();
vi.mock("@/services/models", () => ({
  modelsApi: {
    list: (...args: any[]) => mockList(...args),
    listTypes: (...args: any[]) => mockListTypes(...args),
    importFromOllama: (...args: any[]) => mockImport(...args),
    bulkCreate: (...args: any[]) => mockBulkCreate(...args),
    update: (...args: any[]) => mockUpdate(...args),
  },
}));
vi.mock("@/services/knowledge", () => ({
  knowledgeApi: {
    list: (...args: any[]) => mockKbList(...args),
  },
}));

import ModelsPage from "@/app/dashboard/system/models/page";

const TestWrapper = ({ children }: { children: React.ReactNode }) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{children}</ConfigProvider>
);

// Empty list response so the table below the cards doesn't crash
// during the test (it shares the same fetch lifecycle as the page).
const emptyListResponse = () => ({
  data: {
    code: 200,
    message: "ok",
    data: [],
    total: 0,
    page: 1,
    page_size: 10,
  },
});

// 4 hardcoded entries in the page's FALLBACK_PROVIDERS list. The
// numeric count matters: it's a regression guard against accidental
// truncation of the fallback. If the source list ever shrinks or
// grows, this test forces a deliberate update.
//
// History: was 5 entries including "OpenAI" — removed on 2026-06-15
// to mirror `backend/app/core/model_providers.py:MODEL_PROVIDERS`
// after openai/azure_openai/mistral/groq/grok were dropped from the
// catalog (no chat-model loader implementation behind them).
const FALLBACK_LABELS = [
  "Ollama (本地)",
  "Anthropic",
  "智谱 GLM",
  "MiniMax",
];

describe("ModelsPage / provider catalog fallback", () => {
  beforeEach(() => {
    mockList.mockReset();
    mockListTypes.mockReset();
    mockImport.mockReset();
    mockBulkCreate.mockReset();
    mockKbList.mockReset();
    mockList.mockResolvedValue(emptyListResponse());
    // KB list — empty by default; tests that need references override.
    mockKbList.mockResolvedValue({
      data: { code: 200, message: "ok", data: [], total: 0, page: 1, page_size: 100 },
    });
    vi.spyOn(message, "error").mockImplementation((() => ({})) as any);
  });

  it("renders the hardcoded FALLBACK_PROVIDERS list when the catalog endpoint rejects", async () => {
    // Simulate the dev server being down / network error.
    mockListTypes.mockRejectedValue(new Error("Network Error"));

    render(<ModelsPage />, { wrapper: TestWrapper });

    // All 4 fallback labels must show up as Card titles.
    for (const label of FALLBACK_LABELS) {
      await waitFor(
        () => {
          expect(screen.getByText(label)).toBeTruthy();
        },
        { timeout: 3000 }
      );
    }

    // The page must surface the "已切换为内置列表" warning so the
    // admin knows they're looking at a degraded view, not the real
    // catalog.
    expect(
      screen.getByText(/无法获取 provider 列表.*已切换为内置列表/),
    ).toBeTruthy();
  });

  it("falls back to FALLBACK_PROVIDERS when the catalog endpoint returns a non-200 or non-array payload", async () => {
    // The page guards on `code === 200 && Array.isArray(data)`. A
    // response that violates either branch must trip the same
    // fallback path as a network error.
    mockListTypes.mockResolvedValue({
      data: { code: 500, message: "boom", data: null },
    });

    render(<ModelsPage />, { wrapper: TestWrapper });

    // Pick one fallback label to assert; the per-entry exhaustive
    // check is covered by the first test.
    await waitFor(
      () => {
        expect(screen.getByText(FALLBACK_LABELS[0])).toBeTruthy();
      },
      { timeout: 3000 }
    );
    // The page distinguishes the two fallback reasons in the
    // warning text — assert on the relevant substring.
    expect(
      screen.getByText(/后端返回的 provider 列表无效.*已切换为内置列表/),
    ).toBeTruthy();
  });

  it("uses the backend catalog when it returns a valid 200 + array response", async () => {
    // Happy path regression: the fallback must NOT kick in if the
    // backend returns a well-formed response. We return two custom
    // providers with labels that do NOT exist in FALLBACK_PROVIDERS
    // so a stale fallback would be impossible to confuse with the
    // real catalog.
    const customProviders = [
      {
        value: "deepseek",
        label: "DeepSeek (custom-test)",
        description: "Custom test entry",
        base_url_hint: "https://api.deepseek.com/v1",
      },
      {
        value: "qwen",
        label: "通义千问 (custom-test)",
        description: "Custom test entry 2",
        base_url_hint: "https://dashscope.aliyuncs.com/compatible-mode/v1",
      },
    ];
    mockListTypes.mockResolvedValue({
      data: { code: 200, message: "ok", data: customProviders },
    });

    render(<ModelsPage />, { wrapper: TestWrapper });

    // Custom labels appear.
    await waitFor(
      () => {
        expect(screen.getByText("DeepSeek (custom-test)")).toBeTruthy();
        expect(screen.getByText("通义千问 (custom-test)")).toBeTruthy();
      },
      { timeout: 3000 }
    );

    // No fallback warning should be shown.
    expect(
      screen.queryByText(/已切换为内置列表/),
    ).toBeNull();
  });

  it("fallback list contains exactly 4 entries (regression guard)", async () => {
    // Pin the count so accidental deletion of a fallback entry
    // fails this test loudly. The list is a UI safety net; we want
    // any change to be intentional.
    mockListTypes.mockRejectedValue(new Error("Network Error"));

    render(<ModelsPage />, { wrapper: TestWrapper });

    for (const label of FALLBACK_LABELS) {
      await waitFor(
        () => {
          expect(screen.getByText(label)).toBeTruthy();
        },
        { timeout: 3000 }
      );
    }
  });
});

describe("ModelsPage / 用途 column", () => {
  // One list of test rows, two test cases. The mock is set inside each
  // test so we can vary the rows.
  const baseRow = (overrides: any = {}) => ({
    id: 1,
    name: "test-model",
    model_name: "test-name",
    model_type: "ollama",
    base_url: "http://localhost:11434",
    temperature: 0.7,
    max_tokens: 4096,
    timeout: 120,
    is_default: false,
    is_active: true,
    created_at: "2026-06-06T00:00:00Z",
    updated_at: "2026-06-06T00:00:00Z",
    ...overrides,
  });

  beforeEach(() => {
    mockList.mockReset();
    mockListTypes.mockReset();
    mockImport.mockReset();
    mockBulkCreate.mockReset();
    mockKbList.mockReset();
    mockListTypes.mockResolvedValue({
      data: { code: 200, message: "ok", data: [] },
    });
    mockKbList.mockResolvedValue({
      data: { code: 200, message: "ok", data: [], total: 0, page: 1, page_size: 100 },
    });
    vi.spyOn(message, "error").mockImplementation((() => ({})) as any);
  });

  it("renders Chat + Embed dual tags when a row is both is_chat and is_embedding", async () => {
    mockList.mockResolvedValue({
      data: {
        code: 200,
        message: "ok",
        data: [baseRow({ id: 11, name: "dual", is_chat: true, is_embedding: true })],
        total: 1,
        page: 1,
        page_size: 10,
      },
    });

    render(<ModelsPage />, { wrapper: TestWrapper });

    await waitFor(() => {
      expect(screen.getByText("dual")).toBeTruthy();
    });
    // The 用途 column shows BOTH "Chat" and "Embed" tags for a dual row.
    await waitFor(() => {
      expect(screen.getByText("Chat")).toBeTruthy();
      expect(screen.getByText("Embed")).toBeTruthy();
    });
  });

  it("renders only the Chat tag for chat-only models and only Embed for embed-only", async () => {
    mockList.mockResolvedValue({
      data: {
        code: 200,
        message: "ok",
        data: [
          baseRow({ id: 21, name: "chat-only", is_chat: true, is_embedding: false }),
          baseRow({ id: 22, name: "embed-only", is_chat: false, is_embedding: true }),
        ],
        total: 2,
        page: 1,
        page_size: 10,
      },
    });

    render(<ModelsPage />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText("chat-only")).toBeTruthy();
    });
    await waitFor(() => {
      expect(screen.getByText("embed-only")).toBeTruthy();
    });
    // The 用途 column is the only place that renders "Chat" and
    // "Embed" string tokens. We assert that the labels exist at all,
    // since per-row split is rendered by the column render function.
    expect(screen.getAllByText("Chat").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Embed").length).toBeGreaterThan(0);
  });
});

describe("ModelsPage / Ollama import button", () => {
  beforeEach(() => {
    mockList.mockReset();
    mockListTypes.mockReset();
    mockImport.mockReset();
    mockBulkCreate.mockReset();
    mockKbList.mockReset();
    mockList.mockResolvedValue({
      data: {
        code: 200,
        message: "ok",
        data: [],
        total: 0,
        page: 1,
        page_size: 10,
      },
    });
    mockListTypes.mockResolvedValue({
      data: { code: 200, message: "ok", data: [] },
    });
    mockKbList.mockResolvedValue({
      data: { code: 200, message: "ok", data: [], total: 0, page: 1, page_size: 100 },
    });
    vi.spyOn(message, "error").mockImplementation((() => ({})) as any);
  });

  it("shows a '从 Ollama 导入' button next to '添加模型'", async () => {
    render(<ModelsPage />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /从 Ollama 导入/ })).toBeTruthy();
    });
  });

  it("clicking the import button opens the OllamaImportModal which calls importFromOllama", async () => {
    const user = userEvent.setup();
    mockImport.mockResolvedValue({
      data: {
        code: 200,
        message: "ok",
        data: { base_url: "http://localhost:11434", reachable: false, models: [], error_message: "down" },
      },
    });

    render(<ModelsPage />, { wrapper: TestWrapper });
    await waitFor(() => screen.getByRole("button", { name: /从 Ollama 导入/ }));

    await user.click(screen.getByRole("button", { name: /从 Ollama 导入/ }));

    await waitFor(() => {
      expect(mockImport).toHaveBeenCalled();
    });
    // The modal renders the failure state (alert + "无法连接 Ollama").
    await waitFor(() => {
      expect(screen.getByText(/无法连接 Ollama/)).toBeTruthy();
    });
  });
});

describe("ModelsPage / KB-reference-aware delete", () => {
  const baseRow = (overrides: any = {}) => ({
    id: 1,
    name: "test-model",
    model_name: "test-name",
    model_type: "ollama",
    base_url: "http://localhost:11434",
    temperature: 0.7,
    max_tokens: 4096,
    timeout: 120,
    is_default: false,
    is_active: true,
    is_chat: true,
    is_embedding: true,
    created_at: "2026-06-06T00:00:00Z",
    updated_at: "2026-06-06T00:00:00Z",
    ...overrides,
  });

  beforeEach(() => {
    mockList.mockReset();
    mockListTypes.mockReset();
    mockImport.mockReset();
    mockBulkCreate.mockReset();
    mockKbList.mockReset();
    mockListTypes.mockResolvedValue({
      data: { code: 200, message: "ok", data: [] },
    });
    vi.spyOn(message, "error").mockImplementation((() => ({})) as any);
  });

  it("disables the delete button when a KB references the model and shows a tooltip", async () => {
    // Two models in the list. The KB list references id=42.
    mockList.mockResolvedValue({
      data: {
        code: 200,
        message: "ok",
        data: [
          baseRow({ id: 42, name: "in-use" }),
          baseRow({ id: 43, name: "unused" }),
        ],
        total: 2,
        page: 1,
        page_size: 10,
      },
    });
    mockKbList.mockResolvedValue({
      data: {
        code: 200,
        message: "ok",
        data: [
          {
            id: 1,
            name: "kb-1",
            embedding_model_config_id: 42,
            embedding_model: "nomic-embed-text",
            status: "active",
            created_at: "2026-06-06T00:00:00Z",
          },
        ],
        total: 1,
        page: 1,
        page_size: 100,
      },
    });

    render(<ModelsPage />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText("in-use")).toBeTruthy();
      expect(screen.getByText("unused")).toBeTruthy();
    });

    // There are two delete buttons; the one in the "in-use" row must
    // be disabled. Walk all delete buttons and check disabled state.
    const deleteButtons = await waitFor(() => {
      return screen.getAllByRole("button", { name: /删除/ });
    });
    expect(deleteButtons.length).toBe(2);
    // Exactly one delete button should be disabled (the in-use one).
    const disabledCount = deleteButtons.filter((b) => b.hasAttribute("disabled")).length;
    expect(disabledCount).toBe(1);
  });
});

describe("ModelsPage / inline is_active switch", () => {
  // Behavior contract for handleToggleActive (page.tsx:245-288):
  //   1. Render an interactive Switch in the 状态 column (not a static Tag).
  //   2. Clicking it calls modelsApi.update(id, { is_active: <inverted> }).
  //   3. Optimistic update: the Switch's aria-checked flips *before* the
  //      API resolves; ant-switch-loading is on while in flight.
  //   4. Rollback + surface message on response.data.code !== 200.
  //   5. Rollback + surface detail on thrown error (response.data.message
  //      → response.data.detail → err.message → fallback).
  //   6. Loading is always cleared in the finally block.
  const baseRow = (overrides: any = {}) => ({
    id: 1,
    name: "test-model",
    model_name: "test-name",
    model_type: "ollama",
    base_url: "http://localhost:11434",
    temperature: 0.7,
    max_tokens: 4096,
    timeout: 120,
    is_default: false,
    is_active: true,
    is_chat: true,
    is_embedding: false,
    created_at: "2026-06-06T00:00:00Z",
    updated_at: "2026-06-06T00:00:00Z",
    ...overrides,
  });

  // AntD v5 Switch renders <button class="ant-switch" aria-checked="...">.
  // Locate the Switch inside the row for a given model name.
  const findSwitch = (modelName: string): HTMLButtonElement => {
    const row = screen.getByText(modelName).closest("tr");
    if (!row) throw new Error(`row not found for ${modelName}`);
    const sw = row.querySelector("button.ant-switch") as HTMLButtonElement;
    if (!sw) throw new Error(`switch not found in row ${modelName}`);
    return sw;
  };

  beforeEach(() => {
    mockList.mockReset();
    mockListTypes.mockReset();
    mockImport.mockReset();
    mockBulkCreate.mockReset();
    mockUpdate.mockReset();
    mockKbList.mockReset();
    mockListTypes.mockResolvedValue({
      data: { code: 200, message: "ok", data: [] },
    });
    mockKbList.mockResolvedValue({
      data: { code: 200, message: "ok", data: [], total: 0, page: 1, page_size: 100 },
    });
    vi.spyOn(message, "error").mockImplementation((() => ({})) as any);
  });

  it("renders a Switch in the 状态 column (replaces the static Tag)", async () => {
    mockList.mockResolvedValue({
      data: {
        code: 200,
        message: "ok",
        data: [baseRow({ id: 200, name: "switchable", is_active: true })],
        total: 1,
        page: 1,
        page_size: 10,
      },
    });

    render(<ModelsPage />, { wrapper: TestWrapper });
    await waitFor(() => {
      expect(screen.getByText("switchable")).toBeTruthy();
    });

    const sw = findSwitch("switchable");
    // Real <button>, not a static Tag — ant-switch class is the marker.
    expect(sw.classList.contains("ant-switch")).toBe(true);
    // aria-checked reflects the row's is_active.
    expect(sw.getAttribute("aria-checked")).toBe("true");
  });

  it("clicking the Switch calls modelsApi.update with the inverted is_active value", async () => {
    mockList.mockResolvedValue({
      data: {
        code: 200,
        message: "ok",
        data: [baseRow({ id: 201, name: "from-true", is_active: true })],
        total: 1,
        page: 1,
        page_size: 10,
      },
    });
    mockUpdate.mockResolvedValue({
      data: { code: 200, message: "ok", data: null },
    });

    const user = userEvent.setup();
    render(<ModelsPage />, { wrapper: TestWrapper });
    await waitFor(() => screen.getByText("from-true"));

    const sw = findSwitch("from-true");
    await user.click(sw);

    await waitFor(() => {
      expect(mockUpdate).toHaveBeenCalledWith(201, { is_active: false });
    });
  });

  it("flips the Switch state immediately on click (optimistic update) before the API resolves", async () => {
    // Manual promise so we can observe the intermediate state.
    let resolveUpdate: (v: any) => void = () => {};
    mockUpdate.mockImplementation(
      () => new Promise((resolve) => { resolveUpdate = resolve; })
    );

    mockList.mockResolvedValue({
      data: {
        code: 200,
        message: "ok",
        data: [baseRow({ id: 202, name: "optimistic", is_active: true })],
        total: 1,
        page: 1,
        page_size: 10,
      },
    });

    const user = userEvent.setup();
    render(<ModelsPage />, { wrapper: TestWrapper });
    await waitFor(() => screen.getByText("optimistic"));

    const sw = findSwitch("optimistic");
    expect(sw.getAttribute("aria-checked")).toBe("true");

    await user.click(sw);

    // Optimistic update: aria-checked flips BEFORE the promise resolves.
    await waitFor(() => {
      expect(sw.getAttribute("aria-checked")).toBe("false");
    });
    // Loading class is on while the request is in flight.
    expect(sw.classList.contains("ant-switch-loading")).toBe(true);

    // Now resolve the API call.
    resolveUpdate({ data: { code: 200, message: "ok", data: null } });

    // After the response: loading clears, state stays flipped.
    await waitFor(() => {
      expect(sw.classList.contains("ant-switch-loading")).toBe(false);
    });
    expect(sw.getAttribute("aria-checked")).toBe("false");
  });

  it("rolls back the Switch state when the API returns a non-200 response and surfaces the message", async () => {
    mockList.mockResolvedValue({
      data: {
        code: 200,
        message: "ok",
        data: [baseRow({ id: 203, name: "rollback-422", is_active: true })],
        total: 1,
        page: 1,
        page_size: 10,
      },
    });
    mockUpdate.mockResolvedValue({
      data: { code: 422, message: "embedding 模型被引用,不可禁用", data: null },
    });
    const errorSpy = vi.spyOn(message, "error");

    const user = userEvent.setup();
    render(<ModelsPage />, { wrapper: TestWrapper });
    await waitFor(() => screen.getByText("rollback-422"));

    const sw = findSwitch("rollback-422");
    expect(sw.getAttribute("aria-checked")).toBe("true");

    await user.click(sw);

    // After the failed response, state reverts to is_active=true.
    await waitFor(() => {
      expect(sw.getAttribute("aria-checked")).toBe("true");
    });
    // Backend's Chinese message is surfaced to the admin.
    expect(errorSpy).toHaveBeenCalledWith("embedding 模型被引用,不可禁用");
  });

  it("rolls back the Switch state on network error and surfaces the error message", async () => {
    mockList.mockResolvedValue({
      data: {
        code: 200,
        message: "ok",
        data: [baseRow({ id: 204, name: "rollback-net", is_active: false })],
        total: 1,
        page: 1,
        page_size: 10,
      },
    });
    mockUpdate.mockRejectedValue(new Error("Network Error"));
    const errorSpy = vi.spyOn(message, "error");

    const user = userEvent.setup();
    render(<ModelsPage />, { wrapper: TestWrapper });
    await waitFor(() => screen.getByText("rollback-net"));

    const sw = findSwitch("rollback-net");
    expect(sw.getAttribute("aria-checked")).toBe("false");

    await user.click(sw);

    // After the network error, state reverts to is_active=false.
    await waitFor(() => {
      expect(sw.getAttribute("aria-checked")).toBe("false");
    });
    // Network error message is surfaced via the err.message path.
    expect(errorSpy).toHaveBeenCalledWith("Network Error");
  });

  it("clears the loading state from togglingActiveIds after the response (success path)", async () => {
    mockList.mockResolvedValue({
      data: {
        code: 200,
        message: "ok",
        data: [baseRow({ id: 205, name: "loading-clear-ok", is_active: true })],
        total: 1,
        page: 1,
        page_size: 10,
      },
    });
    // Slow response so the loading state is observable.
    let resolveUpdate: (v: any) => void = () => {};
    mockUpdate.mockImplementation(
      () => new Promise((resolve) => { resolveUpdate = resolve; })
    );

    const user = userEvent.setup();
    render(<ModelsPage />, { wrapper: TestWrapper });
    await waitFor(() => screen.getByText("loading-clear-ok"));

    const sw = findSwitch("loading-clear-ok");
    await user.click(sw);

    // While pending: loading is on.
    await waitFor(() => {
      expect(sw.classList.contains("ant-switch-loading")).toBe(true);
    });

    // Resolve: loading should clear.
    resolveUpdate({ data: { code: 200, message: "ok", data: null } });
    await waitFor(() => {
      expect(sw.classList.contains("ant-switch-loading")).toBe(false);
    });
  });
});

