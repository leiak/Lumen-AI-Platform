/**
 * RealtimeClient — module-level singleton WebSocket client for the
 * AI platform web frontend. Authenticates via JWT in the query
 * string (the standard pattern for browser WebSockets, which cannot
 * set custom headers). Handles exponential backoff, 4401 stop, and
 * heartbeat pings.
 *
 * See: docs/superpowers/specs/2026-06-04-kb-document-notification-design.md §3.4
 */
export type Status = "connecting" | "open" | "closed" | "reconnecting";
export type Handler = (msg: { event: string; payload: any }) => void;
type StatusHandler = (s: Status) => void;

class RealtimeClient {
  private ws?: WebSocket;
  private _status: Status = "closed";
  private handlers: Set<Handler> = new Set();
  private statusHandlers: Set<StatusHandler> = new Set();
  private retry = 0;
  private pingTimer?: ReturnType<typeof setInterval>;
  private token = "";
  private authFailed = false;
  private disposed = false;

  get status() { return this._status; }

  connect(token: string) {
    if (this.authFailed) return;
    if (this.ws && this._status !== "closed") return;
    this.token = token;
    this.disposed = false;          // allow reconnection after a prior disconnect
    this._open();
  }

  private _open() {
    if (this.disposed) return;
    this._setStatus(this.retry === 0 ? "connecting" : "reconnecting");
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${location.hostname}:11335/api/v1/ws/web?token=${encodeURIComponent(this.token)}`;
    this.ws = new WebSocket(url);
    this.ws.onopen = () => {
      this.retry = 0;
      this._setStatus("open");
      this.pingTimer = setInterval(() => {
        this.ws?.send(JSON.stringify({ type: "ping" }));
      }, 25_000);
    };
    this.ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg?.type === "broadcast") {
          this.handlers.forEach(h => h({ event: msg.event, payload: msg.payload }));
        }
      } catch { /* ignore malformed frames */ }
    };
    this.ws.onclose = (ev: CloseEvent) => {
      clearInterval(this.pingTimer);
      if (ev.code === 4401) {
        this.authFailed = true;
        this._setStatus("closed");
        return;
      }
      this._setStatus("closed");
      this._scheduleReconnect();
    };
    this.ws.onerror = () => this.ws?.close();
  }

  private _scheduleReconnect() {
    const delay = Math.min(30_000, 1000 * Math.pow(2, this.retry++));
    setTimeout(() => this._open(), delay);
  }

  private _setStatus(s: Status) {
    this._status = s;
    this.statusHandlers.forEach(h => h(s));
  }

  onMessage(h: Handler) {
    this.handlers.add(h);
    return () => this.handlers.delete(h);
  }

  onStatusChange(h: StatusHandler) {
    this.statusHandlers.add(h);
    h(this._status);                  // emit current immediately
    return () => this.statusHandlers.delete(h);
  }

  disconnect() {
    this.disposed = true;
    this.ws?.close();
    this.ws = undefined;
    this.authFailed = false;
    clearInterval(this.pingTimer);
    this.pingTimer = undefined;
    this.retry = 0;
    this._setStatus("closed");
  }
}

export const realtime = new RealtimeClient();
