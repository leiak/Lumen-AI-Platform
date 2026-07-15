// frontend/__tests__/workflow/_base/aimessage.test.ts
import { describe, expect, it } from "vitest";
import { extractAIMessageContent } from "@/components/workflow/_base/aimessage";

describe("extractAIMessageContent", () => {
  it("returns the content segment from a well-formed AIMessage string", () => {
    const raw =
      "content='Hello, world!' additional_kwargs={'refusal': None} name='ChatBot' id='run-123'";
    expect(extractAIMessageContent(raw)).toBe("Hello, world!");
  });

  it("decodes escaped newlines and quotes inside content", () => {
    const raw =
      "content='Line 1\\nLine 2 with a \\' quote' additional_kwargs={} name='x' id='y'";
    expect(extractAIMessageContent(raw)).toBe("Line 1\nLine 2 with a ' quote");
  });

  it("returns the original string when the AIMessage pattern does not match", () => {
    expect(extractAIMessageContent("not an aimessage")).toBe("not an aimessage");
    expect(extractAIMessageContent("")).toBe("");
  });
});
