/** API client: SSE parser, fetch wrapper with Bearer auth + 401 retry. */

import { TokenExpiredError } from "./auth";

export interface SSEEvent {
  event?: string;
  data: string;
  id?: string;
}

/** Parse an SSE chunk into a list of complete events. Returns the
 *  events parsed; the caller is responsible for carrying over the
 *  trailing partial buffer (we drop the last chunk when the buffer
 *  does not end with a blank-line separator). */
export function parseSSE(buf: string): SSEEvent[] {
  const events: SSEEvent[] = [];
  // If buffer doesn't end with the separator, the final chunk is
  // partial — leave it in the buffer for the next call.
  const endsWithSep = buf.endsWith("\n\n");
  const chunks = buf.split("\n\n");
  const complete = endsWithSep ? chunks : chunks.slice(0, -1);
  for (const c of complete) {
    const trimmed = c.trim();
    if (!trimmed) continue;
    if (trimmed.startsWith(":")) continue;  // comment / heartbeat
    const ev: SSEEvent = { data: "" };
    for (const line of trimmed.split("\n")) {
      if (line.startsWith("data: ")) ev.data += line.slice(6);
      else if (line.startsWith("event: ")) ev.event = line.slice(7).trim();
      else if (line.startsWith("id: ")) ev.id = line.slice(4).trim();
    }
    events.push(ev);
  }
  return events;
}

export interface StreamArgs {
  server: string;
  token: string;
  body: any;
  signal: AbortSignal;
}

export async function* streamChat(args: StreamArgs): AsyncGenerator<any> {
  const res = await fetch(`${args.server}/api/v1/external/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${args.token}`,
    },
    body: JSON.stringify(args.body),
    signal: args.signal,
  });
  if (res.status === 401) throw new TokenExpiredError();
  if (!res.ok) throw new Error(`HTTP ${res.status} ${await res.text()}`);

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const events = parseSSE(buf);
    let consumed = 0;
    for (const ev of events) {
      const start = buf.indexOf("\n\n", consumed);
      if (start < 0) break;
      consumed = start + 2;
      try {
        yield JSON.parse(ev.data);
      } catch {
        // malformed JSON event — skip
      }
    }
    buf = buf.slice(consumed);
  }
}

export async function uploadFile(args: {
  server: string;
  token: string;
  file: File;
}): Promise<{ file_id: string; name: string; size: number; mime_type: string; content_text: string }> {
  const fd = new FormData();
  fd.append("file", args.file);
  const res = await fetch(`${args.server}/api/v1/external/chat/upload`, {
    method: "POST",
    headers: { Authorization: `Bearer ${args.token}` },
    body: fd,
  });
  if (res.status === 401) throw new TokenExpiredError();
  if (!res.ok) throw new Error(`upload failed: HTTP ${res.status}`);
  const body = await res.json();
  if (body.code !== 200) throw new Error(body.message || "upload failed");
  return body.data;
}

export async function listConversations(args: { server: string; token: string }): Promise<any[]> {
  const res = await fetch(`${args.server}/api/v1/external/conversations`, {
    headers: { Authorization: `Bearer ${args.token}` },
  });
  if (res.status === 401) throw new TokenExpiredError();
  if (!res.ok) throw new Error(`list failed: HTTP ${res.status}`);
  const body = await res.json();
  return body.data || [];
}

/** Trade (app_key, visitor_id) for a JWT. */
export async function fetchToken(args: {
  server: string;
  appKey: string;
  visitorId: string;
}): Promise<{ token: string; expires_in: number; allowed_agents: any[]; allowed_teams: any[]; visitor_id: number }> {
  const res = await fetch(`${args.server}/api/v1/external/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ app_key: args.appKey, visitor_id: args.visitorId }),
  });
  if (!res.ok) throw new Error(`token failed: HTTP ${res.status}`);
  const body = await res.json();
  if (body.code !== 200) throw new Error(body.message || "token failed");
  return body.data;
}
