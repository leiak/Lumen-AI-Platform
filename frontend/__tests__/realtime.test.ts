import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  url: string;
  readyState = 0; // CONNECTING
  onopen: ((e: any) => void) | null = null;
  onclose: ((e: any) => void) | null = null;
  onerror: ((e: any) => void) | null = null;
  onmessage: ((e: any) => void) | null = null;
  sent: any[] = [];
  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }
  send(data: string) { this.sent.push(JSON.parse(data)); }
  close(code = 1000) {
    this.readyState = 3;
    this.onclose?.({ code });
  }
  // Test helpers
  fakeOpen() { this.readyState = 1; this.onopen?.({}); }
  fakeMessage(data: any) { this.onmessage?.({ data: JSON.stringify(data) }); }
  fakeClose(code = 1006) { this.readyState = 3; this.onclose?.({ code }); }
}

describe("RealtimeClient", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    (globalThis as any).WebSocket = FakeWebSocket;
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.resetModules();
  });

  it("connects with token in query string", async () => {
    const { realtime } = await import("@/services/realtime");
    realtime.connect("my-jwt");
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.instances[0].url).toContain("token=my-jwt");
  });

  it("dispatches broadcast messages to subscribers", async () => {
    const { realtime } = await import("@/services/realtime");
    realtime.connect("tok");
    const ws = FakeWebSocket.instances[0];
    ws.fakeOpen();
    const handler = vi.fn();
    const unsub = realtime.onMessage(handler);
    ws.fakeMessage({ type: "broadcast", event: "notification_created", payload: { id: 1 } });
    expect(handler).toHaveBeenCalledWith({ event: "notification_created", payload: { id: 1 } });
    unsub();
    ws.fakeMessage({ type: "broadcast", event: "x", payload: {} });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("schedules reconnect with exponential backoff on close", async () => {
    const { realtime } = await import("@/services/realtime");
    realtime.connect("tok");
    FakeWebSocket.instances[0].fakeOpen();
    FakeWebSocket.instances[0].fakeClose(1006);
    // backoff base is 1s
    await vi.advanceTimersByTimeAsync(1100);
    expect(FakeWebSocket.instances.length).toBeGreaterThanOrEqual(2);
  });

  it("does NOT reconnect after 4401 (auth failed)", async () => {
    const { realtime } = await import("@/services/realtime");
    realtime.connect("tok");
    FakeWebSocket.instances[0].fakeClose(4401);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeWebSocket.instances).toHaveLength(1); // no new conn
  });

  it("does NOT reconnect after explicit disconnect()", async () => {
    const { realtime } = await import("@/services/realtime");
    realtime.connect("tok");
    FakeWebSocket.instances[0].fakeOpen();
    realtime.disconnect();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeWebSocket.instances).toHaveLength(1); // no reconnect after disconnect
  });
});
