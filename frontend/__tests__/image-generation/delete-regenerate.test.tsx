// frontend/__tests__/image-generation/delete-regenerate.test.tsx
// M22 — image generation feature (T21)
//
// Tests for the delete confirmation flow on DetailModal. The delete button
// is wrapped in an AntD Popconfirm — clicking the button opens the
// Popconfirm (which shows the title "确定删除?"), and clicking the
// Popconfirm's confirm button ("删除" inside the popover) triggers the
// delete API.
//
// Notes:
//   - The "trigger" button (text "删除", danger) lives inside the Modal's
//     footer. Clicking it opens the Popconfirm. The Popconfirm portal
//     renders the title "确定删除?" plus an OK and Cancel button.
//   - The Popconfirm's OK button also has the text "删除" (it's the
//     `okText` we set in the component). So there are TWO buttons with
//     the text "删除" on screen once the popover is open.
//   - To disambiguate, we grab the OK button by its location within the
//     popover using `within(.ant-popover).getByRole("button", { name: "删除" })`.
//   - `vi.mock` factories are hoisted above the rest of the file, so we use
//     `vi.hoisted()` to share the regen/del references between the mock
//     factory and the test body.
import { describe, expect, it, vi, beforeEach } from "vitest";
import {
  render,
  screen,
  waitFor,
  fireEvent,
} from "@testing-library/react";
import { TestWrapper } from "./test-utils";
import { DetailModal } from "@/components/image-generation/DetailModal";

const detail = {
  id: 1,
  prompt_preview: "x",
  model_config_id: 1,
  model_name: "M",
  model_type: "openai",
  size: "1024x1024",
  status: "completed" as const,
  has_thumbnail: true,
  file_size: 1,
  width: 1,
  height: 1,
  duration_ms: 1,
  created_at: "2026-06-11T00:00:00Z",
  prompt: "x",
  negative_prompt: null,
  quality: null,
  style: null,
  n: 1,
  params: null,
  error_message: null,
  updated_at: "2026-06-11T00:00:00Z",
};

const hoisted = vi.hoisted(() => ({
  regen: vi.fn().mockResolvedValue({ id: 2, status: "pending" }),
  del: vi.fn().mockResolvedValue(true),
}));

vi.mock("@/services/image-generation", () => ({
  imageGenerationApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    regenerate: hoisted.regen,
    delete: hoisted.del,
    imagePath: (id: number) => `/image-generation/${id}/image`,
    thumbnailPath: (id: number) => `/image-generation/${id}/thumbnail`,
  },
}));

describe("Delete + Regenerate", () => {
  beforeEach(() => {
    hoisted.regen.mockClear();
    hoisted.del.mockClear();
  });

  it("delete requires confirm", async () => {
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
    // Click the delete trigger button. AntD buttons prepend the icon's
    // aria-label to the accessible name, so the button is "delete 删除"
    // (DeleteOutlined alt + the visible text). We match the full name.
    const triggerBtn = screen.getByRole("button", { name: /删除/ });
    fireEvent.click(triggerBtn);
    // Popconfirm title should appear.
    expect(await screen.findByText("确定删除?")).toBeInTheDocument();
    // Now click the Popconfirm's OK button. AntD splits the okText "删除"
    // into two characters for visual spacing, so the button's accessible
    // name is "删 除" (with a single space). The trigger button has the
    // accessible name "delete 删除" (icon + text), so we can disambiguate
    // globally using the exact spaced name "删 除".
    const confirmBtn = screen.getByRole("button", { name: "删 除" });
    fireEvent.click(confirmBtn);
    await waitFor(() => expect(hoisted.del).toHaveBeenCalledWith(1));
  });
});
