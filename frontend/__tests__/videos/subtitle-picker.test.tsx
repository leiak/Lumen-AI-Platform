// frontend/__tests__/videos/subtitle-picker.test.tsx
// M36.1.1 — SubtitlePickerModal contract.

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { TestWrapper } from "./test-utils";

const mockListSubtitles = vi.fn();

vi.mock("@/services/subtitle", () => ({
  listSubtitles: (...args: any[]) => mockListSubtitles(...args),
}));

import { SubtitlePickerModal } from "@/components/video/SubtitlePickerModal";

const sampleSub = (id: number, lang: string) => ({
  id,
  language: lang,
  cue_count: 5 + id,
  duration_ms: 4000 + id * 500,
  char_count: 100 + id * 10,
  tts_job_id: id % 2 === 0 ? id : null,
  created_at: "2026-07-15T08:00:00Z",
});

beforeEach(() => {
  mockListSubtitles.mockReset();
  mockListSubtitles.mockResolvedValue({
    items: [sampleSub(1, "zh-CN"), sampleSub(2, "en-US")],
    total: 2,
    page: 1,
    page_size: 20,
  });
});

describe("SubtitlePickerModal", () => {
  it("lists subtitles from listSubtitles", async () => {
    const onConfirm = vi.fn();
    render(
      <TestWrapper>
        <SubtitlePickerModal open onClose={() => {}} onConfirm={onConfirm} />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListSubtitles).toHaveBeenCalled());
    expect(await screen.findByText("#1")).toBeInTheDocument();
    expect(screen.getByText("#2")).toBeInTheDocument();
  });

  it("OK disabled until selection; OK fires onConfirm with id", async () => {
    const onConfirm = vi.fn();
    render(
      <TestWrapper>
        <SubtitlePickerModal open onClose={() => {}} onConfirm={onConfirm} />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListSubtitles).toHaveBeenCalled());
    const okBtn = screen.getByRole("button", { name: "确定" });
    expect(okBtn).toBeDisabled();
    const row2 = await screen.findByText("#2");
    fireEvent.click(row2);
    expect(okBtn).not.toBeDisabled();
    fireEvent.click(okBtn);
    expect(onConfirm).toHaveBeenCalledWith(2);
  });

  it("clicking the same row again deselects (toggles)", async () => {
    const onConfirm = vi.fn();
    render(
      <TestWrapper>
        <SubtitlePickerModal open onClose={() => {}} onConfirm={onConfirm} />
      </TestWrapper>
    );
    await waitFor(() => expect(mockListSubtitles).toHaveBeenCalled());
    const row1 = await screen.findByText("#1");
    const okBtn = screen.getByRole("button", { name: "确定" });
    // select
    fireEvent.click(row1);
    expect(okBtn).not.toBeDisabled();
    // deselect
    fireEvent.click(row1);
    expect(okBtn).toBeDisabled();
  });
});