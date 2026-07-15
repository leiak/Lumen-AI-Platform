// frontend/__tests__/image-generation/filter-search.test.tsx
// M22 — image generation feature (T21)
//
// Tests for the search prompt filter on /dashboard/image-generation. Typing
// in the search input + pressing Enter should reset the page to 1 and include
// the prompt in the next list call.
//
// Notes:
//   - The page uses `useQuery` with a 5s polling interval, so the first list
//     call fires on mount and the Enter handler fires a second one. We assert
//     on the LAST call's args — that's the one that carries the search
//     payload.
//   - The AntD Input uses `onPressEnter` (not a keydown listener), so the
//     dispatchEvent('keydown' Enter) trick does not work. We use the React
//     `fireEvent.keyDown` with `key: "Enter"` and that is what the underlying
//     rc-input / antd Input wires to onPressEnter in jsdom.
//   - Mock list to return empty (the test does not need actual list items;
//     we only assert on the params passed to the API).
//   - `vi.mock` factories are hoisted above the rest of the file, so we use
//     `vi.hoisted()` to share the `listMock` reference between the mock
//     factory and the test body.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { TestWrapper } from "./test-utils";
import ImageGenerationPage from "@/app/dashboard/image-generation/page";

const hoisted = vi.hoisted(() => ({
  listMock: vi
    .fn()
    .mockResolvedValue({ items: [], total: 0, page: 1, page_size: 12 }),
}));

vi.mock("@/services/image-generation", () => ({
  imageGenerationApi: {
    list: hoisted.listMock,
    get: vi.fn(),
    create: vi.fn(),
    regenerate: vi.fn(),
    delete: vi.fn(),
    imagePath: (id: number) => `/image-generation/${id}/image`,
    thumbnailPath: (id: number) => `/image-generation/${id}/thumbnail`,
  },
}));

vi.mock("@/services/models", () => ({
  modelsApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    listTypes: vi.fn(),
    importFromOllama: vi.fn(),
    bulkCreate: vi.fn(),
  },
}));

describe("ImageGenerationPage filter", () => {
  beforeEach(() => {
    hoisted.listMock.mockClear();
    hoisted.listMock.mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 12,
    });
  });

  it("search input triggers list refetch with prompt + page=1", async () => {
    render(
      <TestWrapper>
        <ImageGenerationPage />
      </TestWrapper>
    );
    const input = screen.getByPlaceholderText("搜索 prompt") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "cat" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
    await waitFor(() => {
      // We expect at least one list call with the search payload. Assert
      // on the last call (Enter triggers a refetch with the new params).
      const calls = hoisted.listMock.mock.calls;
      expect(calls.length).toBeGreaterThan(0);
      const lastCall = calls[calls.length - 1][0];
      expect(lastCall).toMatchObject({ prompt: "cat", page: 1 });
    });
  });
});
