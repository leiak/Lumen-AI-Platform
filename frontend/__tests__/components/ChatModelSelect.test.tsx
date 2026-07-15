import { describe, expect, it, vi, beforeEach } from "vitest";
import { useState } from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ConfigProvider } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const mockList = vi.fn();
vi.mock("@/services/models", () => ({
  modelsApi: {
    list: (...args: any[]) => mockList(...args),
  },
}));

import ChatModelSelect from "@/components/ChatModelSelect";

// Per-render QueryClient so the query cache (and staleTime window)
// doesn't leak between tests — otherwise test 2 would see test 1's
// cached result and never call mockList at all.
const TestWrap = ({ children }: { children: React.ReactNode }) => {
  const [qc] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: false } },
      })
  );
  return (
    <QueryClientProvider client={qc}>
      <ConfigProvider button={{ autoInsertSpace: false }}>{children}</ConfigProvider>
    </QueryClientProvider>
  );
};

const ok = (data: any[]) => ({
  data: { code: 200, message: "ok", data, total: data.length, page: 1, page_size: 100 },
});

describe("ChatModelSelect", () => {
  beforeEach(() => {
    mockList.mockReset();
  });

  it("renders fetched options with name (model_name) labels", async () => {
    mockList.mockResolvedValue(
      ok([
        {
          id: 1,
          name: "MiniMax-M2.7-highspeed",
          model_name: "MiniMax-M2.7-highspeed",
          is_chat: true,
          is_embedding: false,
          is_active: true,
          is_default: true,
          model_type: "openai",
        },
        {
          id: 2,
          name: "qwen2.5:0.5b",
          model_name: "qwen2.5:0.5b",
          is_chat: true,
          is_embedding: false,
          is_active: true,
          is_default: false,
          model_type: "ollama",
        },
      ])
    );
    render(<ChatModelSelect value={1} onChange={() => {}} />, {
      wrapper: TestWrap,
    });

    // The selected value's label must be visible in the selector's
    // closed display (AntD writes the full option label as the
    // `title` attribute on the selection span, which we match).
    await waitFor(() => {
      expect(
        screen.getByTitle(/MiniMax-M2\.7-highspeed/)
      ).toBeTruthy();
    });

    // Open the dropdown so the second option (not currently selected)
    // is rendered into the DOM.
    const combobox = screen.getByRole("combobox");
    fireEvent.mouseDown(combobox);
    await waitFor(() => {
      expect(
        screen.getByTitle(/qwen2\.5:0\.5b/)
      ).toBeTruthy();
    });
  });

  it("calls modelsApi.list with is_chat=true and is_active=true", async () => {
    mockList.mockResolvedValue(ok([]));
    render(<ChatModelSelect />, { wrapper: TestWrap });
    await waitFor(() => {
      expect(mockList).toHaveBeenCalled();
    });
    const args = mockList.mock.calls[0];
    // args signature: list(1, 100, { is_chat: true, is_active: true })
    expect(args[2]).toMatchObject({ is_chat: true, is_active: true });
  });

  it("shows an empty-state Alert with a link to the models page when no chat models exist", async () => {
    mockList.mockResolvedValue(ok([]));
    render(<ChatModelSelect />, { wrapper: TestWrap });
    await waitFor(() => {
      // The Alert description starts with "请先前往" — unique to the
      // Alert (placeholder text "暂无可用 Chat 模型" duplicates the
      // Alert title and would match multiple elements).
      expect(screen.getByText(/请先前往/)).toBeTruthy();
    });
    // The Alert description should include a link to the system models
    // page so the user has a one-click path to add one.
    const link = screen.getByRole("link", { name: /系统模型管理/ });
    expect(link).toBeTruthy();
    expect(link.getAttribute("href")).toBe("/dashboard/system/models");
  });
});
