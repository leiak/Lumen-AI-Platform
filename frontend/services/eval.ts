// frontend/services/eval.ts
// M37.3 — RAG evaluation dashboard HTTP service + 客户端聚合
//
// 后端当前没有 dashboard aggregate endpoint(M37.2 只 ship 了 5 个 run
// endpoint + 1 compare endpoint,plan §T18 也未要求新增)。
// 所以这里采用「**前端客户端聚合**」策略:
//
//   1. GET /api/v1/eval/runs/?page_size=20    拉最近 run 列表(轻量,无 metrics_json)
//   2. 对其中 status=completed 的 run 并行 GET /api/v1/eval/runs/{id}
//      拿 metrics_json(Promise.allSettled 容错,失败的当 null)
//   3. 客户端聚合 → EvalDashboardSummary
//
// 跑 20 次以下评测时:21 个并行 HTTP 请求 ~500ms,可以接受。超过 20 个
// run 后只看最近 20 个的 trend,够用。后续若跑评测密集可加 backend
// aggregate endpoint(plan §CP7+ follow-up)。

import api from "./auth";
import { getRun, listRuns, compareRuns } from "./eval_run";
import type {
  EvalRunDetail,
  EvalRunListItem,
} from "@/types/eval_run";
import type {
  DashboardKPI,
  DashboardKPIRaw,
  DashboardSummaryParams,
  EvalDashboardSummary,
  LatestCompareSnapshot,
  RunBuckets,
  TerminalStatus,
  TrendBucket,
  TrendPoint,
  TrendRunRef,
  TrendSeries,
} from "@/types/eval";

export type {
  DashboardKPI,
  DashboardKPIRaw,
  DashboardSummaryParams,
  EvalDashboardSummary,
  LatestCompareSnapshot,
  RunBuckets,
  TerminalStatus,
  TrendBucket,
  TrendPoint,
  TrendRunRef,
  TrendSeries,
} from "@/types/eval";

const DEFAULT_LOOKBACK_DAYS = 30;
const DEFAULT_MAX_DATASETS = 5;
const DEFAULT_RECENT_LIMIT = 20;

// ===========================================================================
// 聚合纯函数 —— 易测试、不依赖 HTTP
// ===========================================================================

/** ISO timestamp → yyyy-MM-dd (本地时区)。空值返空串。 */
export function isoToLocalDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

/** 现在往前 N 天的 yyyy-MM-dd 数组(包含今天),长度 = N+1。 */
export function lastNDates(n: number, today: Date = new Date()): string[] {
  const out: string[] = [];
  for (let i = n; i >= 0; i -= 1) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    out.push(`${yyyy}-${mm}-${dd}`);
  }
  return out;
}

/** 把 run 列表按状态分桶。 */
export function bucketRunsByStatus(runs: EvalRunListItem[]): RunBuckets {
  const buckets: RunBuckets = {
    completed: [],
    running: [],
    failed: [],
    cancelled: [],
    pending: [],
  };
  for (const r of runs) {
    if (r.status === "completed") buckets.completed.push(r);
    else if (r.status === "running") buckets.running.push(r);
    else if (r.status === "failed") buckets.failed.push(r);
    else if (r.status === "cancelled") buckets.cancelled.push(r);
    else buckets.pending.push(r);
  }
  return buckets;
}

/** N 天前的 Date(包含 time = 00:00:00 本地)。 */
function daysAgo(n: number, today: Date = new Date()): Date {
  const d = new Date(today);
  d.setDate(d.getDate() - n);
  return d;
}

/** 仅看 finished_at 在 last NDays 之内的 completed run。 */
export function recentCompletedRuns(
  runs: EvalRunListItem[],
  days: number,
  today: Date = new Date(),
): EvalRunListItem[] {
  const cutoff = daysAgo(days, today).getTime();
  return runs.filter(
    (r) =>
      r.status === "completed" &&
      r.finished_at !== null &&
      new Date(r.finished_at).getTime() >= cutoff,
  );
}

