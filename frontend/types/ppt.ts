// PPT JSON Schema 类型（与后端 lumen_schemas/ppt.py 共用同一结构）
export interface ChartData {
  type: "bar" | "line" | "pie";
  title: string;
  labels: string[];
  datasets: { name: string; values: number[] }[];
}

export interface Slide {
  layout: "title_only" | "title_content" | "two_column" | "blank" | "chart";
  title?: string;
  content?: string[];
  leftContent?: string[];
  rightContent?: string[];
  chart?: ChartData;
  notes?: string;
}

export interface PptSchema {
  title: string;
  subtitle?: string;
  author?: string;
  slides: Slide[];
}

export interface PptGenerateRequest {
  conversation_id: number;
  title?: string;
  content_range: 0 | 5 | 10 | 20;
  include_charts: boolean;
  style: "simple" | "business" | "academic";
  mode: "frontend" | "backend";
}

export interface PptTaskResponse {
  task_id: string;
  status: "pending" | "processing" | "completed" | "failed";
  file_url?: string;
  error?: string;
}

export interface PptConfig {
  title?: string;
  contentRange: 0 | 5 | 10 | 20;
  includeCharts: boolean;
  style: "simple" | "business" | "academic";
  mode: "frontend" | "backend";
}
