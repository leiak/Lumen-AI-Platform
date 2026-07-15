// frontend/__tests__/markdown-to-docx.test.ts
//
// Tests for the markdown → .docx converter used by the chat
// export button. We unpack the produced .docx (a zip) with jszip
// and grep the document.xml — that's the only way to verify that
// the file Word will actually open contains the right structure.

import { describe, it, expect } from "vitest";
import JSZip from "jszip";
import { markdownToDocx } from "@/lib/markdown-to-docx";

async function readDocumentXml(md: string): Promise<string> {
  const buf = await markdownToDocx(md);
  // docx is a zip; transfer the Uint8Array via a Blob so jszip
  // accepts it portably across Node and jsdom.
  const zip = await JSZip.loadAsync(buf as unknown as ArrayBuffer);
  const entry = zip.file("word/document.xml");
  expect(entry, "word/document.xml should exist in the docx zip").toBeTruthy();
  return (await entry!.async("string")) as string;
}

describe("markdownToDocx", () => {
  it("produces a valid zip starting with PK", async () => {
    const buf = await markdownToDocx("# Hello");
    // Packer.toBuffer returns a Node Buffer (which extends Uint8Array
    // at runtime, but the global Uint8Array instanceof check varies
    // across vitest environments). Check the byte header directly
    // — PK\x03\x04 is the universal ZIP local-file-header magic.
    expect(buf).toBeTruthy();
    const view = new Uint8Array(
      buf.buffer,
      buf.byteOffset,
      buf.byteLength,
    );
    expect(view[0]).toBe(0x50); // 'P'
    expect(view[1]).toBe(0x4b); // 'K'
    expect(view[2]).toBe(0x03);
    expect(view[3]).toBe(0x04);
  });

  it("renders headings and body paragraphs with spacing", async () => {
    const xml = await readDocumentXml("# Title\n\nBody paragraph.");
    // Heading text present
    expect(xml).toContain("Title");
    expect(xml).toContain("Body paragraph.");
    // Body paragraph spacing tag (w:spacing with w:after="120") appears.
    // The docx schema writes tag attributes even when values come from
    // styles, but when we set them explicitly we should see after="120".
    expect(xml).toMatch(/w:after="120"/);
    // Heading spacing adds before="240"
    expect(xml).toMatch(/w:before="240"/);
  });

  it("drops thematic break (---) without rendering literal dashes", async () => {
    const xml = await readDocumentXml(
      "First paragraph.\n\n---\n\nSecond paragraph.",
    );
    expect(xml).not.toContain("———");
    // The two paragraphs should both be present
    expect(xml).toContain("First paragraph.");
    expect(xml).toContain("Second paragraph.");
  });

  it("renders markdown tables as real Word tables with borders", async () => {
    const md = [
      "| 维度 | 一期现状 |",
      "|------|----------|",
      "| App 端 | 基础预约 |",
      "| 后台端 | 记录管理 |",
    ].join("\n");
    const xml = await readDocumentXml(md);
    // Real table block (not just text)
    expect(xml).toContain("<w:tbl>");
    // Borders (w:tblBorders) present
    expect(xml).toContain("<w:tblBorders");
    // Each side of the table has a single-style border
    expect(xml).toContain('w:val="single"');
    // Cell text comes through
    expect(xml).toContain("维度");
    expect(xml).toContain("App 端");
    // Header row gets a light grey fill (f0f0f0)
    expect(xml).toContain("f0f0f0");
  });

  it("respects the requested table from the chat export feedback", async () => {
    const md = [
      "| 维度 | 一期现状 | 二期深化方向 | 价值 |",
      "|------|----------|--------------|------|",
      "| App 端 | 基础预约+车辆管理 | 智能化、个性化、增值化 | 提升用户体验与活跃度 |",
      "| 后台端 | 记录管理+API对接 | 数据化、自动化、可视化 | 提升 B 端运营效率 |",
      "| 业务边界 | 医院/学校/商圈/共享 | 新增场景+生态融合 | 扩大业务覆盖 |",
      "| 技术能力 | 实时查询+预约 | AI+IoT+大数据 | 沉淀技术壁垒 |",
    ].join("\n");
    const xml = await readDocumentXml(md);
    expect(xml).toContain("<w:tbl>");
    expect(xml).toContain("维度");
    expect(xml).toContain("沉淀技术壁垒");
  });

  it("renders bulleted and ordered lists with spacing", async () => {
    const md = ["- alpha", "- beta", "- gamma"].join("\n");
    const xml = await readDocumentXml(md);
    // Bullet glyph (rendered in a TextRun)
    expect(xml).toContain("•");
    expect(xml).toContain("alpha");
    expect(xml).toContain("gamma");
    // after-spacing applied to list paragraphs
    expect(xml).toMatch(/w:after="120"/);
  });

  it("renders fenced code blocks with grey shading and monospace font", async () => {
    const md = ["```", "print('hi')", "```"].join("\n");
    const xml = await readDocumentXml(md);
    // docx XML escapes apostrophes; check the unescaped part
    expect(xml).toContain("print(");
    // Code-block background
    expect(xml).toContain("f5f5f5");
    // Monospace font hint
    expect(xml).toContain("Consolas");
  });
});