/** 计算本周 / 上周 KPI 原始数值(测试断言用)。 */
export function computeKPIRaw(
  runs: EvalRunListItem[],
  metricsByRun: Record<number, Pick<EvalRunDetail, "metrics_json"> | null>,
  today: Date = new Date(),
): DashboardKPIRaw {
  // 本周 = 最近 7 天(含今天);上周 = 7-14 天前。
  const nowMs = today.getTime();
  const weekCutoff = nowMs - 7 * 86_400_000;
  const lastWeekCutoff = nowMs - 14 * 86_400_000;

  let runs_this_week = 0;
  let runs_last_week = 0;
  let hit5_this_sum = 0;
  let hit5_this_n = 0;
  let hit5_last_sum = 0;
  let hit5_last_n = 0;
  let hit5_all_sum = 0;
  let hit5_all_n = 0;

  for (const r of runs) {
    if (r.status !== "completed" || !r.finished_at) continue;
    const ms = new Date(r.finished_at).getTime();
    const metrics = metricsByRun[r.id];
    const hit5 =
      metrics?.metrics_json?.retrieval?.hit_at_5 ?? null;

    if (ms >= weekCutoff) {
      runs_this_week += 1;
      if (hit5 !== null) {
        hit5_this_sum += hit5;
        hit5_this_n += 1;
      }
    } else if (ms >= lastWeekCutoff) {
      runs_last_week += 1;
      if (hit5 !== null) {
        hit5_last_sum += hit5;
        hit5_last_n += 1;
      }
    }
    if (hit5 !== null) {
      hit5_all_sum += hit5;
      hit5_all_n += 1;
    }
  }

  return {
    runs_this_week,
    runs_last_week,
    avg_hit_at_5_this_week:
      hit5_this_n > 0 ? hit5_this_sum / hit5_this_n : 0,
    avg_hit_at_5_last_week:
      hit5_last_n > 0 ? hit5_last_sum / hit5_last_n : 0,
    avg_hit_at_5_all_time: hit5_all_n > 0 ? hit5_all_sum / hit5_all_n : 0,
  };
}

/** 把 KPI 原始数值包成前端用的 DashboardKPI 卡片(4 张)。 */
export function buildKPICards(raw: DashboardKPIRaw): DashboardKPI[] {
  const avg = raw.avg_hit_at_5_this_week || raw.avg_hit_at_5_all_time;
  const lastWeekAvg =
    raw.avg_hit_at_5_last_week || raw.avg_hit_at_5_all_time;

  // delta: 本周 - 上周,转百分比字符串
  const hit5Delta =
    raw.avg_hit_at_5_this_week > 0 && raw.avg_hit_at_5_last_week > 0
      ? raw.avg_hit_at_5_this_week - raw.avg_hit_at_5_last_week
      : null;
  const hit5DeltaStr =
    hit5Delta === null
      ? null
      : `${hit5Delta >= 0 ? "+" : ""}${(hit5Delta * 100).toFixed(1)}%`;
  const hit5DeltaTone: DashboardKPI["deltaTone"] =
    hit5Delta === null
      ? "neutral"
      : hit5Delta > 0
        ? "up"
        : hit5Delta < 0
          ? "down"
          : "neutral";

  // runs delta
  const runsDelta = raw.runs_this_week - raw.runs_last_week;
  const runsDeltaStr =
    raw.runs_last_week === 0 && raw.runs_this_week === 0
      ? null
      : `${runsDelta >= 0 ? "+" : ""}${runsDelta} 次`;
  const runsDeltaTone: DashboardKPI["deltaTone"] =
    runsDelta === 0
      ? "neutral"
      : runsDelta > 0
        ? "up"
        : "down";

  return [
    {
      label: "本周评测次数 / Runs this week",
      value: `${raw.runs_this_week} 次`,
      delta: runsDeltaStr,
      deltaTone: runsDeltaTone,
      hint: `vs 上周 ${raw.runs_last_week} 次`,
    },
    {
      label: "本周平均 Hit@5 / Avg Hit@5",
      value: avg > 0 ? avg.toFixed(3) : "—",
      delta: hit5DeltaStr,
      deltaTone: hit5DeltaTone,
      hint:
        lastWeekAvg > 0
          ? `vs 上周 ${lastWeekAvg.toFixed(3)}`
          : "无对比数据",
    },
    {
      label: "历史平均 Hit@5 / All-time Hit@5",
      value:
        raw.avg_hit_at_5_all_time > 0
          ? raw.avg_hit_at_5_all_time.toFixed(3)
          : "—",
      delta: null,
      deltaTone: "neutral",
      hint: "全部已完成 run 的 hit@5 均值",
    },
    {
      label: "本周活跃评测者 / Active",
      value: "—",
      delta: null,
      deltaTone: "neutral",
      hint: "M37.3 当前不统计(留给 follow-up)",
    },
  ];
}

