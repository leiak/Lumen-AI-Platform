// frontend/__tests__/videos/audio-picker.test.tsx
// M36.1.1 — AudioPickerModal contract.
//
// Verifies:
//   - Modal lists TTS jobs from listTTSJobs (filtered to status=completed)
//   - User can single-select a row
//   - OK button is disabled until a row is selected
//   - onConfirm receives the chosen id

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { TestWrapper } from "./test-utils";

const mockListTTSJobs = vi.fn();

vi.mock("@/services/tts", () => ({
  listTTSJobs: (...args: any[]) => mockListTTSJobs(...args),
}));

import { AudioPickerModal } from "@/components/video/AudioPickerModal";

const completedJob = (id: number, voice: string) => ({
  id,
  model_config_id: 1,
  voice,
  format: "mp3" as const,
  status: "completed" as const,
  text_preview: `Job ${id} preview text`,
  duration_ms: 5000 + id * 100,
  char_count: 20,
  created_at: "2026-07-15T08:00:00Z",
});

beforeEach(() => {
  mockListTTSJobs.mockReset();
  mockListTTSJobs.mockResolvedValue({
    items: [completedJob(1, "zh-CN-XiaoxiaoNeural"), completedJob(2, "zh-CN-YunxiNeural")],
    total: 2,
    page: 1,
    page_size: 20,
  });
});

describe("AudioPickerModal", () => {
  it("lists TTS jobs and requires a selection before confirming", async () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    render(
      <TestWrapper>
        <AudioPickerModal open onClose={onClose} onConfirm={onConfirm} />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListTTSJobs).toHaveBeenCalled());
    // Both jobs should appear (id rendered as #1 / #2)
    expect(await screen.findByText("#1")).toBeInTheDocument();
    expect(screen.getByText("#2")).toBeInTheDocument();
    // OK button is disabled until a row is selected
    const okBtn = screen.getByRole("button", { name: "确定" });
    expect(okBtn).toBeDisabled();
  });

  it("filters to status=completed when calling listTTSJobs", async () => {
    const onConfirm = vi.fn();
    render(
      <TestWrapper>
        <AudioPickerModal open onClose={() => {}} onConfirm={onConfirm} />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListTTSJobs).toHaveBeenCalled());
    // The picker only wants audio whose on-disk mp3 exists → completed only.
    expect(mockListTTSJobs).toHaveBeenCalledWith(
      expect.objectContaining({ status: "completed" })
    );
  });

  it("clicking a row enables OK, and OK fires onConfirm with the chosen id", async () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    render(
      <TestWrapper>
        <AudioPickerModal open onClose={onClose} onConfirm={onConfirm} />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListTTSJobs).toHaveBeenCalled());
    // Click the row for job #1
    const row1 = await screen.findByText("#1");
    fireEvent.click(row1);
    // OK now enabled
    const okBtn = screen.getByRole("button", { name: "确定" });
    expect(okBtn).not.toBeDisabled();
    // Click OK
    fireEvent.click(okBtn);
    expect(onConfirm).toHaveBeenCalledWith(1);
  });
});