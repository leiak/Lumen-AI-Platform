// frontend/__tests__/videos/compose-modal-bgm.test.tsx
// M36.2.2 — ComposeModal BGM field wiring.
//
// Verifies:
//   - 高级参数区有「背景音乐」字段
//   - 「从背景音乐库选」按钮打开 MusicPickerModal
//   - picker 选中后,返回的 id 字符串被填到 background_music_path
//   - 提交表单时 background_music_path 字段进 payload

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { TestWrapper } from "./test-utils";

const mockListVideos = vi.fn();
const mockCreateVideoCompose = vi.fn();
const mockListStockMusics = vi.fn();

vi.mock("@/services/video", () => ({
  listVideos: (...args: any[]) => mockListVideos(...args),
  cancelVideo: vi.fn(),
  deleteVideo: vi.fn(),
  createVideoCompose: (...args: any[]) => mockCreateVideoCompose(...args),
  buildVideoUrl: (id: number) => `/api/v1/videos/${id}/download`,
}));

vi.mock("@/services/stock-music", () => ({
  listStockMusics: (...args: any[]) => mockListStockMusics(...args),
  getStockMusic: vi.fn(),
  buildStockMusicUrl: (id: number) =>
    `http://localhost/api/v1/stock-musics/${id}/file`,
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

const mockFetch = vi.fn();
const mockCreateObjectURL = vi.fn();
const mockRevokeObjectURL = vi.fn();

import VideosPage from "@/app/dashboard/videos/page";

beforeEach(() => {
  window.localStorage.setItem("access_token", "test-token");
  mockListVideos.mockReset();
  mockListVideos.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 12 });
  mockCreateVideoCompose.mockReset();
  mockCreateVideoCompose.mockResolvedValue({
    id: 100, tenant_id: 1, user_id: 1, conversation_id: null,
    model_config_id: null, playbook_id: null, source_audio_id: null,
    source_subtitle_id: null, source_images: ["/img/a.png"],
    resolution: "1280x720", fps: 24, file_path: "videos/x.mp4",
    file_size: 1024, mime_type: "video/mp4", duration_ms: 4000,
    status: "pending", error_message: null, started_at: null, finished_at: null,
    created_at: "2026-08-07T08:00:00Z", updated_at: "2026-08-07T08:00:00Z",
  });
  mockImageList.mockReset();
  mockImageList.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 24 });

  mockListStockMusics.mockReset();
  mockListStockMusics.mockResolvedValue({
    items: [{
      id: 1, name: "舒缓钢琴", category: "舒缓",
      description: "soft piano", mime_type: "audio/mpeg",
      file_size: 235000, duration_seconds: 30,
      source: "builtin" as const, created_at: "2026-08-07T08:00:00Z",
    }],
    total: 1, page: 1, page_size: 24,
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

describe("ComposeModal BGM integration", () => {
  it("advanced section has a 「背景音乐」 input + 「从背景音乐库选」 button", async () => {
    render(
      <TestWrapper>
        <VideosPage />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListVideos).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /新建合成/ }));

    expect(screen.getByText("背景音乐 (可选)")).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("本地音频路径 或 stock_musics.id (整数)"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /从背景音乐库选/ }),
    ).toBeInTheDocument();
  });

  it("clicking 「从背景音乐库选」 opens MusicPickerModal and lists builtin tracks", async () => {
    render(
      <TestWrapper>
        <VideosPage />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListVideos).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /新建合成/ }));
    fireEvent.click(screen.getByRole("button", { name: /从背景音乐库选/ }));

    await waitFor(() => expect(mockListStockMusics).toHaveBeenCalled());
    expect(await screen.findByText("舒缓钢琴")).toBeInTheDocument();
  });

  it("selecting a track in the picker writes the id string into background_music_path", async () => {
    render(
      <TestWrapper>
        <VideosPage />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListVideos).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /新建合成/ }));
    fireEvent.click(screen.getByRole("button", { name: /从背景音乐库选/ }));

    await waitFor(() => expect(mockListStockMusics).toHaveBeenCalled());
    // 选第一行,然后确定。
    fireEvent.click(await screen.findByText("舒缓钢琴"));
    fireEvent.click(screen.getByRole("button", { name: /^确定$/ }));

    // Modal 关闭后,ComposeModal 里 background_music_path 的 input 应
    // 该出现 "1" (后台 resolve 时把数字 id 字串当 stock_musics.id)。
    // 注意:Form.Item + name + Space.Compact 的坑 — 必须用 noStyle 包
    // Input,setFieldValue 才能注入到 Input 的显示值(见 ComposeModal
    // 注释)。
    await waitFor(() =>
      expect(
        screen.getByPlaceholderText("本地音频路径 或 stock_musics.id (整数)"),
      ).toHaveDisplayValue("1"),
    );
  });

  it("submitting the form with BGM set includes background_music_path in the payload", async () => {
    render(
      <TestWrapper>
        <VideosPage />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListVideos).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /新建合成/ }));

    // 先添加一张 source_images 行,让 submit 按钮可点。
    fireEvent.click(
      await screen.findByRole("button", { name: /添加图片路径/ }),
    );
    const imageInputs = await screen.findAllByPlaceholderText(
      /path\/to\/image\.png/,
    );
    fireEvent.change(imageInputs[0], { target: { value: "/tmp/a.png" } });

    // 直接往 BGM input 粘贴一个 id 字串 (覆盖 picker 路径,确保提交
    // 走通)。
    const bgmInput = screen.getByPlaceholderText(
      "本地音频路径 或 stock_musics.id (整数)",
    );
    fireEvent.change(bgmInput, { target: { value: "1" } });

    fireEvent.click(screen.getByRole("button", { name: /提交合成/ }));

    await waitFor(() => expect(mockCreateVideoCompose).toHaveBeenCalled());
    const payload = mockCreateVideoCompose.mock.calls[0][0];
    expect(payload.background_music_path).toBe("1");
    // backend 默认 0.3 音量写在 schema 里,UI 不暴露就不传。
  });
});
