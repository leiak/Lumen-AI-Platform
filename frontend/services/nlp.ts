// frontend/services/nlp.ts
import api from "./auth";

export interface NLPClassification {
  id: number;
  name: string;
  description?: string;
  keywords: string[];
  tenant_id?: number;
  created_at: string;
}

export interface NLPAnnotation {
  id: number;
  content: string;
  classification_id: number;
  tenant_id?: number;
  created_at: string;
}

export interface NLPQA {
  id: number;
  question: string;
  answer: string;
  tenant_id?: number;
  created_at: string;
}

/**
 * Hyperparameters that the user can tweak from the training config form.
 * They are passed in the train request body. The current backend service
 * applies fixed defaults, but sending them keeps the contract forward
 * compatible and lets the UI show what was requested.
 */
export interface NLPTrainingConfig {
  model?: string; // e.g. "tfidf-lr"
  epochs?: number;
  batch_size?: number;
  learning_rate?: number;
  max_features?: number;
  test_size?: number;
}

export interface TrainResult {
  status: string;
  model_path?: string;
  accuracy?: number;
  message: string;
  // Optional extended fields (e.g. from a future async/polling backend)
  job_id?: string;
  progress?: number;
  metrics?: Record<string, number>;
}

export interface PredictResult {
  predicted_class_id?: number;
  confidence?: number;
  error?: string;
}

export interface ParsedDatasetRow {
  content: string;
  classification_id?: number;
}

export const nlpApi = {
  // Classification
  listClassifications: (page = 1, pageSize = 10) =>
    api.get<any>(`/nlp/classification/?page=${page}&page_size=${pageSize}`),
  createClassification: (data: Partial<NLPClassification>) =>
    api.post<any>("/nlp/classification/", data),
  updateClassification: (id: number, data: Partial<NLPClassification>) =>
    api.put<any>(`/nlp/classification/${id}`, data),
  deleteClassification: (id: number) =>
    api.delete<any>(`/nlp/classification/${id}`),
  getClassification: (id: number) =>
    api.get<any>(`/nlp/classification/${id}`),

  // Annotation (text dataset)
  listAnnotations: (classificationId?: number, page = 1, pageSize = 100) =>
    api.get<any>(
      `/nlp/annotation/?classification_id=${classificationId || ""}&page=${page}&page_size=${pageSize}`
    ),
  createAnnotation: (data: Partial<NLPAnnotation>) =>
    api.post<any>("/nlp/annotation/", data),
  deleteAnnotation: (id: number) =>
    api.delete<any>(`/nlp/annotation/${id}`),

  // QA
  listQA: (page = 1, pageSize = 10) =>
    api.get<any>(`/nlp/qa/?page=${page}&page_size=${pageSize}`),
  createQA: (data: Partial<NLPQA>) =>
    api.post<any>("/nlp/qa/", data),
  updateQA: (id: number, data: Partial<NLPQA>) =>
    api.put<any>(`/nlp/qa/${id}`, data),
  deleteQA: (id: number) =>
    api.delete<any>(`/nlp/qa/${id}`),

  // Training
  train: (classificationId: number, config: NLPTrainingConfig = {}) =>
    api.post<any>("/nlp/train", {
      classification_id: classificationId,
      ...config,
    }),
  predict: (text: string, classificationId: number) =>
    api.post<any>("/nlp/predict", null, {
      params: { text, classification_id: classificationId },
    }),
};

/**
 * Parse a pasted text block (CSV, TSV or one-per-line) into dataset rows.
 * - If the block has a header line with a column named "text" / "content"
 *   (optionally with "label"/"class"/"classification_id") that header is
 *   used to map columns.
 * - Otherwise the whole line is treated as a single text row.
 * - If `defaultClassificationId` is provided, rows without a label column
 *   are bound to it.
 */
export function parseDatasetText(
  raw: string,
  defaultClassificationId?: number
): ParsedDatasetRow[] {
  const text = raw.replace(/\r\n?/g, "\n").trim();
  if (!text) return [];
  const lines = text.split("\n").filter((l) => l.trim().length > 0);
  if (lines.length === 0) return [];

  // Try CSV/TSV (very small parser — no quoted fields with commas)
  const sep = lines[0].includes("\t") ? "\t" : ",";

  const firstCols = lines[0].split(sep).map((c) => c.trim().toLowerCase());
  const hasHeader = firstCols.some((c) =>
    ["text", "content", "句子", "文本"].includes(c)
  );
  const labelIdx = firstCols.findIndex((c) =>
    ["label", "class", "classification", "classification_id", "标签", "分类"].includes(c)
  );
  const textIdx = hasHeader
    ? firstCols.findIndex((c) =>
        ["text", "content", "句子", "文本"].includes(c)
      )
    : -1;

  const dataLines = hasHeader ? lines.slice(1) : lines;

  return dataLines
    .map((line) => {
      const cols = line.split(sep);
      const content =
        textIdx >= 0 ? (cols[textIdx] || "").trim() : line.trim();
      let classification_id: number | undefined = defaultClassificationId;
      if (labelIdx >= 0) {
        const raw = (cols[labelIdx] || "").trim();
        const parsed = Number(raw);
        if (!Number.isNaN(parsed) && parsed > 0) {
          classification_id = parsed;
        } else if (raw) {
          // Treat as a name and try to resolve later — but here we keep the
          // raw string and the caller can resolve it. For simplicity, drop it
          // and rely on the default classification.
          classification_id = defaultClassificationId;
        }
      }
      return { content, classification_id };
    })
    .filter((row) => row.content.length > 0);
}
