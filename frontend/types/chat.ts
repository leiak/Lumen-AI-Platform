export interface Message {
  id: number;
  conversation_id: number;
  role: 'user' | 'assistant' | 'system';
  content: string;
  metadata?: Record<string, any>;
  created_at: string;
}

export interface Conversation {
  id: number;
  title: string;
  agent_id?: number;
  agent_name?: string;
  created_at: string;
  updated_at: string;
}

/**
 * A single citation / source attached to an assistant message.
 * The backend (or any RAG layer) can attach a `sources` array to
 * `Message.metadata`; the chat UI renders it as numbered chips.
 *
 * All fields are optional so we degrade gracefully when the backend
 * returns only a subset.
 */
export interface CitationSource {
  /** Stable identifier for the source (chunk id, document id, URL, etc.) */
  id?: string | number;
  /** Human-readable title, e.g. document filename. */
  title?: string;
  /** Alias for `title` — some backends use `name`. */
  name?: string;
  /** Optional URL to open the source in a new tab. */
  url?: string;
  /** Document id (from the knowledge base) for navigation. */
  document_id?: number;
  /** Knowledge base id the document belongs to. */
  knowledge_base_id?: number;
  /** Short snippet shown in the preview modal. */
  snippet?: string;
  /** Full content (used as a fallback for the snippet). */
  content?: string;
  /** Relevance score from retrieval (0-1). */
  score?: number;
  /** Free-form extra metadata. */
  [key: string]: any;
}

/**
 * Reference to an attachment the user uploaded alongside a chat message.
 * The content_text is sent inline to /chat/stream (V1 simplification).
 */
export interface AttachmentRef {
  file_id: string;
  name: string;
  size: number;
  mime_type: string;
  content_text: string;
}
