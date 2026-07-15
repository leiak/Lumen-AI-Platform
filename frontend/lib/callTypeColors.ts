/**
 * Color mapping for ``call_type`` values used by the trace timeline UI.
 *
 * Reused by:
 * - ``/dashboard/logs/trace/[trace_id]/page.tsx`` for Timeline dot colors
 * - ``/dashboard/logs/llm-calls-tab.tsx`` for the call_type column tag color
 *
 * antd Timeline accepts only ``blue | red | green | gray`` natively, so
 * for richer colors we set ``dot`` to a custom ``<span style={{color}}>``.
 * For tags, antd accepts the full CSS color set.
 *
 * Defaults to a neutral ``gray`` for unknown call_types so additions to
 * the backend enum don't break the UI; the new tag still renders, it just
 * uses the fallback color.
 *
 * Spec: docs/superpowers/specs/2026-06-15-embedding-trace-retention.md §"Trace 视图"
 */
export const COLOR_BY_CALL_TYPE: Record<string, string> = {
  // === LLM (M26) ===
  chat: "blue",
  widget: "geekblue",
  "team.manager_decision": "purple",
  "team.worker": "cyan",
  "team.aggregate": "orange",
  "workflow.llm": "green",
  image_generation: "magenta",
  // === Embeddings (M27) ===
  kb_retrieval: "gold",
  kb_ingest: "lime",
  "system.kb_ingest": "default",
  workflow_kb: "volcano",
  dim_probe: "default",
};

export function colorForCallType(callType: string | undefined | null): string {
  if (!callType) return "default";
  return COLOR_BY_CALL_TYPE[callType] || "default";
}
