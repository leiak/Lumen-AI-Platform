// frontend/__tests__/videos/stock-picker.test.tsx
// M36.2.1 — StockPickerModal + ComposeModal wiring.
//
// Verifies:
//   - 从素材库选 button opens the stock picker
//   - selecting rows then clicking 确定 calls the picker callback
//   - filters by category when category Select changes
//   - initialSelected highlights pre-selected ids
//   - the StockPickerModal reads /api/v1/stock-assets and renders a grid
//
// Note: StockPickerModal 的每张卡同时挂了 `<div onClick>` 和 `<Checkbox onChange>`,
// 用 fireEvent.click(checkbox) 会在 jsdom 触发双重 toggle(净变化 = 0)。本套测试
// 点卡片的 name 文本(只会冒泡到父 div onClick,不会触碰 Checkbox onChange),
// 保证每次点击只 toggle 一次。

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { TestWrapper } from "./test-utils";

const mockListVideos = vi.fn();
const mockCreateVideoCompose = vi.fn();
const mockListStockAssets = vi.fn();
const mockFetch = vi.fn();
const mockCreateObjectURL = vi.fn();
const mockRevokeObjectURL = vi.fn();

vi.mock("@/services/video", () => ({
  listVideos: (...args: any[]) => mockListVideos(...args),
  cancelVideo: vi.fn(),
  deleteVideo: vi.fn(),
  createVideoCompose: (...args: any[]) => mockCreateVideoCompose(...args),
  buildVideoUrl: (id: number) => `/api/v1/videos/${id}/download`,
}));

vi.mock("@/services/stock", () => ({
  listStockAssets: (...args: any[]) => mockListStockAssets(...args),
  getStockAsset: vi.fn(),
  buildStockImageUrl: (id: number) =>
    `http://localhost/api/v1/stock-assets/${id}/image`,
}));

vi.mock("@/services/playbook", () => ({
  listPlaybooks: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 }),
}));

const mockImageList = vi.fn();
vi.mock("@/services/image-generation", () => ({
  imageGenerationApi: {
    list: (...args: any[]) => mockImageList(...args),
    thumbnailPath: (id: number) => `/image-generation/${id}/thumbnail`,
    imagePath: (id: number) => `/image-generation/${id}/image`,
  },
}));

import VideosPage from "@/app/dashboard/videos/page";
import { StockPickerModal } from "@/components/video/StockPickerModal";

const sampleAsset = (id: number, name: string, category: string) => ({
  id,
  name,
  category,
  tags: ["builtin"],
  mime_type: "image/png",
  width: 1024,
  height: 1024,
  file_size: 12345,
  source: "builtin" as const,
  created_at: "2026-07-15T08:00:00Z",
});

beforeEach(() => {
  window.localStorage.setItem("access_token", "test-token");
  mockListVideos.mockReset();
  mockListVideos.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 12 });
  mockCreateVideoCompose.mockReset();
  mockCreateVideoCompose.mockResolvedValue({
    id: 100,
    tenant_id: 1,
    user_id: 1,
    conversation_id: null,
    model_config_id: null,
    playbook_id: null,
    source_audio_id: null,
    source_subtitle_id: null,
    source_images: ["/img/a.png"],
    resolution: "1280x720",
    fps: 24,
    file_path: "videos/x.mp4",
    file_size: 1024,
    mime_type: "video/mp4",
    duration_ms: 4000,
    status: "pending",
    error_message: null,
    started_at: null,
    finished_at: null,
    created_at: "2026-07-15T08:00:00Z",
    updated_at: "2026-07-15T08:00:00Z",
  });
  mockImageList.mockReset();
  mockImageList.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 24 });

  // Two stock items, both builtin landscape, fetched with category filter
  // respected by the modal.
  mockListStockAssets.mockReset();
  mockListStockAssets.mockImplementation((params: any) => {
    if (params?.category) {
      return Promise.resolve({
        items: [sampleAsset(1, "金色日落山景", params.category)],
        total: 1,
        page: 1,
        page_size: 24,
      });
    }
    return Promise.resolve({
      items: [
        sampleAsset(1, "金色日落山景", "风景"),
        sampleAsset(2, "团队合影", "人物"),
      ],
      total: 2,
      page: 1,
      page_size: 24,
    });
  });

  // StockThumb 走 fetch + blob + URL.createObjectURL(MEMORY 2026-06-20)。
  // jsdom 默认没 fetch / URL.createObjectURL,挂全局 mock 让缩略图正常加载。
  mockFetch.mockReset();
  mockFetch.mockResolvedValue({
    ok: true,
    blob: () => Promise.resolve(new Blob(["png"], { type: "image/png" })),
  });
  // @ts-ignore
  global.fetch = mockFetch;
  mockCreateObjectURL.mockReset();
  mockCreateObjectURL.mockReturnValue("blob:http://localhost/stock-thumb");
  mockRevokeObjectURL.mockReset();
  // @ts-ignore
  global.URL.createObjectURL = mockCreateObjectURL;
  // @ts-ignore
  global.URL.revokeObjectURL = mockRevokeObjectURL;
});

