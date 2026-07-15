/**
 * Tests for the pure helper that merges the final SSE `done` event's
 * metadata into the streaming assistant message in local state.
 *
 * Why a pure helper: the page.tsx streaming code is a complex async
 * generator over SSE — hard to test in jsdom. The metadata merge is
 * the part that actually has business logic ("don't clobber existing
 * metadata fields, only patch the keys that arrived"), so we extract
 * it and test it directly.
 */
import { describe, it, expect } from "vitest";
import { mergeDoneMetadata } from "@/lib/chat-sse-utils";
import type { Message } from "@/types/chat";

const baseMsg: Message = {
  id: 0,
  conversation_id: 1,
  role: "assistant",
  content: "answer",
  created_at: "2026-06-04T00:00:00Z",
};

describe("mergeDoneMetadata", () => {
  it("returns the same message when done event has no metadata fields", () => {
    const out = mergeDoneMetadata(baseMsg, { content: "", done: true, conversation_id: 1 });
    expect(out).toBe(baseMsg);
  });

  it("attaches search_status when present", () => {
    const out = mergeDoneMetadata(baseMsg, {
      content: "", done: true, conversation_id: 1, search_status: "empty",
    });
    expect(out.metadata).toEqual({ search_status: "empty" });
  });

  it("attaches sources when present", () => {
    const sources = [{ title: "T", url: "u", snippet: "s" }];
    const out = mergeDoneMetadata(baseMsg, {
      content: "", done: true, conversation_id: 1, sources,
    });
    expect(out.metadata?.sources).toEqual(sources);
  });

  it("preserves existing metadata fields (e.g. attachments) when patching", () => {
    const msg: Message = {
      ...baseMsg,
      metadata: { attachments: [{ name: "a.txt", size: 1, mime_type: "text/plain" }] },
    };
    const out = mergeDoneMetadata(msg, {
      content: "", done: true, conversation_id: 1, search_status: "ok",
    });
    expect(out.metadata).toEqual({
      attachments: [{ name: "a.txt", size: 1, mime_type: "text/plain" }],
      search_status: "ok",
    });
  });

  it("returns a new object (does not mutate the input message)", () => {
    const out = mergeDoneMetadata(baseMsg, {
      content: "", done: true, conversation_id: 1, search_status: "ok",
    });
    expect(out).not.toBe(baseMsg);
    expect(baseMsg.metadata).toBeUndefined(); // unchanged
  });
});
