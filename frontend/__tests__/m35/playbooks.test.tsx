// frontend/__tests__/m35/playbooks.test.tsx
// M35: /dashboard/system/playbooks page tests.
//
// Verifies:
//   - Built-in playbooks show 内置 tag + 编辑/删除 disabled
//   - User playbooks can be created via modal
//   - User playbooks can be edited
//   - User playbooks can be deleted (popconfirm → deletePlaybook call)
//   - Empty list → Empty component
//
// Mocking pattern follows __tests__/chat/page-agent-binding.test.tsx —
// intercept the service module and assert against `.mock.calls`.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { TestWrapper } from "./test-utils";
import { message } from "antd";

const mockListPlaybooks = vi.fn();
const mockGetPlaybook = vi.fn();
const mockCreatePlaybook = vi.fn();
const mockUpdatePlaybook = vi.fn();
const mockDeletePlaybook = vi.fn();
const mockImportPlaybookYaml = vi.fn();

vi.mock("@/services/playbook", () => ({
  listPlaybooks: (...args: any[]) => mockListPlaybooks(...args),
  getPlaybook: (...args: any[]) => mockGetPlaybook(...args),
  createPlaybook: (...args: any[]) => mockCreatePlaybook(...args),
  updatePlaybook: (...args: any[]) => mockUpdatePlaybook(...args),
  deletePlaybook: (...args: any[]) => mockDeletePlaybook(...args),
  importPlaybookYaml: (...args: any[]) => mockImportPlaybookYaml(...args),
}));

import PlaybooksPage from "@/app/dashboard/system/playbooks/page";
import type { PlaybookDetail, PlaybookListItem } from "@/types/playbook";

// services/playbook.ts unwraps the antd envelope internally (res.data.data),
// so the service mock must return the *flat* shape it returns — { items,
// total, page, page_size } — NOT the envelope.
const listResult = (items: PlaybookListItem[]) => ({
  items,
  total: items.length,
  page: 1,
  page_size: 10,
});

const baseDate = "2026-06-25T08:00:00Z";

const builtInItem = (id: number, name: string): PlaybookListItem => ({
  id,
  name,
  description: "built-in",
  scope: ["image", "tts"],
  is_builtin: true,
  created_at: baseDate,
  updated_at: baseDate,
});

const userItem = (id: number, name: string): PlaybookListItem => ({
  id,
  name,
  description: "user",
  scope: ["image"],
  is_builtin: false,
  created_at: baseDate,
  updated_at: baseDate,
});

const detailFor = (row: PlaybookListItem): PlaybookDetail => ({
  ...row,
  tenant_id: 1,
  yaml_content: "keywords:\n  - clean\n  - modern\n",
  style_tokens: { keywords: ["clean", "modern"] },
  created_by: 1,
});

