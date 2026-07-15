// frontend/types/subtitle.ts
// M35: subtitle types.

export interface SubtitleListItem {
  id: number;
  language: string;
  cue_count: number;
  duration_ms: number;
  char_count: number;
  tts_job_id: number | null;
  created_at: string;
}

export interface SubtitleDetail extends SubtitleListItem {
  tenant_id: number;
  user_id: number;
  source_type: string;
  format: string;
  content: string;
}

export interface SubtitleCreateRequest {
  script: string;
  total_duration_ms: number;
  language?: string;
  tts_job_id?: number | null;
}
