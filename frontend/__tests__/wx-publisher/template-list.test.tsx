// frontend/__tests__/wx-publisher/template-list.test.tsx
// M32 — 公众号助手 — Template gallery tests.
// 2 cases: Card 网格 / 系统模板标识.
//
// M32.1 follow-up: TemplateCard now fetch+blob+URL.createObjectURL
// internally (see components/wx-publisher/TemplateCard.tsx header for
// why <img src=...> doesn't work with Bearer auth). jsdom has no fetch
// and no URL.createObjectURL, so polyfill both before each test —
// otherwise the new useEffect throws "fetch is not a function" and
// the card silently renders without a thumbnail (which is fine for
// this test, but we want it to *not* throw).
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { TestWrapper } from "./test-utils";
import TemplatesPage from "@/app/dashboard/wx-publisher/templates/page";

const hoisted = vi.hoisted(() => ({
  listMock: vi.fn(),
}));

vi.mock("@/services/wx-publisher", () => ({
  draftApi: { list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), delete: vi.fn(), addSection: vi.fn(), updateSection: vi.fn(), deleteSection: vi.fn(), reorderSections: vi.fn() },
  accountApi: { list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), delete: vi.fn(), verify: vi.fn() },
  templateApi: {
    list: hoisted.listMock,
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    thumbnailPath: (id: number) => `/x/${id}`,
  },
  draftAiApi: { outline: vi.fn(), rewrite: vi.fn(), expand: vi.fn(), title: vi.fn(), render: vi.fn() },
  materialApi: { list: vi.fn(), get: vi.fn(), create: vi.fn(), delete: vi.fn(), importFromKB: vi.fn() },
  publishApi: { createPublish: vi.fn(), getPublish: vi.fn() },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
  useParams: () => ({ id: "1" }),
  usePathname: () => "/dashboard/wx-publisher/templates",
}));

// Polyfill fetch + URL.createObjectURL for jsdom (TemplateCard's
// thumbnail useEffect needs both). We return a fake 1x1 JPEG blob so
// the effect's happy-path completes and the card shows a real <img>.
beforeEach(() => {
  const fakeJpegBytes = new Uint8Array([
    0xff, 0xd8, 0xff, 0xe0, 0, 0x10, 0x4a, 0x46, 0x49, 0x46, 0, 1, 1, 0, 0, 1,
    0, 1, 0, 0, 0xff, 0xdb, 0, 0x43, 0, 8, 6, 6, 7, 6, 5, 8, 7, 7, 7, 9, 9,
    8, 10, 12, 20, 13, 12, 11, 11, 12, 25, 18, 19, 15, 20, 29, 26, 31, 30, 29,
    26, 28, 28, 32, 36, 46, 39, 32, 34, 44, 35, 28, 28, 40, 55, 41, 44, 48,
    49, 52, 52, 52, 31, 39, 57, 61, 56, 50, 60, 46, 51, 52, 50, 0xff, 0xd9,
  ]);
  global.fetch = vi.fn(async () =>
    new Response(fakeJpegBytes, { status: 200, headers: { "content-type": "image/jpeg" } })
  );
  if (!URL.createObjectURL) {
    URL.createObjectURL = vi.fn(() => "blob:fake/test");
  }
  if (!URL.revokeObjectURL) {
    URL.revokeObjectURL = vi.fn();
  }
});

const sampleTemplates = [
  { id: 1, name: "极简白", category: "minimal", is_system: true, usage_count: 12, has_thumbnail: true, description: "极简白底", created_at: "2026-06-17T08:00:00Z" },
  { id: 2, name: "科技深色", category: "tech", is_system: true, usage_count: 5, has_thumbnail: false, description: "科技风", created_at: "2026-06-17T08:00:00Z" },
  { id: 3, name: "我的自定义", category: "magazine", is_system: false, usage_count: 1, has_thumbnail: true, description: "杂志风", created_at: "2026-06-17T08:00:00Z" },
];

describe("TemplatesPage", () => {
  beforeEach(() => {
    hoisted.listMock.mockReset();
    hoisted.listMock.mockResolvedValue({
      items: sampleTemplates,
      total: 3,
      page: 1,
      page_size: 24,
    });
  });

  it("renders template cards in grid", async () => {
    render(<TestWrapper><TemplatesPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByText("极简白")).toBeInTheDocument());
    expect(screen.getByText("科技深色")).toBeInTheDocument();
    expect(screen.getByText("我的自定义")).toBeInTheDocument();
  });

  it("marks system templates with 系统 tag", async () => {
    render(<TestWrapper><TemplatesPage /></TestWrapper>);
    await waitFor(() => expect(screen.getAllByText("系统").length).toBeGreaterThanOrEqual(2));
  });
});