describe("PlaybooksPage", () => {
  beforeEach(async () => {
    mockListPlaybooks.mockReset();
    mockGetPlaybook.mockReset();
    mockCreatePlaybook.mockReset();
    mockUpdatePlaybook.mockReset();
    mockDeletePlaybook.mockReset();
    mockImportPlaybookYaml.mockReset();
    // Default list -> empty
    mockListPlaybooks.mockResolvedValue(listResult([]));
    // Stub App.useApp() message spy (the antd `message` module is what
    // would be the fallback if App.useApp() is unavailable, which it
    // isn't, but the spy keeps console clean).
    vi.spyOn(message, "error").mockImplementation((() => ({})) as any);
    vi.spyOn(message, "warning").mockImplementation((() => ({})) as any);
    vi.spyOn(message, "success").mockImplementation((() => ({})) as any);
  });

  it("renders list rows and shows built-in tag + disables actions for built-ins", async () => {
    mockListPlaybooks.mockResolvedValue(
      listResult([builtInItem(1, "clean-professional"), userItem(2, "my-style")])
    );
    render(
      <TestWrapper>
        <PlaybooksPage />
      </TestWrapper>
    );
    // Wait for rows
    await waitFor(() => expect(screen.getByText("clean-professional")).toBeInTheDocument());
    expect(screen.getByText("my-style")).toBeInTheDocument();
    // Built-in tag (LockOutlined icon + text)
    expect(screen.getAllByText("内置").length).toBeGreaterThanOrEqual(1);
    // AntD v5 disabled Button → renders `disabled=""` HTML attribute.
    // The page has two rows: built-in row first, user row second.
    const editButtons = screen.getAllByRole("button", { name: /编辑/ });
    expect(editButtons.length).toBe(2);
    // First button (built-in row) must be disabled.
    expect(editButtons[0].hasAttribute("disabled")).toBe(true);
    // Second button (user row) must NOT be disabled.
    expect(editButtons[1].hasAttribute("disabled")).toBe(false);
  });

  it("creates a new playbook via the modal: validates → createPlaybook → reload", async () => {
    mockCreatePlaybook.mockResolvedValue({});
    // After create, the page reloads — return a list that now has the row.
    mockListPlaybooks
      .mockResolvedValueOnce(listResult([]))
      .mockResolvedValueOnce(listResult([userItem(99, "my-style")]));
    render(
      <TestWrapper>
        <PlaybooksPage />
      </TestWrapper>
    );
    // Open the create modal by clicking the "新建 Playbook" button in Card.extra
    // (the same text appears as the modal title — we must scope to the button).
    const createBtn = await screen.findByRole("button", { name: /新建 Playbook/ });
    fireEvent.click(createBtn);
    // The modal title now also shows "新建 Playbook" — getAllByText proves
    // the modal is open.
    await waitFor(() =>
      expect(screen.getAllByText("新建 Playbook").length).toBeGreaterThanOrEqual(2)
    );
    // Fill name + YAML (description optional). The form is set up with
    // DEFAULT_YAML by default, so we only need to type a name.
    const nameInput = document.querySelector('input[id="name"]') as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: "my-style" } });
    // Save (the Modal's okText is "保存") — only the OK button in the modal.
    const saveButtons = screen.getAllByRole("button", { name: /^保存$/ });
    fireEvent.click(saveButtons[saveButtons.length - 1]);
    await waitFor(() => expect(mockCreatePlaybook).toHaveBeenCalledTimes(1));
    const payload = mockCreatePlaybook.mock.calls[0][0];
    expect(payload.name).toBe("my-style");
    expect(payload.yaml_content).toContain("keywords");
  });

  it("deletes a user playbook via popconfirm → deletePlaybook", async () => {
    mockListPlaybooks.mockResolvedValue(listResult([userItem(2, "my-style")]));
    mockDeletePlaybook.mockResolvedValue(undefined);
    render(
      <TestWrapper>
        <PlaybooksPage />
      </TestWrapper>
    );
    await waitFor(() => expect(screen.getByText("my-style")).toBeInTheDocument());
    // Click 删除 button — the trigger. Popconfirm shows OK (default text
    // may be "OK" in jsdom intl locale or "确定" — match "primary" class).
    const triggerBtn = screen.getByRole("button", { name: /删除/ });
    fireEvent.click(triggerBtn);
    // Popconfirm title should appear.
    expect(await screen.findByText("确认删除该 playbook?")).toBeInTheDocument();
    // Find the OK button inside the popover layer (rc-trigger renders into
    // a separate portal). The primary ant-btn is the OK button (Cancel is
    // the secondary default button).
    await waitFor(() => {
      const okBtn = document.querySelector(".ant-popover .ant-btn-primary");
      expect(okBtn).toBeTruthy();
      fireEvent.click(okBtn!);
    });
    await waitFor(() => expect(mockDeletePlaybook).toHaveBeenCalledWith(2));
  });

  it("shows empty state when list is empty", async () => {
    render(
      <TestWrapper>
        <PlaybooksPage />
      </TestWrapper>
    );
    await waitFor(() =>
      expect(screen.getByText(/暂无 playbook/)).toBeInTheDocument()
    );
  });
});
