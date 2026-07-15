// frontend/__tests__/image-generation/page-renders.test.tsx
// M22 — image generation feature (T20)
//
// List rendering tests for /dashboard/image-generation. Verifies the page
// renders list items from the API, and shows the AntD Empty component when
// the API returns no items.
//
// Notes:
//   - The service mock must export `imagePath` / `thumbnailPath` (renamed
//     from the plan's `imageUrl` / `thumbnailUrl` per T14).
//   - The page uses `useQuery` with a 5s polling interval, so we need
//     `retry: false` (via TestWrapper) and to wait for the list text to
//     appear rather than the spinner.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { TestWrapper } from "./test-utils";
import ImageGenerationPage from "@/app/dashboard/image-generation/page";

vi.mock("@/services/image-generation", () => ({
  imageGenerationApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    regenerate: vi.fn(),
    delete: vi.fn(),
    imagePath: (id: number) => `/image-generation/${id}/image`,
    thumbnailPath: (id: number) => `/image-generation/${id}/thumbnail`,
  },
}));

const sampleItem = {
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
  created_at: "2026-06-11T08:00:00Z",
};

describe("ImageGenerationPage", () => {
  beforeEach(async () => {
    const { imageGenerationApi } = await import("@/services/image-generation");
    (imageGenerationApi.list as any).mockReset();
  });

  it("renders the page heading and list", async () => {
    const { imageGenerationApi } = await import("@/services/image-generation");
    (imageGenerationApi.list as any).mockResolvedValue({
      items: [sampleItem],
      total: 1,
      page: 1,
      page_size: 12,
    });
    render(
      <TestWrapper>
        <ImageGenerationPage />
      </TestWrapper>
    );
    await waitFor(() => expect(screen.getByText("a cat")).toBeInTheDocument());
  });

  it("shows empty state when no items", async () => {
    const { imageGenerationApi } = await import("@/services/image-generation");
    (imageGenerationApi.list as any).mockResolvedValueOnce({
      items: [],
      total: 0,
      page: 1,
      page_size: 12,
    });
    render(
      <TestWrapper>
        <ImageGenerationPage />
      </TestWrapper>
    );
    await waitFor(() =>
      expect(screen.getByText(/还没有图片/)).toBeInTheDocument()
    );
  });
});
