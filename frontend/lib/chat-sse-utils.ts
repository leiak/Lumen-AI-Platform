/**
 * Pure helpers for the /chat/stream SSE client in the chat page.
 *
 * Extracted out of page.tsx so the metadata-merge logic (the part with
 * real business rules: "patch keys, don't clobber, don't mutate") can
 * be unit-tested without standing up the whole streaming pipeline.
 */
import type { Message } from "@/types/chat";

export interface DoneEvent {
  content: string;
  done: boolean;
  conversation_id: number;
  search_status?: "ok" | "empty" | "error" | "disabled";
  sources?: Array<{ title?: string; url?: string; snippet?: string }>;
  /** Marketplace skill display names applied to this message. */
  skills?: string[];
}

/**
 * Merge the metadata fields from the final SSE `done` event into the
 * streaming assistant message that page.tsx is keeping in local state.
 *
 * Returns the same reference when the event has nothing to patch, so
 * React's `setMessages` doesn't trigger a needless re-render.
 */
export function mergeDoneMetadata(message: Message, ev: DoneEvent): Message {
  const hasSearchStatus = ev.search_status !== undefined;
  const hasSources = ev.sources !== undefined;
  const hasSkills = ev.skills !== undefined;
  if (!hasSearchStatus && !hasSources && !hasSkills) {
    return message;
  }
  return {
    ...message,
    metadata: {
      ...(message.metadata || {}),
      ...(hasSearchStatus ? { search_status: ev.search_status } : {}),
      ...(hasSources ? { sources: ev.sources } : {}),
      ...(hasSkills ? { skills: ev.skills } : {}),
    },
  };
}
