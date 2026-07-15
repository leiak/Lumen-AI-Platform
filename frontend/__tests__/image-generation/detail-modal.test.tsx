// frontend/__tests__/image-generation/detail-modal.test.tsx
// M22 — image generation feature (T21)
//
// Tests for the DetailModal: prompt + params JSON display, and the regenerate
// action triggers the API.
//
// Notes:
//   - The component fetches the image bytes via fetch + blob + createObjectURL
//     (see DetailModal.tsx header for the rationale). We don't need to wait for
//     the image to actually render — the prompt + params are in the
//     Descriptions block which renders immediately.
//   - Mock the @/services/image-generation module with `imagePath` /
//     `thumbnailPath` (T14's actual export names).
//   - The component uses `App.useApp()` (or static `message` for `useMutation`
//     onError) — static `message` is the fallback if no App context. In
//     jsdom this works without an explicit <App> wrapper, but TestWrapper
//     already provides one (T19).
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { TestWrapper } from "./test-utils";
import { DetailModal } from "@/components/image-generation/DetailModal";

const detail = {
  id: 1,
  prompt_preview: "a cat",
  model_config_id: 1,
  model_name: "TestModel",
  model_type: "openai",
  size: "1024x1024",
  status: "completed" as const,
  has_thumbnail: true,
  file_size: 1024,
  width: 1024,
  height: 1024,
  duration_ms: 1000,
  created_at: new Date().toISOString(),
  prompt: "a cat wearing a hat",
  negative_prompt: null,
  quality: "standard",
  style: "vivid",
  n: 1,
  params: { foo: "bar" },
  error_message: null,
  updated_at: new Date().toISOString(),
};

vi.mock("@/services/image-generation", () => ({
  imageGenerationApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    regenerate: vi.fn().mockResolvedValue({ id: 2, status: "pending" }),
    delete: vi.fn().mockResolvedValue(true),
    imagePath: (id: number) => `/image-generation/${id}/image`,
    thumbnailPath: (id: number) => `/image-generation/${id}/thumbnail`,
  },
}));

describe("DetailModal", () => {
  beforeEach(async () => {
    const { imageGenerationApi } = await import("@/services/image-generation");
    (imageGenerationApi.regenerate as any).mockClear();
    (imageGenerationApi.delete as any).mockClear();
  });

  it("shows prompt and params JSON", () => {
    render(
      <TestWrapper>
        <DetailModal
          open
          detail={detail as any}
          apiBase="http://x"
          onClose={() => {}}
        />
      </TestWrapper>
    );
    // The full prompt (not the preview) shows in Descriptions.Item "Prompt".
    expect(screen.getByText("a cat wearing a hat")).toBeInTheDocument();
    // params is JSON.stringified with 2-space indent — exact text match is
    // sufficient here, the test is asserting the JSON block renders at all.
    expect(screen.getByText(/"foo": "bar"/)).toBeInTheDocument();
  });

  it("triggers regenerate on click", async () => {
    const { imageGenerationApi } = await import("@/services/image-generation");
    render(
      <TestWrapper>
        <DetailModal
          open
          detail={detail as any}
          apiBase="http://x"
          onClose={() => {}}
        />
      </TestWrapper>
    );
    fireEvent.click(screen.getByText("重新生成"));
    await waitFor(() =>
      expect(imageGenerationApi.regenerate).toHaveBeenCalledWith(1)
    );
  });
});
