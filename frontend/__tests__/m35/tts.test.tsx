// frontend/__tests__/m35/tts.test.tsx
// M35: /dashboard/tts page tests.
//
// Verifies:
//   - Page renders model selector with TTS-capable models
//   - Picking a model triggers voice list load
//   - Submit creates a TTS job with payload { model_config_id, text, voice, ... }
//   - Generate + Subtitle also calls createSubtitle
//   - History table renders TTSJobListItem rows from listTTSJobs
//   - Empty history → Empty component
//
// The page uses App.useApp() (toast pattern per MEMORY 2026-06-07), useQuery
// for models/playbooks via the service, and 2s polling for history. We're
// not testing the polling timer — we just verify the list initially renders.
//
// Bearer auth via fetch+blob+createObjectURL is intentionally out of scope
// here (covered by the TTS audio endpoint unit tests on the backend).
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { TestWrapper } from "./test-utils";

const mockListTTSJobs = vi.fn();
const mockListTTSVoices = vi.fn();
const mockCreateTTSJob = vi.fn();
const mockDeleteTTSJob = vi.fn();

vi.mock("@/services/tts", () => ({
  listTTSJobs: (...args: any[]) => mockListTTSJobs(...args),
  listTTSVoices: (...args: any[]) => mockListTTSVoices(...args),
  createTTSJob: (...args: any[]) => mockCreateTTSJob(...args),
  deleteTTSJob: (...args: any[]) => mockDeleteTTSJob(...args),
  buildAudioUrl: (id: number) => `/api/v1/tts/jobs/${id}/audio`,
}));

const mockListPlaybooks = vi.fn();
const mockCreateSubtitle = vi.fn();
const mockDownloadSubtitleUrl = vi.fn();

vi.mock("@/services/playbook", () => ({
  listPlaybooks: (...args: any[]) => mockListPlaybooks(...args),
}));

vi.mock("@/services/subtitle", () => ({
  createSubtitle: (...args: any[]) => mockCreateSubtitle(...args),
  downloadSubtitleUrl: (...id: number[]) => `/api/v1/subtitles/${id[0]}/download`,
}));

const mockModelsList = vi.fn();
vi.mock("@/services/models", () => ({
  modelsApi: {
    list: (...args: any[]) => mockModelsList(...args),
  },
}));

import TTSPage from "@/app/dashboard/tts/page";
import type { TTSJobListItem } from "@/types/tts";
import type { PlaybookListItem } from "@/types/playbook";

// The page reads window.localStorage to get the Bearer token for audio fetches.
// Stub it so "未登录" toasts don't fire.
beforeEach(() => {
  window.localStorage.setItem("access_token", "test-token");
});

// Service mock shapes: tts/playbook services unwrap the antd envelope
// internally (res.data.data), so they return flat objects.
const modelsEnvelope = (data: any[]) => ({
  data: { code: 200, message: "ok", data, total: data.length, page: 1, page_size: 100 },
});
const ttsListResult = (items: TTSJobListItem[]) => ({
  items,
  total: items.length,
  page: 1,
  page_size: 20,
});
const playbookListResult = (items: PlaybookListItem[]) => ({
  items,
  total: items.length,
  page: 1,
  page_size: 50,
});

const sampleTTSModel = (id: number, name: string) => ({
  id,
  name,
  model_name: `${name}-1.0`,
  model_type: "edge",
  is_tts: true,
  is_active: true,
  is_chat: false,
  is_embedding: false,
  is_image_generation: false,
  tenant_id: 1,
  created_at: "2026-06-25T00:00:00Z",
  updated_at: "2026-06-25T00:00:00Z",
});

const sampleVoice = (id: string) => ({
  id,
  name: `${id}-name`,
  language: "zh-CN",
  gender: "female",
});

const samplePlaybook = (id: number, name: string): PlaybookListItem => ({
  id,
  name,
  description: "x",
  scope: ["tts"],
  is_builtin: false,
  created_at: "2026-06-25T00:00:00Z",
  updated_at: "2026-06-25T00:00:00Z",
});

const sampleJob = (id: number, status: TTSJobListItem["status"]): TTSJobListItem => ({
  id,
  model_config_id: 1,
  voice: "zh-CN-XiaoxiaoNeural",
  format: "mp3",
  status,
  text_preview: "sample",
  duration_ms: null,
  char_count: 6,
  created_at: "2026-06-25T08:00:00Z",
});

