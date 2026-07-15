import PptxGenJS from "pptxgenjs";
import type { PptSchema, ChartData } from "@/types/ppt";

// 与后端 lumen_tasks/ppt_task.py StyleTheme 镜像同一套主题定义。
export interface StyleTheme {
  bg: string;
  title: string;
  body: string;
  accent: string;
  accentSoft: string;
  titleFont: string;
  bodyFont: string;
  titleSize: number;
  bodySize: number;
  bulletChar: string;
  chartPalette: string[];
  showTopBar: boolean;
  showLeftAccent: boolean;
  showDecorativeLine: boolean;
  pageNumberFormat: "dotted" | "slash" | "roman";
}

const THEMES: Record<string, StyleTheme> = {
  simple: {
    bg: "FFFFFF",
    title: "1A1A1A",
    body: "444444",
    accent: "888888",
    accentSoft: "CCCCCC",
    titleFont: "Calibri Light",
    bodyFont: "Calibri Light",
    titleSize: 28,
    bodySize: 18,
    bulletChar: "—",
    chartPalette: ["595959", "808080", "A6A6A6", "BFBFBF", "D9D9D9", "8C8C8C"],
    showTopBar: false,
    showLeftAccent: false,
    showDecorativeLine: false,
    pageNumberFormat: "dotted",
  },
  business: {
    bg: "FFFFFF",
    title: "1F4E79",
    body: "333333",
    accent: "2C5A8A",
    accentSoft: "4472C4",
    titleFont: "Calibri",
    bodyFont: "Calibri",
    titleSize: 28,
    bodySize: 18,
    bulletChar: "▪",
    chartPalette: ["1F4E79", "ED7D31", "70AD47", "FFC000", "4472C4", "264478"],
    showTopBar: true,
    showLeftAccent: true,
    showDecorativeLine: true,
    pageNumberFormat: "slash",
  },
  academic: {
    bg: "FAFAF5",
    title: "00328B",
    body: "222222",
    accent: "00328B",
    accentSoft: "808000",
    titleFont: "Times New Roman",
    bodyFont: "Times New Roman",
    titleSize: 28,
    bodySize: 18,
    bulletChar: "§",
    chartPalette: ["4682B4", "B22222", "808000", "CD853F", "2F4F4F", "8B4513"],
    showTopBar: true,
    showLeftAccent: false,
    showDecorativeLine: false,
    pageNumberFormat: "roman",
  },
};

export function styleTheme(style: string): StyleTheme {
  return THEMES[style] ?? THEMES.simple;
}

function toRoman(n: number): string {
  const vals: [number, string][] = [
    [1000, "M"], [900, "CM"], [500, "D"], [400, "CD"], [100, "C"],
    [90, "XC"], [50, "L"], [40, "XL"], [10, "X"], [9, "IX"],
    [5, "V"], [4, "IV"], [1, "I"],
  ];
  let out = "";
  for (const [v, s] of vals) {
    while (n >= v) {
      out += s;
      n -= v;
    }
  }
  return out || "I";
}

export function formatPageNumber(fmt: string, num: number, total: number): string {
  if (fmt === "dotted") return `${String(num).padStart(2, "0")}.`;
  if (fmt === "roman") return `${toRoman(num)} / ${toRoman(total)}`;
  return `${num}/${total}`;
}

function bulletOpt(theme: StyleTheme) {
  // 把主题 bullet 字符转成 pptxgenjs characterCode(4 位 hex 码点)
  const code = (theme.bulletChar.codePointAt(0) ?? 0x2022)
    .toString(16)
    .toUpperCase()
    .padStart(4, "0");
  return { characterCode: code };
}

function buildChart(
  slide: ReturnType<PptxGenJS["addSlide"]>,
  chartData: ChartData,
  theme: StyleTheme
) {
  const chartTypeMap: Record<string, number> = {
    bar: (PptxGenJS as any).Charts.Bar,
    line: (PptxGenJS as any).Charts.Line,
    pie: (PptxGenJS as any).Charts.Pie,
  };
  const chartType = chartTypeMap[chartData.type] ?? (PptxGenJS as any).Charts.Bar;

  const data = chartData.datasets.map((ds) => ({
    name: ds.name,
    labels: chartData.labels,
    values: ds.values,
  }));

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (slide as any).addChart(chartType, data, {
    showTitle: true,
    title: chartData.title,
    titleColor: theme.title,
    titleFontFace: theme.titleFont,
    titleFontSize: 14,
    titleBold: true,
    chartColors: theme.chartPalette,
    x: 1,
    y: 1.5,
    w: 11,
    h: 5,
    showLegend: true,
    legendPos: "b",
    legendFontFace: theme.bodyFont,
  });
}

