import { describe, it, expect } from "vitest";
import { renderMarkdown } from "../src/core/markdown";

describe("renderMarkdown", () => {
  it("renders headings", () => {
    const out = renderMarkdown("# Hello");
    expect(out).toContain("<h1>Hello</h1>");
  });
  it("escapes raw HTML (XSS guard)", () => {
    const out = renderMarkdown('<script>alert(1)</script>');
    expect(out).not.toContain("<script>");
  });
  it("highlights code blocks", () => {
    const out = renderMarkdown("```python\nprint(1)\n```");
    expect(out).toContain("hljs");
  });
});
