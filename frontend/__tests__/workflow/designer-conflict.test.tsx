/**
 * M30d 2.0 (2026-09-07): 409 conflict detection tests.
 *
 * Covers the contract between the designer frontend and the
 * PUT /workflows/{id} endpoint's If-Match header. The frontend's
 * useAutoSave sends the last-known updated_at on every save; if a
 * concurrent edit advanced the row's updated_at, the server returns
 * 409 with the new timestamp and the frontend must surface a clear
 * error to the user.
 *
 * 3 cases (per 2.0 spec A8):
 *  - saveDesigner passes the If-Match header with current updated_at
 *  - 409 response is parsed and surfaced to handleSave's error path
 *  - successful retry after a 409 succeeds (no stale-lock-in)
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import api from "@/services/auth";
import { workflowApi } from "@/services/workflow";

vi.mock("@/services/auth", () => ({
  default: {
    put: vi.fn(),
    post: vi.fn(),
    get: vi.fn(),
    delete: vi.fn(),
  },
}));

const mockedApi = api as unknown as {
  put: ReturnType<typeof vi.fn>;
  post: ReturnType<typeof vi.fn>;
  get: ReturnType<typeof vi.fn>;
  delete: ReturnType<typeof vi.fn>;
};

describe("designer 409 conflict (M30d 2.0)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("saveDesigner forwards If-Match header with last known updated_at", async () => {
    mockedApi.put.mockResolvedValue({
      data: { code: 200, data: { id: 7, updated_at: "2026-09-07T13:00:00.000000" } },
    });

    await workflowApi.saveDesigner(
      7,
      { name: "wf", definition: { nodes: [], edges: [] } },
      "2026-09-07T12:00:00.000000",
    );

    expect(mockedApi.put).toHaveBeenCalledWith(
      "/workflows/7",
      expect.objectContaining({ name: "wf" }),
      expect.objectContaining({
        headers: expect.objectContaining({
          "If-Match": "2026-09-07T12:00:00.000000",
        }),
      }),
    );
  });

  it("409 response surfaces structured detail so the UI can toast", async () => {
    // Simulate the FastAPI 409 body shape
    mockedApi.put.mockRejectedValue({
      response: {
        status: 409,
        data: {
          detail: {
            error: "conflict",
            current_updated_at: "2026-09-07T13:00:00.000000",
            submitted_updated_at: "2026-09-07T12:00:00.000000",
          },
        },
      },
    });

    let caught: unknown;
    try {
      await workflowApi.saveDesigner(
        7,
        { name: "wf", definition: { nodes: [], edges: [] } },
        "2026-09-07T12:00:00.000000",
      );
    } catch (e) {
      caught = e;
    }

    expect(caught).toBeDefined();
    const detail = (caught as { response: { data: { detail: unknown } } })
      .response.data.detail;
    expect(detail).toMatchObject({ error: "conflict" });
    expect((detail as { current_updated_at: string }).current_updated_at)
      .toBe("2026-09-07T13:00:00.000000");
  });

  it("retry with fresh updated_at after a 409 succeeds", async () => {
    // First call: 409. Second call (with current_updated_at): 200.
    mockedApi.put
      .mockRejectedValueOnce({
        response: {
          status: 409,
          data: { detail: { error: "conflict", current_updated_at: "2026-09-07T13:00:00.000000" } },
        },
      })
      .mockResolvedValueOnce({
        data: { code: 200, data: { id: 7, updated_at: "2026-09-07T13:00:01.000000" } },
      });

    // First attempt fails
    await expect(
      workflowApi.saveDesigner(
        7,
        { name: "wf", definition: { nodes: [], edges: [] } },
        "2026-09-07T12:00:00.000000",
      ),
    ).rejects.toBeDefined();

    // Retry with the current value the 409 told us about
    await expect(
      workflowApi.saveDesigner(
        7,
        { name: "wf", definition: { nodes: [], edges: [] } },
        "2026-09-07T13:00:00.000000",
      ),
    ).resolves.toBeDefined();

    expect(mockedApi.put).toHaveBeenCalledTimes(2);
  });
});