/** 按 (dataset_id, date) 聚合 hit@5 / mrr。 */
export function buildTrendBuckets(
  runs: EvalRunListItem[],
  metricsByRun: Record<number, Pick<EvalRunDetail, "metrics_json"> | null>,
  lookbackDays: number,
  today: Date = new Date(),
): Map<string, TrendBucket> {
  const cutoffMs = daysAgo(lookbackDays, today).getTime();
  const buckets = new Map<string, TrendBucket>();

  for (const r of runs) {
    if (r.status !== "completed" || !r.finished_at) continue;
    const ms = new Date(r.finished_at).getTime();
    if (ms < cutoffMs) continue;
    const date = isoToLocalDate(r.finished_at);
    if (!date) continue;
    const metrics = metricsByRun[r.id];
    const hit5 = metrics?.metrics_json?.retrieval?.hit_at_5 ?? null;
    const mrr = metrics?.metrics_json?.retrieval?.mrr ?? null;
    const key = `${r.dataset_id}::${date}`;
    const existing = buckets.get(key) ?? {
      date,
      hit_at_5_sum: 0,
      mrr_sum: 0,
      run_count: 0,
    };
    if (hit5 !== null) {
      existing.hit_at_5_sum += hit5;
    }
    if (mrr !== null) {
      existing.mrr_sum += mrr;
    }
    existing.run_count += 1;
    buckets.set(key, existing);
  }
  return buckets;
}

/** 把 buckets + dataset 名映射 → TrendSeries[],每天补 0 点保连续。 */
export function buildTrendSeries(
  buckets: Map<string, TrendBucket>,
  datasetNameById: Record<number, string>,
  lookbackDays: number,
  maxDatasets: number,
  today: Date = new Date(),
): TrendSeries[] {
  const dates = lastNDates(lookbackDays, today);

  // 1. 按 dataset 分组 bucket key 头
  const byDataset = new Map<number, Map<string, TrendBucket>>();
  for (const [key, b] of buckets) {
    const sep = key.indexOf("::");
    if (sep < 0) continue;
    const dsIdStr = key.slice(0, sep);
    const date = key.slice(sep + 2);
    const dsId = Number(dsIdStr);
    if (!Number.isFinite(dsId)) continue;
    let m = byDataset.get(dsId);
    if (!m) {
      m = new Map();
      byDataset.set(dsId, m);
    }
    m.set(date, b);
  }

  // 2. 按 dataset 总 run_count 排序,取前 maxDatasets
  const sortedDsIds = Array.from(byDataset.keys())
    .map((id) => {
      const m = byDataset.get(id);
      let total = 0;
      m?.forEach((b) => {
        total += b.run_count;
      });
      return { id, total };
    })
    .sort((a, b) => b.total - a.total)
    .slice(0, maxDatasets)
    .map((x) => x.id);

  // 3. 拼 series
  const series: TrendSeries[] = [];
  for (const dsId of sortedDsIds) {
    const dsBuckets = byDataset.get(dsId);
    if (!dsBuckets) continue;
    const points: TrendPoint[] = [];
    const runs: TrendRunRef[] = [];
    for (const date of dates) {
      const b = dsBuckets.get(date);
      if (!b) {
        points.push({ date, hit_at_5: 0, mrr: 0, run_count: 0 });
        continue;
      }
      points.push({
        date,
        hit_at_5: b.run_count > 0 ? b.hit_at_5_sum / b.run_count : 0,
        mrr: b.run_count > 0 ? b.mrr_sum / b.run_count : 0,
        run_count: b.run_count,
      });
    }
    series.push({
      dataset_id: dsId,
      dataset_name: datasetNameById[dsId] ?? `dataset #${dsId}`,
      points,
      runs,
    });
  }
  return series;
}

