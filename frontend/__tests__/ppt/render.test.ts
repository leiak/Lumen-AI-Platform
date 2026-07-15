import { describe, test, expect } from "vitest";
import { styleTheme, renderPpt } from "@/lib/ppt-renderer";
import type { PptSchema } from "@/types/ppt";

describe("PPT style themes", () => {
  test("三风格 theme 至少 2 项字段不同", () => {
    const s = styleTheme("simple");
    const b = styleTheme("business");
    const a = styleTheme("academic");
    expect(s.titleFont).not.toBe(b.titleFont);
    expect(s.bg).not.toBe(a.bg);
    expect(b.chartPalette).not.toEqual(s.chartPalette);
    expect(s.bulletChar).not.toBe(b.bulletChar);
    expect(s.showTopBar).not.toBe(b.showTopBar);
  });

  test("学术主题含衬线字体、地球色板、罗马页码", () => {
    const a = styleTheme("academic");
    expect(a.titleFont).toContain("Times");
    expect(a.chartPalette.length).toBeGreaterThanOrEqual(5);
    expect(a.pageNumberFormat).toBe("roman");
    expect(a.showTopBar).toBe(true);
  });

  test("用 mock schema 渲染 pptxgenjs 不抛且输出非空", async () => {
    const schema: PptSchema = {
      title: "x",
      slides: [
        { layout: "title_only", title: "t" },
        { layout: "title_content", title: "内容", content: ["要点一", "要点二"] },
        { layout: "blank", content: ["谢谢观看"] },
      ],
    };
    const buf = await renderPpt(schema, "academic");
    expect(buf.byteLength).toBeGreaterThan(0);
  });
});