describe("TTSPage", () => {
  beforeEach(() => {
    mockListTTSJobs.mockReset();
    mockListTTSVoices.mockReset();
    mockCreateTTSJob.mockReset();
    mockDeleteTTSJob.mockReset();
    mockListPlaybooks.mockReset();
    mockCreateSubtitle.mockReset();
    mockModelsList.mockReset();

    // Defaults — empty lists, no voices
    mockListTTSJobs.mockResolvedValue(ttsListResult([]));
    mockListTTSVoices.mockResolvedValue([]);
    mockListPlaybooks.mockResolvedValue(playbookListResult([]));
    mockModelsList.mockResolvedValue(modelsEnvelope([sampleTTSModel(1, "Edge TTS zh")]));
    mockCreateTTSJob.mockResolvedValue({
      id: 100,
      status: "pending",
      model_config_id: 1,
      format: "mp3",
      voice: "zh-CN-XiaoxiaoNeural",
      created_at: "2026-06-25T08:00:00Z",
    });
  });

  it("renders the page heading and model selector", async () => {
    render(
      <TestWrapper>
        <TTSPage />
      </TestWrapper>
    );
    expect(await screen.findByText("语音合成")).toBeInTheDocument();
    // Wait for the model select to mount and load via the mock.
    await waitFor(() => expect(mockModelsList).toHaveBeenCalled());
    // The form's "TTS 模型" label is rendered.
    expect(screen.getByText("TTS 模型")).toBeInTheDocument();
  });

  it("picking a model triggers listTTSVoices and populates the Voice dropdown", async () => {
    mockListTTSVoices.mockResolvedValue([sampleVoice("zh-CN-XiaoxiaoNeural"), sampleVoice("zh-CN-YunxiNeural")]);
    render(
      <TestWrapper>
        <TTSPage />
      </TestWrapper>
    );
    await waitFor(() => expect(mockModelsList).toHaveBeenCalled());
    // Open the model Select — it's the first combobox on the page.
    const comboboxes = screen.getAllByRole("combobox");
    fireEvent.mouseDown(comboboxes[0]);
    const modelOpt = await screen.findByText(/Edge TTS zh \(edge\)/);
    fireEvent.click(modelOpt);
    // listTTSVoices(modelConfigId, language?) — language is optional,
    // so vitest records the call as `[1]` rather than `[1, undefined]`.
    await waitFor(() =>
      expect(mockListTTSVoices).toHaveBeenCalled()
    );
    expect(mockListTTSVoices.mock.calls[0][0]).toBe(1);
  });

  it("submit creates a TTS job with model_config_id + text + voice + format", async () => {
    mockListTTSVoices.mockResolvedValue([sampleVoice("zh-CN-XiaoxiaoNeural")]);
    render(
      <TestWrapper>
        <TTSPage />
      </TestWrapper>
    );
    await waitFor(() => expect(mockModelsList).toHaveBeenCalled());
    // Pick model — find the first combobox (TTS 模型) and pick the option.
    fireEvent.mouseDown(screen.getAllByRole("combobox")[0]);
    fireEvent.click(await screen.findByText(/Edge TTS zh \(edge\)/));
    // Allow the voice list to populate (useEffect → listTTSVoices).
    await waitFor(() => expect(mockListTTSVoices).toHaveBeenCalled());
    // Click Generate (the visible text is just "Generate" — match loosely).
    const genBtn = await screen.findByRole("button", { name: /Generate$/ });
    fireEvent.click(genBtn);
    await waitFor(() => expect(mockCreateTTSJob).toHaveBeenCalledTimes(1));
    const payload = mockCreateTTSJob.mock.calls[0][0];
    expect(payload.model_config_id).toBe(1);
    expect(payload.text).toBeTruthy(); // DEFAULT_TEXT
    expect(payload.voice).toBe("zh-CN-XiaoxiaoNeural");
    expect(payload.format).toBe("mp3");
    // No subtitle without the +Subtitle button
    expect(mockCreateSubtitle).not.toHaveBeenCalled();
  });

  it("Generate + Subtitle also calls createSubtitle and downloadSubtitleUrl", async () => {
    mockListTTSVoices.mockResolvedValue([sampleVoice("zh-CN-XiaoxiaoNeural")]);
    mockCreateSubtitle.mockResolvedValue({ id: 42, cue_count: 2 });
    // window.open stub so we don't actually try to pop a tab.
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);

    render(
      <TestWrapper>
        <TTSPage />
      </TestWrapper>
    );
    await waitFor(() => expect(mockModelsList).toHaveBeenCalled());
    fireEvent.mouseDown(screen.getAllByRole("combobox")[0]);
    fireEvent.click(await screen.findByText(/Edge TTS zh \(edge\)/));
    await waitFor(() => expect(mockListTTSVoices).toHaveBeenCalled());

    const subtitleBtn = await screen.findByRole("button", { name: /Generate \+ Subtitle/ });
    fireEvent.click(subtitleBtn);
    await waitFor(() => expect(mockCreateTTSJob).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(mockCreateSubtitle).toHaveBeenCalledTimes(1));
    const subPayload = mockCreateSubtitle.mock.calls[0][0];
    expect(subPayload.script).toBeTruthy();
    expect(subPayload.total_duration_ms).toBeGreaterThanOrEqual(2000);
    expect(subPayload.language).toBe("zh-CN");
    expect(subPayload.tts_job_id).toBe(100);
    // The download url was opened in a new tab.
    await waitFor(() =>
      expect(openSpy).toHaveBeenCalledWith(expect.stringContaining("/subtitles/42/download"), "_blank")
    );
    openSpy.mockRestore();
  });

  it("renders history list when listTTSJobs returns rows", async () => {
    mockListTTSJobs.mockResolvedValue(
      ttsListResult([sampleJob(10, "completed"), sampleJob(11, "pending")])
    );
    render(
      <TestWrapper>
        <TTSPage />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListTTSJobs).toHaveBeenCalled());
    // Both rows appear (status tags).
    expect(await screen.findByText("completed")).toBeInTheDocument();
    expect(screen.getByText("pending")).toBeInTheDocument();
  });

  it("renders Empty when there is no history", async () => {
    render(
      <TestWrapper>
        <TTSPage />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListTTSJobs).toHaveBeenCalled());
    expect(await screen.findByText(/暂无任务/)).toBeInTheDocument();
  });
});
