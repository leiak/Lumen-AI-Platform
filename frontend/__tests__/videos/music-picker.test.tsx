// frontend/__tests__/videos/music-picker.test.tsx
// M36.2.2 — MusicPickerModal: list BGM, audio preview, confirm callback.
//
// Mirrors stock-picker.test.tsx structure but adapted for single-select
// with inline <audio> preview. The audio preview uses the fetch + blob +
// createObjectURL pattern (MEMORY 2026-06-20) so we mock fetch + URL.

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { TestWrapper } from "./test-utils";

const mockListStockMusics = vi.fn();
const mockFetch = vi.fn();
const mockCreateObjectURL = vi.fn();
const mockRevokeObjectURL = vi.fn();

vi.mock("@/services/stock-music", () => ({
  listStockMusics: (...args: any[]) => mockListStockMusics(...args),
  getStockMusic: vi.fn(),
  buildStockMusicUrl: (id: number) =>
    `http://localhost/api/v1/stock-musics/${id}/file`,
}));

import { MusicPickerModal } from "@/components/video/MusicPickerModal";

const sampleMusic = (id: number, name: string, category: string) => ({
  id,
  name,
  category,
  description: `${category} style background music`,
  mime_type: "audio/mpeg",
  file_size: 235000,
  duration_seconds: 30,
  source: "builtin" as const,
  created_at: "2026-08-07T08:00:00Z",
});

beforeEach(() => {
  window.localStorage.setItem("access_token", "test-token");
  mockListStockMusics.mockReset();
  mockListStockMusics.mockResolvedValue({
    items: [
      sampleMusic(1, "舒缓钢琴", "舒缓"),
      sampleMusic(2, "活力节拍", "振奋"),
    ],
    total: 2,
    page: 1,
    page_size: 24,
  });

  mockFetch.mockReset();
  mockFetch.mockResolvedValue({
    ok: true,
    blob: () => Promise.resolve(new Blob(["id3-fake"], { type: "audio/mpeg" })),
  });
  // @ts-ignore
  global.fetch = mockFetch;
  mockCreateObjectURL.mockReset();
  mockCreateObjectURL.mockReturnValue("blob:http://localhost/music-thumb");
  mockRevokeObjectURL.mockReset();
  // @ts-ignore
  global.URL.createObjectURL = mockCreateObjectURL;
  // @ts-ignore
  global.URL.revokeObjectURL = mockRevokeObjectURL;
});

describe("MusicPickerModal", () => {
  it("opens and lists BGM tracks from /api/v1/stock-musics", async () => {
    render(
      <TestWrapper>
        <MusicPickerModal open initialSelected={null} onClose={() => {}} onConfirm={vi.fn()} />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListStockMusics).toHaveBeenCalled());
    expect(await screen.findByText("舒缓钢琴")).toBeInTheDocument();
    expect(await screen.findByText("活力节拍")).toBeInTheDocument();
    expect(screen.getByText(/共 2 首/)).toBeInTheDocument();
  });

  it("disables OK when nothing selected and shows track count", async () => {
    render(
      <TestWrapper>
        <MusicPickerModal open initialSelected={null} onClose={() => {}} onConfirm={vi.fn()} />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListStockMusics).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: /^确定$/ })).toBeDisabled();
  });

  it("selecting a row enables OK and fires onConfirm with the chosen id", async () => {
    const onConfirm = vi.fn();
    render(
      <TestWrapper>
        <MusicPickerModal open initialSelected={null} onClose={() => {}} onConfirm={onConfirm} />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListStockMusics).toHaveBeenCalled());
    const name1 = await screen.findByText("舒缓钢琴");
    fireEvent.click(name1);

    expect(screen.getByRole("button", { name: /^确定$/ })).not.toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /^确定$/ }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm).toHaveBeenCalledWith(1);
  });

  it("clicking a selected row toggles off (deselects)", async () => {
    render(
      <TestWrapper>
        <MusicPickerModal open initialSelected={1} onClose={() => {}} onConfirm={vi.fn()} />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListStockMusics).toHaveBeenCalled());
    const name1 = await screen.findByText("舒缓钢琴");
    // 初始选中 1 号 → OK enabled。
    expect(screen.getByRole("button", { name: /^确定$/ })).not.toBeDisabled();
    // 再点一次 → 取消选中 → OK 重新禁用。
    fireEvent.click(name1);
    expect(screen.getByRole("button", { name: /^确定$/ })).toBeDisabled();
  });

  it("audio preview fetches the proxy URL with Bearer header and calls createObjectURL", async () => {
    render(
      <TestWrapper>
        <MusicPickerModal open initialSelected={1} onClose={() => {}} onConfirm={vi.fn()} />
      </TestWrapper>
    );
    // initialSelected={1} → 选中第一行 → 立即挂 <audio> → 立即 fetch。
    await waitFor(() => expect(mockFetch).toHaveBeenCalled());
    const url = String(mockFetch.mock.calls[0][0]);
    expect(url).toContain("/api/v1/stock-musics/1/file");
    const headers = (mockFetch.mock.calls[0][1]?.headers ?? {}) as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer test-token");
    await waitFor(() => expect(mockCreateObjectURL).toHaveBeenCalled());
    // <audio> 元素的 src 来自 createObjectURL 的返回值。
    const audio = await screen.findByLabelText("preview-舒缓钢琴");
    expect(audio).toBeInTheDocument();
    expect(audio.getAttribute("src")).toBe("blob:http://localhost/music-thumb");
  });
});
