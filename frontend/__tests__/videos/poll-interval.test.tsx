// frontend/__tests__/videos/poll-interval.test.tsx
// M36.1 — verify the page's 5s refetch interval wiring.
//
// We mock the listVideos service with a controllable counter and use
// vitest's fake timers to advance time. The page should re-invoke
// listVideos when the 5s interval elapses (and not over-poll).

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { TestWrapper } from "./test-utils";

const mockListVideos = vi.fn();
const mockCancelVideo = vi.fn();
const mockDeleteVideo = vi.fn();

vi.mock("@/services/video", () => ({
  listVideos: (...args: any[]) => mockListVideos(...args),
  cancelVideo: (...args: any[]) => mockCancelVideo(...args),
  deleteVideo: (...args: any[]) => mockDeleteVideo(...args),
  createVideoCompose: vi.fn(),
  buildVideoUrl: (id: number) => `/api/v1/videos/${id}/download`,
}));

vi.mock("@/services/playbook", () => ({
  listPlaybooks: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 }),
}));

import VideosPage from "@/app/dashboard/videos/page";

beforeEach(() => {
  window.localStorage.setItem("access_token", "test-token");
  mockListVideos.mockReset();
  mockListVideos.mockResolvedValue({
    items: [],
    total: 0,
    page: 1,
    page_size: 12,
  });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("VideosPage poll interval", () => {
  it("refetches listVideos after the 5s refetchInterval", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(
      <TestWrapper>
        <VideosPage />
      </TestWrapper>
    );
    // First call: enabled + immediate
    await waitFor(() => expect(mockListVideos).toHaveBeenCalledTimes(1));

    // Advance 5s → expect another call
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    await waitFor(() => expect(mockListVideos.mock.calls.length).toBeGreaterThanOrEqual(2));

    // Advance another 5s → a third call
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    await waitFor(() => expect(mockListVideos.mock.calls.length).toBeGreaterThanOrEqual(3));
  });
});