/** 把 listRuns() 结果 + detail fetch 结果聚合成 EvalDashboardSummary。 */
export function aggregateRunsForDashboard(
  runs: EvalRunListItem[],
  metricsByRun: Record<number, Pick<EvalRunDetail, "metrics_json"> | null>,
  datasetNameById: Record<number, string>,
  params: DashboardSummaryParams = {},
  today: Date = new Date(),
): EvalDashboardSummary {
  const lookback = params.lookback_days ?? DEFAULT_LOOKBACK_DAYS;
  const maxDs = params.max_datasets ?? DEFAULT_MAX_DATASETS;

  const rawKpi = computeKPIRaw(runs, metricsByRun, today);
  const kpis = buildKPICards(rawKpi);

  const buckets = buildTrendBuckets(runs, metricsByRun, lookback, today);
  const trend = buildTrendSeries(buckets, datasetNameById, lookback, maxDs, today);

  // recent_runs = 全部列表(已按时间倒序由后端返)+ 加 metrics 摘要进附注
  return {
    kpis,
    trend,
    recent_runs: runs,
    latest_compare: null, // 由调用方可选填充
    generated_at: today.toISOString(),
  };
}

// ===========================================================================
// HTTP service —— 拉数据 + 客户端聚合
// ===========================================================================

/** listRuns 默认 sort 是按 created_at desc;如果后端改了这里要补 sort 参数。 */
async function fetchRecentRuns(limit: number): Promise<EvalRunListItem[]> {
  const res = await listRuns({ page: 1, page_size: limit });
  return res.items;
}

/** 并行拿 completed run 的 detail(Promise.allSettled 容错)。 */
async function fetchMetricsForCompletedRuns(
  runs: EvalRunListItem[],
): Promise<Record<number, Pick<EvalRunDetail, "metrics_json"> | null>> {
  const completed = runs.filter((r) => r.status === "completed");
  const settled = await Promise.allSettled(
    completed.map((r) => getRun(r.id)),
  );
  const out: Record<number, Pick<EvalRunDetail, "metrics_json"> | null> = {};
  completed.forEach((r, i) => {
    const s = settled[i];
    if (s.status === "fulfilled") {
      out[r.id] = { metrics_json: s.value.metrics_json ?? null };
    } else {
      out[r.id] = null;
    }
  });
  return out;
}

/** 拿 dataset 名映射(为了 trend chart 显示 dataset_name)。 */
async function fetchDatasetNames(
  datasetIds: number[],
): Promise<Record<number, string>> {
  const { getDataset } = await import("./eval_dataset");
  const out: Record<number, string> = {};
  const settled = await Promise.allSettled(
    datasetIds.map((id) => getDataset(id)),
  );
  datasetIds.forEach((id, i) => {
    const s = settled[i];
    if (s.status === "fulfilled") {
      out[id] = s.value.name ?? `dataset #${id}`;
    } else {
      out[id] = `dataset #${id}`;
    }
  });
  return out;
}

/**
 * 拿完整 dashboard payload。
 *
 * 数据流:
 *   listRuns(limit=20) → completed run 并行 getRun(id) → 客户端聚合。
 *
 * @param params.lookback_days 趋势图回看天数(默认 30)
 * @param params.max_datasets 趋势按 dataset 拆线时最多返回前 N 个 dataset(默认 5)
 * @param params.recent_limit 最近 run 列表上限(默认 20)
 */
