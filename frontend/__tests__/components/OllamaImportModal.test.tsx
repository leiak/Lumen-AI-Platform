import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigProvider } from "antd";

const mockImport = vi.fn();
const mockBulkCreate = vi.fn();
vi.mock("@/services/models", () => ({
  modelsApi: {
    importFromOllama: (...args: any[]) => mockImport(...args),
    bulkCreate: (...args: any[]) => mockBulkCreate(...args),
  },
}));

import OllamaImportModal from "@/components/OllamaImportModal";

const TestWrap = ({ children }: { children: React.ReactNode }) => (
  <ConfigProvider button={{ autoInsertSpace: false }}>{children}</ConfigProvider>
);

const okImport = (data: any) => ({ data: { code: 200, message: "ok", data } });

describe("OllamaImportModal", () => {
  const defaultProps = {
    open: true,
    onClose: vi.fn(),
    onSuccess: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows an error Alert and hides the table when Ollama is unreachable", async () => {
    mockImport.mockResolvedValue(
      okImport({
        base_url: "http://localhost:11434",
        reachable: false,
        models: [],
        error_message: "ConnectError: connection refused",
      })
    );
    render(<OllamaImportModal {...defaultProps} />, { wrapper: TestWrap });
    await waitFor(() => {
      // The Alert renders the error_message we mocked.
      expect(
        screen.getByText(/connection refused/i)
      ).toBeTruthy();
    });
    // Table rows must not appear when unreachable.
    expect(screen.queryByText(/nomic-embed-text/)).toBeNull();
  });

  it("fetches importFromOllama on open and renders a row per model", async () => {
    mockImport.mockResolvedValue(
      okImport({
        base_url: "http://localhost:11434",
        reachable: true,
        models: [
          {
            name: "nomic-embed-text:latest",
            size: 274302336,
            modified_at: "2026-05-01T00:00:00Z",
            family: "nomic-bert",
            capabilities: ["embedding"],
            is_embedding_capable: true,
            is_chat_capable: false,
            exists_in_db: false,
            existing_config_id: null,
          },
          {
            name: "qwen2.5:7b",
            size: 4680000000,
            family: "qwen2",
            capabilities: ["completion"],
            is_embedding_capable: false,
            is_chat_capable: true,
            exists_in_db: true,
            existing_config_id: 3,
          },
        ],
      })
    );
    render(<OllamaImportModal {...defaultProps} />, { wrapper: TestWrap });
    await waitFor(() => {
      expect(mockImport).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(screen.getByText(/nomic-embed-text:latest/)).toBeTruthy();
    });
    expect(screen.getByText(/qwen2\.5:7b/)).toBeTruthy();
  });

  it("submits selected rows via modelsApi.bulkCreate on confirm", async () => {
    const user = userEvent.setup();
    mockImport.mockResolvedValue(
      okImport({
        base_url: "http://localhost:11434",
        reachable: true,
        models: [
          {
            name: "nomic-embed-text:latest",
            family: "nomic-bert",
            capabilities: ["embedding"],
            is_embedding_capable: true,
            is_chat_capable: false,
            exists_in_db: false,
            existing_config_id: null,
          },
        ],
      })
    );
    mockBulkCreate.mockResolvedValue(
      okImport({
        results: [
          {
            requested_model_name: "nomic-embed-text:latest",
            status: "created",
            config: { id: 7, name: "nomic-embed-text:latest" },
          },
        ],
      })
    );

    render(<OllamaImportModal {...defaultProps} />, { wrapper: TestWrap });
    await waitFor(() => screen.getByText(/nomic-embed-text:latest/));

    // The newly-fetched, not-in-DB row is selected by default.
    // Click the "批量导入" confirm button.
    await user.click(screen.getByRole("button", { name: /批量导入|导入/ }));

    await waitFor(() => {
      expect(mockBulkCreate).toHaveBeenCalled();
    });
    const rows = mockBulkCreate.mock.calls[0][0];
    expect(Array.isArray(rows)).toBe(true);
    expect(rows.length).toBeGreaterThan(0);
    expect(rows[0]).toMatchObject({
      model_name: "nomic-embed-text:latest",
      model_type: "ollama",
    });
    // New row defaults to is_embedding=true because the model advertises the capability.
    expect(rows[0].is_embedding).toBe(true);
  });

  it("shows per-row outcomes after bulk-create completes", async () => {
    const user = userEvent.setup();
    mockImport.mockResolvedValue(
      okImport({
        base_url: "http://localhost:11434",
        reachable: true,
        models: [
          {
            name: "new-model-1",
            capabilities: [],
            is_embedding_capable: false,
            is_chat_capable: true,
            exists_in_db: false,
            existing_config_id: null,
          },
          {
            name: "dup-model-2",
            capabilities: [],
            is_embedding_capable: false,
            is_chat_capable: true,
            exists_in_db: false,
            existing_config_id: null,
          },
        ],
      })
    );
    mockBulkCreate.mockResolvedValue(
      okImport({
        results: [
          { requested_model_name: "new-model-1", status: "created" },
          {
            requested_model_name: "dup-model-2",
            status: "skipped",
            reason: "duplicate",
            existing_config_id: 11,
          },
        ],
      })
    );

    render(<OllamaImportModal {...defaultProps} />, { wrapper: TestWrap });
    await waitFor(() => screen.getByText("new-model-1"));
    await user.click(screen.getByRole("button", { name: /批量导入|导入/ }));

    // The summary should surface both rows' outcomes.
    // Use getAllByText since "new-model-1" appears as the model name
    // column, not as a unique role-bearing element.
    await waitFor(() => {
      const matches = screen.getAllByText("new-model-1");
      expect(matches.length).toBeGreaterThan(0);
    });
    // The "skipped" outcome must be visible to the admin.
    await waitFor(() => {
      expect(screen.getByText("已跳过")).toBeTruthy();
    });
  });
});