export async function renderPpt(schema: PptSchema, style: string): Promise<Uint8Array> {
  const theme = styleTheme(style);
  const pptx = new PptxGenJS();
  pptx.layout = "LAYOUT_WIDE";
  pptx.author = schema.author || "Lumen AI";
  pptx.title = schema.title;

  const total = schema.slides.length;

  schema.slides.forEach((slideData, idx) => {
    const slide = pptx.addSlide();
    slide.background = { color: theme.bg };

    // 顶部 / 底部装饰条（依主题）
    if (theme.showTopBar) {
      slide.addShape("rect", { x: 0, y: 0, w: "100%", h: 0.12, fill: { color: theme.accent } });
      if (theme.pageNumberFormat === "roman") {
        // academic 顶部双线
        slide.addShape("rect", { x: 0, y: 0.16, w: "100%", h: 0.05, fill: { color: theme.accent } });
      }
      slide.addShape("rect", { x: 0, y: 7.38, w: "100%", h: 0.12, fill: { color: theme.accent } });
    }

    // 页码（右下角）
    slide.addText(formatPageNumber(theme.pageNumberFormat, idx + 1, total), {
      x: 12.3, y: 7.0, w: 0.9, h: 0.35,
      fontSize: 10, color: theme.body, align: "right", fontFace: theme.bodyFont,
    });

    if (slideData.layout === "title_only") {
      slide.addText(slideData.title || schema.title, {
        x: 0.5, y: 2.0, w: 11.333, h: 1.4,
        fontSize: 44, bold: true, color: theme.title, align: "center", fontFace: theme.titleFont,
      });
      let yOffset = 3.3;
      if (theme.showDecorativeLine) {
        slide.addShape("rect", { x: 5.5, y: 3.15, w: 2.333, h: 0.06, fill: { color: theme.accentSoft } });
      }
      if (schema.subtitle) {
        slide.addText(schema.subtitle, {
          x: 0.5, y: 3.3, w: 11.333, h: 0.7,
          fontSize: 22, color: theme.body, align: "center", fontFace: theme.bodyFont,
        });
        yOffset = 4.0;
      }
      if (slideData.content && slideData.content.length > 0) {
        const items = slideData.content.map((item) => ({
          text: `${theme.bulletChar} ${item}`,
          options: { fontSize: 18, color: theme.body, fontFace: theme.bodyFont, breakLine: true },
        }));
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        slide.addText(items as any, { x: 0.5, y: yOffset, w: 11.333, h: 2.5, valign: "top", align: "center" });
      }
    } else if (slideData.layout === "blank") {
      slide.addText("谢谢观看", {
        x: 0.5, y: 3, w: 11.333, h: 1.5,
        fontSize: 44, bold: true, color: theme.title, align: "center", fontFace: theme.titleFont,
      });
      if (theme.showDecorativeLine) {
        slide.addShape("rect", { x: 5, y: 4.5, w: 3.333, h: 0.06, fill: { color: theme.accentSoft } });
      }
    } else if (slideData.layout === "chart") {
      if (slideData.title) {
        slide.addText(slideData.title, {
          x: 0.5, y: 0.3, w: 11.333, h: 0.8,
          fontSize: 28, bold: true, color: theme.title, fontFace: theme.titleFont,
        });
      }
      if (slideData.chart) {
        buildChart(slide, slideData.chart, theme);
      }
    } else {
      // 左侧竖条（依主题）
      if (theme.showLeftAccent) {
        slide.addShape("rect", { x: 0.4, y: 0.4, w: 0.08, h: 1.0, fill: { color: theme.accent } });
      }
      if (slideData.title) {
        slide.addText(slideData.title, {
          x: theme.showLeftAccent ? 0.6 : 0.5, y: 0.3, w: 11.333, h: 0.9,
          fontSize: 28, bold: true, color: theme.title, fontFace: theme.titleFont,
        });
      }
      if (slideData.layout === "title_content" && slideData.content) {
        const items = slideData.content.map((item) => ({
          text: item,
          options: { bullet: bulletOpt(theme), fontSize: 18, color: theme.body, fontFace: theme.bodyFont, breakLine: true },
        }));
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        slide.addText(items as any, { x: 0.5, y: 1.3, w: 11.333, h: 5.5, valign: "top" });
      } else if (slideData.layout === "two_column") {
        const leftItems = (slideData.leftContent || []).map((item) => ({
          text: item,
          options: { bullet: bulletOpt(theme), fontSize: 16, color: theme.body, fontFace: theme.bodyFont, breakLine: true },
        }));
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        slide.addText(leftItems as any, { x: 0.5, y: 1.3, w: 5.0, h: 5.5, valign: "top" });
        const rightItems = (slideData.rightContent || []).map((item) => ({
          text: item,
          options: { bullet: bulletOpt(theme), fontSize: 16, color: theme.body, fontFace: theme.bodyFont, breakLine: true },
        }));
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        slide.addText(rightItems as any, { x: 6.0, y: 1.3, w: 5.0, h: 5.5, valign: "top" });
      }
    }

    if (slideData.notes) {
      slide.addNotes(slideData.notes);
    }
  });

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const result = await (pptx as any).write({ outputType: "arraybuffer" });
  return new Uint8Array(result);
}
