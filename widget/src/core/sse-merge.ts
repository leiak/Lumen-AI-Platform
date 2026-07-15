/** SSE done-event metadata merger.
 *  COPIED from frontend/lib/chat-sse-utils.ts — kept as a verbatim
 *  copy (not a re-export) so the widget has zero dependency on the
 *  Next.js bundle. Update BOTH files when adding fields to the
 *  done event.
 *
 *  Type adjustments vs source: the source imports `Message` from
 *  `@/types/chat`. The widget has its own ChatMessage type (defined
 *  in LumenChat.ts), so we use a local minimal interface here to keep
 *  this module import-free.
 */

export interface WidgetDoneEvent {
  content: string;
  done: boolean;
  conversation_id: number;
  search_status?: "ok" | "empty" | "error" | "disabled";
  sources?: Array<{ title?: string; url?: string; snippet?: string }>;
}

export interface WidgetMessage {
  content?: string;
  role?: string;
  metadata?: Record<string, any>;
  [key: string]: any;
}

/** Merge the metadata fields from the final SSE `done` event into the
 *  streaming assistant message. Returns the same reference when the
 *  event has nothing to patch. */
export function mergeDoneMetadata(message: WidgetMessage, ev: WidgetDoneEvent): WidgetMessage {
  const hasSearchStatus = ev.search_status !== undefined;
  const hasSources = ev.sources !== undefined;
  if (!hasSearchStatus && !hasSources) {
    return message;
  }
  return {
    ...message,
    metadata: {
      ...(message.metadata || {}),
      ...(hasSearchStatus ? { search_status: ev.search_status } : {}),
      ...(hasSources ? { sources: ev.sources } : {}),
    },
  };
}
