// frontend/types/eval.ts
// M37.3 — RAG evaluation dashboard aggregate types
//
// 与 run-level 类型(eval_run.ts)解耦 —— 这里是「跨多次 run 的 dashboard
// KPI / 趋势 / 对比汇总」数据形态。dashboard 主页 / 趋势图 / 跨 run 对比都用。
//
// 单一数据源约定:``EvalDashboardSummary`` = 一份完整的 dashboard payload,
// 由 ``services/eval.ts::getDashboardSummary()`` 返回。后端当前没有
// aggregate endpoint,所以这个 summary 是前端从 listRuns() 拿到的
// ``EvalRunListItem[]`` 客户端聚合出来的(见 services/eval.ts)。

import type {
  EvalRunListItem,
  EvalRunStatus,
} from "./eval_run";

/** KPI 卡片一行的数据。delta 字段可正可负(对比上次)。 */
export interface DashboardKPI {
  /** 卡片标题,中文简短,例:"本周评测次数 / Runs this week" */
  label: string;
  /** 主数值,字符串形式以便支持 "30 条" / "0.65" 混合。 */
  value: string;
  /** 对比 delta,字符串(可空),如 "+0.05" / "-2 次" */
  delta?: string | null;
  /** delta 语义方向:up=好 / down=差 / neutral=持平/无意义。 */
  deltaTone?: "up" | "down" | "neutral" | null;
  /** 卡片底部脚注,可空,例:"vs 上周" / "vs baseline" */
  hint?: string | null;
}

/** 单个时间桶的 KPI(趋势图横轴的一个点)。 */
export interface TrendPoint {
  /** ISO date,例:"2026-08-06" —— 用本地日期,不带时间。 */
  date: string;
  /** 该桶内 hit@5 平均(只统计 completed 且 metrics_json 有值的 run)。 */
  hit_at_5: number;
  /** 该桶内 mrr 平均。 */
  mrr: number;
  /** 该桶内完成的 run 数(算分母用)。 */
  run_count: number;
}

/** 单条 run 在趋势里的简记(趋势图悬浮 tooltip 用)。 */
export interface TrendRunRef {
  run_id: number;
  dataset_id: number;
  /** yyyy-MM-dd,跟 TrendPoint.date 同口径。 */
  date: string;
  hit_at_5: number;
  mrr: number;
}

/** 趋势序列:按 dataset 拆线。 */
export interface TrendSeries {
  dataset_id: number;
  dataset_name: string;
  points: TrendPoint[];
  runs: TrendRunRef[];
}

/** 最近一次「A vs B」对比的快照 — 主页 KPI 卡片第 3 张用。 */
export interface LatestCompareSnapshot {
  run_id_a: number;
  run_id_b: number;
  /** aggregate_delta["retrieval.hit_at_5"] —— 数值,前端格式化为字符串。 */
  hit_at_5_delta: number;
  aggregate_delta: Record<string, number>;
  /** 与上一个 completed run 对比的「赢家 metric」计数。 */
  winner_counts: { a: number; b: number; tie: number };
}

/** 整个 dashboard payload —— 主页一次拿全。 */
export interface EvalDashboardSummary {
  /** 顶部 3-4 张 KPI 卡片数据(按顺序渲染)。 */
  kpis: DashboardKPI[];
  /** 趋势图:按 dataset 拆成多条线,每条线 30 天 points。 */
  trend: TrendSeries[];
  /** 最近 run 列表(轻量,不含 metrics_json)。 */
  recent_runs: EvalRunListItem[];
  /** 上一次对比(如有)。 */
  latest_compare?: LatestCompareSnapshot | null;
  /** 数据生成时间(客户端时间)。 */
  generated_at: string;
}

/** trend 入参:回看 N 天,默认 30。 */
export interface DashboardSummaryParams {
  /** 回看天数,默认 30。 */
  lookback_days?: number;
  /** 趋势按 dataset 拆线时,最多返回前 N 个 dataset,默认 5。 */
  max_datasets?: number;
  /** 最近 run 列表条数上限,默认 20。 */
  recent_limit?: number;
}

/** 内部中间态:run 列表聚合时按状态分桶。 */
export interface RunBuckets {
  completed: EvalRunListItem[];
  running: EvalRunListItem[];
  failed: EvalRunListItem[];
  cancelled: EvalRunListItem[];
  pending: EvalRunListItem[];
}

/** 内部:client-side KPI 计算中间态(测试断言用)。 */
export interface DashboardKPIRaw {
  /** 本周(7 天)完成的 run 数。 */
  runs_this_week: number;
  /** 上周(再往前 7 天)完成的 run 数,做 delta。 */
  runs_last_week: number;
  /** 本周内完成 run 的 hit@5 平均。 */
  avg_hit_at_5_this_week: number;
  /** 上周 hit@5 平均。 */
  avg_hit_at_5_last_week: number;
  /** 全部已完成 run 的 hit@5 平均(兜底,周内无数据时用)。 */
  avg_hit_at_5_all_time: number;
}

/** 内部:client-side trend 聚合配置(测试断言用)。 */
export interface TrendBucket {
  date: string;
  hit_at_5_sum: number;
  mrr_sum: number;
  run_count: number;
}

/** status 转换工具返回值的窄类型,聚合时用。 */
export type TerminalStatus = Extract<
  EvalRunStatus,
  "completed" | "failed" | "cancelled"
>;
