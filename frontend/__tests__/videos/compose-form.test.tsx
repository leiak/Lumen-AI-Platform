// frontend/__tests__/videos/compose-form.test.tsx
// M36.1 — ComposeModal submit flow.
//
// Verifies:
//   - empty source_images → submit disabled
//   - adding a row enables submit
//   - clicking submit calls createVideoCompose with the right payload
//   - audio_path is included in the payload

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { TestWrapper } from "./test-utils";

const mockListVideos = vi.fn();
const mockCreateVideoCompose = vi.fn();

vi.mock("@/services/video", () => ({
  listVideos: (...args: any[]) => mockListVideos(...args),
  cancelVideo: vi.fn(),
  deleteVideo: vi.fn(),
  createVideoCompose: (...args: any[]) => mockCreateVideoCompose(...args),
  buildVideoUrl: (id: number) => `/api/v1/videos/${id}/download`,
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
  // Default empty image list so the ImagePickerModal won't make noise.
  mockImageList.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 24 });
});

describe("ComposeModal", () => {
  it("submit button is disabled when no source_images", async () => {
    render(
      <TestWrapper>
        <VideosPage />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListVideos).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /新建合成/ }));
    // modal opens — submit button is present and disabled.
    const submitBtn = await screen.findByRole("button", { name: /提交合成/ });
    expect(submitBtn).toBeDisabled();
  });

  it("adding a source image enables submit and submit calls createVideoCompose", async () => {
    render(
      <TestWrapper>
        <VideosPage />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListVideos).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /新建合成/ }));

    // Add a source image row.
    fireEvent.click(await screen.findByRole("button", { name: /添加图片路径/ }));

    // The newly added row's Input — find all placeholder inputs of the right kind.
    const inputs = await screen.findAllByPlaceholderText(/\/path\/to\/image\.png/);
    fireEvent.change(inputs[0], {
      target: { value: "/local/path/img1.png" },
    });

    // Submit enabled now.
    const submitBtn = await screen.findByRole("button", { name: /提交合成/ });
    expect(submitBtn).not.toBeDisabled();

    fireEvent.click(submitBtn);
    await waitFor(() => expect(mockCreateVideoCompose).toHaveBeenCalledTimes(1));
    const payload = mockCreateVideoCompose.mock.calls[0][0];
    expect(payload.source_images).toContain("/local/path/img1.png");
    expect(payload.resolution).toBe("1280x720");
    expect(payload.fps).toBe(24);
  });

  it("audio_path is included in the payload when pasted", async () => {
    render(
      <TestWrapper>
        <VideosPage />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListVideos).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /新建合成/ }));
    fireEvent.click(await screen.findByRole("button", { name: /添加图片路径/ }));

    const inputs = await screen.findAllByPlaceholderText(/\/path\/to\/image\.png/);
    fireEvent.change(inputs[0], { target: { value: "/local/img.png" } });

    // Find audio Input (only one with that placeholder) and fill it.
    const audioInput = await screen.findByPlaceholderText(/generated_audios\.id/);
    fireEvent.change(audioInput, { target: { value: "42" } });

    fireEvent.click(screen.getByRole("button", { name: /提交合成/ }));
    await waitFor(() => expect(mockCreateVideoCompose).toHaveBeenCalledTimes(1));
    const payload = mockCreateVideoCompose.mock.calls[0][0];
    expect(payload.audio_path).toBe("42");
  });

  it("ComposeModal exposes 从我的音频库选 + 从我的字幕库选 buttons", async () => {
    render(
      <TestWrapper>
        <VideosPage />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListVideos).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /新建合成/ }));
    expect(
      await screen.findByRole("button", { name: /从我的音频库选/ })
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: /从我的字幕库选/ })
    ).toBeInTheDocument();
  });
});