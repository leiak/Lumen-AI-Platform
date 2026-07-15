// frontend/__tests__/videos/page-renders.test.tsx
// M36.1 — basic page render checks.
//
// Verifies the /dashboard/videos page mounts, shows the heading, the toolbar
// (status Select + 新建合成 button), and an Empty placeholder when the
// list endpoint returns no rows.

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { TestWrapper } from "./test-utils";

const mockListVideos = vi.fn();
const mockCancelVideo = vi.fn();
const mockDeleteVideo = vi.fn();
const mockCreateVideoCompose = vi.fn();

vi.mock("@/services/video", () => ({
  listVideos: (...args: any[]) => mockListVideos(...args),
  cancelVideo: (...args: any[]) => mockCancelVideo(...args),
  deleteVideo: (...args: any[]) => mockDeleteVideo(...args),
  createVideoCompose: (...args: any[]) => mockCreateVideoCompose(...args),
  buildVideoUrl: (id: number) => `/api/v1/videos/${id}/download`,
}));

// playbookService used by ComposeModal PlaybookSelect — return empty so the
// select stays in its placeholder state without async work.
vi.mock("@/services/playbook", () => ({
  listPlaybooks: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 }),
}));

import VideosPage from "@/app/dashboard/videos/page";

beforeEach(() => {
  window.localStorage.setItem("access_token", "test-token");
  mockListVideos.mockReset();
  mockListVideos.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 12 });
});

describe("VideosPage", () => {
  it("renders page heading, toolbar, and Empty when list is empty", async () => {
    render(
      <TestWrapper>
        <VideosPage />
      </TestWrapper>
    );
    // heading
    expect(screen.getByText("视频合成")).toBeInTheDocument();
    // toolbar buttons
    expect(screen.getByRole("button", { name: "刷新" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /新建合成/ })).toBeInTheDocument();
    // status select placeholder
    expect(screen.getByText("状态")).toBeInTheDocument();
    // Empty placeholder once list resolves
    await waitFor(() => expect(mockListVideos).toHaveBeenCalled());
    expect(
      await screen.findByText(/还没有合成记录,点右上角「新建合成」试试/)
    ).toBeInTheDocument();
  });

  it("renders video cards when listVideos returns rows", async () => {
    mockListVideos.mockResolvedValue({
      items: [
        {
          id: 7,
          resolution: "1280x720",
          fps: 24,
          file_size: 1024 * 50,
          duration_ms: 4000,
          status: "completed",
          image_count: 3,
          created_at: "2026-07-15T08:00:00Z",
        },
        {
          id: 8,
          resolution: "1920x1080",
          fps: 30,
          file_size: 1024 * 80,
          duration_ms: null,
          status: "pending",
          image_count: 5,
          created_at: "2026-07-15T08:01:00Z",
        },
      ],
      total: 2,
      page: 1,
      page_size: 12,
    });
    render(
      <TestWrapper>
        <VideosPage />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListVideos).toHaveBeenCalled());
    // VideoCard renders status Tag — completed + pending should both appear
    expect(await screen.findByText("已完成")).toBeInTheDocument();
    expect(screen.getByText("排队中")).toBeInTheDocument();
  });
});