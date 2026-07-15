// frontend/types/tts.ts
// M35: TTS (text-to-speech) types.

export type TTSStatus = "pending" | "running" | "completed" | "failed" | "cancelled";
export type AudioFormat = "mp3" | "wav" | "opus" | "flac" | "aac";

export interface TTSJobListItem {
  id: number;
  model_config_id: number;
  voice: string;
  format: AudioFormat;
  status: TTSStatus;
  text_preview: string;
  duration_ms: number | null;
  char_count: number;
  created_at: string;
}

export interface TTSJobDetail extends TTSJobListItem {
  tenant_id: number;
  user_id: number;
  conversation_id: number | null;
  playbook_id: number | null;
  text: string;
  speed: string;
  file_path: string;
  file_size: number;
  mime_type: string;
  cost_usd: string | null;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
}

export interface TTSJobCreateRequest {
  model_config_id: number;
  text: string;
  voice?: string;
  speed?: number;
  format?: AudioFormat;
  playbook_id?: number | null;
  conversation_id?: number | null;
}

export interface TTSJobCreateResponse {
  id: number;
  status: TTSStatus;
  model_config_id: number;
  format: AudioFormat;
  voice: string;
  created_at: string | null;
}

export interface TTSVoice {
  id: string;
  name: string;
  language: string;
  gender: string;
}