export async function getDashboardSummary(
  params: DashboardSummaryParams = {},
): Promise<EvalDashboardSummary> {
  const limit = params.recent_limit ?? DEFAULT_RECENT_LIMIT;
  const recentRuns = await fetchRecentRuns(limit);
  const metricsByRun = await fetchMetricsForCompletedRuns(recentRuns);
  const datasetIds = Array.from(new Set(recentRuns.map((r) => r.dataset_id)));
  const datasetNameById = await fetchDatasetNames(datasetIds);

  const summary = aggregateRunsForDashboard(
    recentRuns,
    metricsByRun,
    datasetNameById,
    params,
  );

  // 顺手补 latest_compare:如果有 2+ completed run,挑最新两个调 compareRuns
  const completed = recentRuns.filter((r) => r.status === "completed");
  if (completed.length >= 2) {
    const sortedByFinished = [...completed].sort((a, b) => {
      const fa = a.finished_at ? new Date(a.finished_at).getTime() : 0;
      const fb = b.finished_at ? new Date(b.finished_at).getTime() : 0;
      return fb - fa;
    });
    const b = sortedByFinished[0];
    const a = sortedByFinished[1];
    try {
      const compare = await compareRuns({ run_id_a: a.id, run_id_b: b.id });
      let winA = 0;
      let winB = 0;
      let tie = 0;
      for (const w of compare.winners) {
        if (w.winner === "a") winA += 1;
        else if (w.winner === "b") winB += 1;
        else tie += 1;
      }
      summary.latest_compare = {
        run_id_a: compare.run_id_a,
        run_id_b: compare.run_id_b,
        hit_at_5_delta:
          compare.aggregate_delta?.["retrieval.hit_at_5"] ?? 0,
        aggregate_delta: compare.aggregate_delta,
        winner_counts: { a: winA, b: winB, tie },
      } satisfies LatestCompareSnapshot;
    } catch {
      // compare 失败(如不同 dataset)→ 静默,保持 null
    }
  }

  return summary;
}

/**
 * 取趋势序列 —— getDashboardSummary 的子集,dashboard trend 图表单独刷新用。
 *
 * 与 getDashboardSummary 不同:这只调 listRuns + 不补 latest_compare,省一个
 * compareRuns 调用。
 */
export async function getTrendSeries(
  params: DashboardSummaryParams = {},
): Promise<TrendSeries[]> {
  const limit = params.recent_limit ?? DEFAULT_RECENT_LIMIT;
  const recentRuns = await fetchRecentRuns(limit);
  const metricsByRun = await fetchMetricsForCompletedRuns(recentRuns);
  const datasetIds = Array.from(new Set(recentRuns.map((r) => r.dataset_id)));
  const datasetNameById = await fetchDatasetNames(datasetIds);
  const lookback = params.lookback_days ?? DEFAULT_LOOKBACK_DAYS;
  const maxDs = params.max_datasets ?? DEFAULT_MAX_DATASETS;
  const buckets = buildTrendBuckets(recentRuns, metricsByRun, lookback);
  return buildTrendSeries(buckets, datasetNameById, lookback, maxDs);
}

/**
 * 取最近两次 completed run 的 compare 快照,主页「上次基线对比」KPI 用。
 *
 * @returns null 当不足 2 个 completed run,或 compare 失败时(静默)。
 */
export async function getLatestCompareSnapshot(): Promise<LatestCompareSnapshot | null> {
  try {
    const recent = await fetchRecentRuns(DEFAULT_RECENT_LIMIT);
    const completed = recent
      .filter((r) => r.status === "completed")
      .sort((a, b) => {
        const fa = a.finished_at ? new Date(a.finished_at).getTime() : 0;
        const fb = b.finished_at ? new Date(b.finished_at).getTime() : 0;
        return fb - fa;
      });
    if (completed.length < 2) return null;
    const [b, a] = completed;
    const compare = await compareRuns({ run_id_a: a.id, run_id_b: b.id });
    let winA = 0;
    let winB = 0;
    let tie = 0;
    for (const w of compare.winners) {
      if (w.winner === "a") winA += 1;
      else if (w.winner === "b") winB += 1;
      else tie += 1;
    }
    return {
      run_id_a: compare.run_id_a,
      run_id_b: compare.run_id_b,
      hit_at_5_delta: compare.aggregate_delta?.["retrieval.hit_at_5"] ?? 0,
      aggregate_delta: compare.aggregate_delta,
      winner_counts: { a: winA, b: winB, tie },
    };
  } catch {
    return null;
  }
}

// 重新导出基础 api 给外部测试 mock 用
export { api };