describe("StockPickerModal (in ComposeModal wiring)", () => {
  it("opens via the 从素材库选 button and lists items from /api/v1/stock-assets", async () => {
    render(
      <TestWrapper>
        <VideosPage />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListVideos).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /新建合成/ }));

    // 打开 stock picker — AntD 的 button accessible name 是
    // "picture 从素材库选"(icon + text)。用 *匹配。
    fireEvent.click(screen.getByRole("button", { name: /从素材库选/ }));

    // 等 grid 出现(等待 service 调用)。
    await waitFor(() => expect(mockListStockAssets).toHaveBeenCalled());
    expect(await screen.findByText("金色日落山景")).toBeInTheDocument();
    expect(await screen.findByText("团队合影")).toBeInTheDocument();
  });

  it("filters by category when a category is chosen", async () => {
    render(
      <TestWrapper>
        <VideosPage />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListVideos).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /新建合成/ }));
    fireEvent.click(screen.getByRole("button", { name: /从素材库选/ }));

    await waitFor(() => expect(mockListStockAssets).toHaveBeenCalled());

    // AntD Select option
    fireEvent.mouseDown(await screen.findByText("分类"));
    fireEvent.click(
      await screen.findByText("风景", { selector: ".ant-select-item-option-content" }),
    );

    await waitFor(() => {
      const lastCall =
        mockListStockAssets.mock.calls[mockListStockAssets.mock.calls.length - 1][0];
      expect(lastCall.category).toBe("风景");
    });
  });
});

describe("StockPickerModal (isolated)", () => {
  it("shows initial summary and disables OK when 0 selected", async () => {
    const onConfirm = vi.fn();
    render(
      <TestWrapper>
        <StockPickerModal open initialSelected={[]} onClose={() => {}} onConfirm={onConfirm} />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListStockAssets).toHaveBeenCalled());

    expect(await screen.findByText("金色日落山景")).toBeInTheDocument();
    expect(screen.getByText(/共 2 张,已选 0 张/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /确定 \(0\)/ })).toBeDisabled();
  });

  it("toggles selection on card click, updates OK label, fires onConfirm", async () => {
    const onConfirm = vi.fn();
    render(
      <TestWrapper>
        <StockPickerModal open initialSelected={[]} onClose={() => {}} onConfirm={onConfirm} />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListStockAssets).toHaveBeenCalled());
    await screen.findByText("金色日落山景");

    // 点击 name 文本 — 只冒泡到卡片的 onClick,触发 toggle 一次。
    fireEvent.click(screen.getByText("金色日落山景"));
    expect(screen.getByRole("button", { name: /确定 \(1\)/ })).not.toBeDisabled();
    expect(screen.getByText(/共 2 张,已选 1 张/)).toBeInTheDocument();

    fireEvent.click(screen.getByText("团队合影"));
    expect(screen.getByRole("button", { name: /确定 \(2\)/ })).not.toBeDisabled();
    expect(screen.getByText(/共 2 张,已选 2 张/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /确定 \(2\)/ }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    // 因为 Set → Array.from 顺序是插入顺序,所以 [1, 2]。
    expect(onConfirm).toHaveBeenCalledWith([1, 2]);
  });

  it("toggles off when the same card is clicked twice", async () => {
    const onConfirm = vi.fn();
    render(
      <TestWrapper>
        <StockPickerModal open initialSelected={[]} onClose={() => {}} onConfirm={onConfirm} />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListStockAssets).toHaveBeenCalled());
    const name1 = await screen.findByText("金色日落山景");

    fireEvent.click(name1);
    expect(screen.getByRole("button", { name: /确定 \(1\)/ })).not.toBeDisabled();

    fireEvent.click(name1);
    expect(screen.getByRole("button", { name: /确定 \(0\)/ })).toBeDisabled();
    expect(screen.getByText(/已选 0 张/)).toBeInTheDocument();
  });

  it("pre-selects ids passed via initialSelected", async () => {
    const onConfirm = vi.fn();
    render(
      <TestWrapper>
        <StockPickerModal open initialSelected={[1]} onClose={() => {}} onConfirm={onConfirm} />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListStockAssets).toHaveBeenCalled());
    await screen.findByText("金色日落山景");

    expect(screen.getByText(/已选 1 张/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /确定 \(1\)/ })).not.toBeDisabled();
  });
});

describe("StockThumb fetch+blob pattern (MEMORY 2026-06-20)", () => {
  it("each card fetches the proxy URL with Bearer header and calls URL.createObjectURL", async () => {
    render(
      <TestWrapper>
        <StockPickerModal open initialSelected={[]} onClose={() => {}} onConfirm={vi.fn()} />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListStockAssets).toHaveBeenCalled());
    await screen.findByText("金色日落山景");

    // 2 个 sample asset,挂 2 个 StockThumb,期望 2 次 fetch + 2 次 createObjectURL。
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(mockCreateObjectURL).toHaveBeenCalledTimes(2));

    // 校验 URL 形态 + Authorization 头都正确,跟 detail-modal 同模式。
    const allUrls = mockFetch.mock.calls.map((c) => String(c[0]));
    expect(allUrls.some((u) => u.includes("/api/v1/stock-assets/1/image"))).toBe(true);
    expect(allUrls.some((u) => u.includes("/api/v1/stock-assets/2/image"))).toBe(true);
    const firstHeaders = (mockFetch.mock.calls[0][1]?.headers ?? {}) as Record<string, string>;
    expect(firstHeaders.Authorization).toBe("Bearer test-token");
  });
});
