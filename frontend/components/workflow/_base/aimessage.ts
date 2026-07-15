// frontend/components/workflow/_base/aimessage.ts

/**
 * Pull the `content='...'` segment out of a stringified LangChain AIMessage.
 *
 * The backend serializes the AIMessage as Python repr, which produces
 * something like::
 *
 *   content='Hello, world!' additional_kwargs={...} name='ChatBot' id='run-...'
 *
 * Inside `content`, newlines and single quotes are escaped as `\\n` and `\\'`.
 * We extract the segment and decode both escapes so the UI shows readable text.
 *
 * If the input does NOT look like a stringified AIMessage, return it as-is so
 * downstream rendering still works for plain strings.
 */
export function extractAIMessageContent(raw: string): string {
  if (!raw) return raw;
  // Use [\s\S]* instead of .* with the /s flag because tsconfig.json targets
  // ES2017 — the /s flag is an ES2018 feature. [\s\S] gives the same
  // "match across newlines" behavior on the older target.
  const m = raw.match(/^content='([\s\S]*)' additional_kwargs=/);
  if (!m) return raw;
  // Decode the two escapes LangChain applies to AIMessage content.
  return m[1]
    .replace(/\\n/g, "\n")
    .replace(/\\'/g, "'")
    .replace(/\\\\/g, "\\");
}
