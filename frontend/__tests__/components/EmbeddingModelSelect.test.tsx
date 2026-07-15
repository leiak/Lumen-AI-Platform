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

import EmbeddingModelSelect from "@/components/EmbeddingModelSelect";

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

describe("EmbeddingModelSelect", () => {
  beforeEach(() => {
    mockList.mockReset();
  });

  it("renders fetched options with name (model_name) labels", async () => {
    mockList.mockResolvedValue(
      ok([
        {
          id: 5,
          name: "Ollama nomic",
          model_name: "nomic-embed-text",
          is_chat: false,
          is_embedding: true,
          is_active: true,
          model_type: "ollama",
        },
        {
          id: 6,
          name: "OpenAI ada",
          model_name: "text-embedding-3-small",
          is_chat: false,
          is_embedding: true,
          is_active: true,
          model_type: "openai",
        },
      ])
    );
    render(<EmbeddingModelSelect value={5} onChange={() => {}} />, {
      wrapper: TestWrap,
    });

    // The selected value's label must be visible in the selector's
    // closed display (AntD writes the full option label as the
    // `title` attribute on the selection span, which we match).
    await waitFor(() => {
      expect(
        screen.getByTitle(/Ollama nomic \(nomic-embed-text\)/)
      ).toBeTruthy();
    });

    // Open the dropdown so the second option (not currently selected)
    // is rendered into the DOM. We match by `title` (AntD wires it on
    // every option div) because the option body is now split across
    // multiple text nodes (name + parenthetical model_name + provider
    // Tag) and `getByText` with a regex can't match across split nodes.
    const combobox = screen.getByRole("combobox");
    fireEvent.mouseDown(combobox);
    await waitFor(() => {
      expect(
        screen.getByTitle(/OpenAI ada \(text-embedding-3-small\)/)
      ).toBeTruthy();
    });
  });

  it("calls modelsApi.list with is_embedding=true and is_active=true", async () => {
    mockList.mockResolvedValue(ok([]));
    render(<EmbeddingModelSelect />, { wrapper: TestWrap });
    await waitFor(() => {
      expect(mockList).toHaveBeenCalled();
    });
    const args = mockList.mock.calls[0];
    // args signature: list(1, 100, { is_embedding: true, is_active: true })
    expect(args[2]).toMatchObject({ is_embedding: true, is_active: true });
  });

  it("shows the locked hint when disabled", async () => {
    mockList.mockResolvedValue(ok([]));
    render(<EmbeddingModelSelect disabled />, { wrapper: TestWrap });
    // The hint is rendered as part of the wrapper; check the helper text appears.
    expect(screen.getByText(/创建后不可更改/)).toBeTruthy();
  });

  it("fires onLoaded with the fetched models so the parent can auto-default", async () => {
    const models = [
      {
        id: 11,
        name: "Default embed",
        model_name: "default-embed",
        is_chat: false,
        is_embedding: true,
        is_active: true,
        is_default: true,
        model_type: "ollama",
      },
      {
        id: 12,
        name: "Other embed",
        model_name: "other-embed",
        is_chat: false,
        is_embedding: true,
        is_active: true,
        is_default: false,
        model_type: "openai",
      },
    ];
    mockList.mockResolvedValue(ok(models));
    const onLoaded = vi.fn();
    render(<EmbeddingModelSelect onLoaded={onLoaded} />, {
      wrapper: TestWrap,
    });
    await waitFor(() => {
      expect(onLoaded).toHaveBeenCalledWith(models);
    });
  });

  it("shows an empty-state Alert with a link to the models page when no embedding models exist", async () => {
    mockList.mockResolvedValue(ok([]));
    render(<EmbeddingModelSelect />, { wrapper: TestWrap });
    await waitFor(() => {
      // The Alert description starts with "请先前往" — unique to the
      // Alert (placeholder text "暂无可用 Embedding 模型" duplicates
      // the Alert title and would match multiple elements).
      expect(screen.getByText(/请先前往/)).toBeTruthy();
    });
    // The Alert description should include a link to the system models
    // page so the user has a one-click path to add one.
    const link = screen.getByRole("link", { name: /系统模型管理/ });
    expect(link).toBeTruthy();
    expect(link.getAttribute("href")).toBe("/dashboard/system/models");
  });
});
