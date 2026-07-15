import { describe, it, expect } from "vitest";
import { mergeDoneMetadata } from "../src/core/sse-merge";

describe("mergeDoneMetadata", () => {
  it("returns the same reference when event has no metadata fields", () => {
    const msg = { content: "x", role: "assistant" };
    const out = mergeDoneMetadata(msg, { content: "", done: true, conversation_id: 1 });
    expect(out).toBe(msg);
  });

  it("merges search_status into metadata", () => {
    const out = mergeDoneMetadata({}, { content: "", done: true, conversation_id: 1, search_status: "ok" });
    expect(out.metadata?.search_status).toBe("ok");
  });

  it("merges sources into metadata", () => {
    const out = mergeDoneMetadata({}, { content: "", done: true, conversation_id: 1, sources: [{ title: "x" }] });
    expect(out.metadata?.sources).toHaveLength(1);
  });

  it("preserves existing content (does not clobber message fields)", () => {
    const msg = { content: "hi" };
    const out = mergeDoneMetadata(msg, { content: "", done: true, conversation_id: 1, sources: [] });
    expect(out.content).toBe("hi");
  });

  it("preserves existing metadata fields when patching new ones", () => {
    const msg = { metadata: { attachments: [{ name: "a" }] } };
    const out = mergeDoneMetadata(msg, { content: "", done: true, conversation_id: 1, search_status: "ok" });
    expect(out.metadata?.attachments).toEqual([{ name: "a" }]);
    expect(out.metadata?.search_status).toBe("ok");
  });
});
