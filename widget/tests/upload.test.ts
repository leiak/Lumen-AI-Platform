import { describe, it, expect, vi, beforeEach } from "vitest";
import { uploadFile } from "../src/core/api";

describe("uploadFile", () => {
  beforeEach(() => {
    (global as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        code: 200,
        data: {
          file_id: "f1",
          name: "x.txt",
          size: 1,
          mime_type: "text/plain",
          content_text: "hi",
        },
      }),
    });
  });

  it("returns parsed UploadResult on 200", async () => {
    const r = await uploadFile({
      server: "http://x",
      token: "t",
      file: new File(["hi"], "x.txt"),
    });
    expect(r.file_id).toBe("f1");
    expect(r.content_text).toBe("hi");
  });

  it("throws on non-200", async () => {
    (global as any).fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 415,
      text: async () => "no",
    });
    await expect(
      uploadFile({
        server: "http://x",
        token: "t",
        file: new File([""], "x.bin"),
      })
    ).rejects.toThrow();
  });
});
