import { describe, it, expect } from "vitest";
import { parseSSE } from "../src/core/api";

describe("parseSSE", () => {
  it("splits on double newline", () => {
    const buf = "data: a\n\ndata: b\n\n";
    const events = parseSSE(buf);
    expect(events.map((e) => e.data)).toEqual(["a", "b"]);
  });

  it("handles partial last buffer (no trailing \\n\\n)", () => {
    const buf = "data: a\n\ndata: b";
    const events = parseSSE(buf);
    expect(events.map((e) => e.data)).toEqual(["a"]);
  });

  it("ignores non-data lines", () => {
    const buf = "event: foo\ndata: a\n\n";
    const events = parseSSE(buf);
    expect(events).toHaveLength(1);
    expect(events[0].data).toBe("a");
  });

  it("skips empty events (heartbeats etc.)", () => {
    const buf = ": heartbeat\n\ndata: a\n\n";
    const events = parseSSE(buf);
    expect(events).toHaveLength(1);
  });
});
