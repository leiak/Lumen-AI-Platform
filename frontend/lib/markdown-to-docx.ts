// frontend/lib/markdown-to-docx.ts
//
// Convert a markdown string to a .docx binary buffer.
//
// The chat UI keeps the raw markdown the LLM produced in
// ``Message.content`` and re-renders it with react-markdown. We
// don't try to walk the React tree — we re-parse the same source
// with remark-parse so the export is independent of the renderer
// and stable against future UI changes.
//
// Scope (per design spec 3.3):
//   supported:  headings h1-h3, paragraphs, bullet/numbered lists
//               (single level; nested lists flattened to plain text),
//               tables (cell content limited to paragraph + inline
//               formatting), fenced code blocks (monospace, light
//               grey background), inline code, **bold**, *italic*,
//               [text](url) links
//   degraded:   images -> "[图片: alt]" placeholder text;
//               blockquote -> indented italic paragraph;
//               any unknown node -> silently dropped
//
// Why Uint8Array: the Electron IPC channel serialises with
// structured clone, which handles plain number[] better than
// ArrayBuffer across versions.

import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkGfm from "remark-gfm";
import {
  Document,
  Packer,
  Paragraph,
  TextRun,
  HeadingLevel,
  Table,
  TableRow,
  TableCell,
  ExternalHyperlink,
  WidthType,
  ShadingType,
  BorderStyle,
} from "docx";
import type {
  Root,
  RootContent,
  PhrasingContent,
  Heading,
  Paragraph as MdastParagraph,
  List as MdastList,
  Code,
  Table as MdastTable,
  Blockquote,
  Link,
  Image as MdastImage,
} from "mdast";

// ---------- types ----------

type Block = Paragraph | Table;
type Inline = TextRun | ExternalHyperlink;

// Inheritable run-level formatting: bold/italic and the code
// font cascade through nested inline elements (e.g. **<code>x</code>**).
// text/break are per-run, not inheritable.
type InheritOpts = Pick<RunOpts, "bold" | "italics" | "font">;

interface RunOpts {
  text?: string;
  bold?: boolean;
  italics?: boolean;
  font?: string;
  break?: number;
}

// ---------- entry point ----------

export async function markdownToDocx(text: string): Promise<Uint8Array> {
  // remark-gfm extends standard CommonMark with GitHub-flavoured
  // extensions: pipe tables (`| a | b |\n|---|---|`), fenced code
  // blocks (already in CommonMark but gfm tightens the parsing),
  // strikethrough, autolinks, etc. Without it the chat-exported
  // markdown tables (which the LLM emits in GFM style) get
  // re-rendered as a single paragraph of pipe characters.
  const tree = unified()
    .use(remarkParse)
    .use(remarkGfm)
    .parse(text) as Root;
  const blocks = tree.children.flatMap(childToBlock);
  const doc = new Document({
    creator: "Lumen AI Platform",
    title: "Chat Export",
    sections: [{ children: blocks }],
  });
  return Packer.toBuffer(doc);
}

// ---------- block-level dispatch ----------

// Spacing in twentieths of a point (1pt = 20). docx default has
// zero spacing between paragraphs, which makes chat exports look
// cramped; bump it to ~6pt after each block and ~12pt before each
// heading so the document has visible breathing room.
const PARA_SPACING = { after: 120 } as const;
const HEADING_SPACING = { before: 240, after: 120 } as const;

function childToBlock(node: RootContent): Block[] {
  switch (node.type) {
    case "heading":
      return [headingToBlock(node)];
    case "paragraph":
      return [paragraphToBlock(node)];
    case "list":
      return listToBlock(node);
    case "code":
      return [codeBlockToBlock(node)];
    case "table":
      return [tableToBlock(node)];
    case "blockquote":
      return blockquoteToBlock(node);
    case "thematicBreak":
      // Markdown `---` separators were rendered as a literal "———"
      // text run, which read as visual noise between paragraphs in
      // chat exports. We don't actually want a separator here —
      // the spacing adjustments below already give the doc
      // breathing room — so drop the node entirely.
      return [];
    case "image":
      return [imageToBlock(node)];
    default:
      return [];
  }
}

function headingToBlock(node: Heading): Paragraph {
  return new Paragraph({
    heading: headingLevel(node.depth),
    spacing: HEADING_SPACING,
    children: [new TextRun({ text: plainText(node), bold: true })],
  });
}

function paragraphToBlock(node: MdastParagraph): Paragraph {
  return new Paragraph({
    spacing: PARA_SPACING,
    children: inlineToRuns(node.children),
  });
}

function listToBlock(node: MdastList): Paragraph[] {
  const isOrdered = !!node.ordered;
  const start = node.start ?? 1;
  return node.children.map((item, i) => {
    const prefix = isOrdered ? `${start + i}. ` : "• ";
    // mdast ListItem children are block-level; flatten to inline
    // runs by recursing into paragraphs and concatenating text.
    const inlineRuns: Inline[] = item.children.flatMap((child) => {
      if (child.type === "paragraph") {
        return inlineToRuns(child.children);
      }
      // For nested list / code in list item, fall back to plain text
      return [new TextRun({ text: plainText(child) })];
    });
    return new Paragraph({
      spacing: PARA_SPACING,
      children: [new TextRun({ text: prefix }), ...inlineRuns],
    });
  });
}

function codeBlockToBlock(node: Code): Paragraph {
  const lines = node.value.split("\n");
  const runs: TextRun[] = [];
  lines.forEach((line, i) => {
    runs.push(new TextRun({ text: line, font: "Consolas" }));
    if (i < lines.length - 1) {
      runs.push(new TextRun({ break: 1 }));
    }
  });
  return new Paragraph({
    spacing: PARA_SPACING,
    shading: { type: ShadingType.CLEAR, fill: "f5f5f5" },
    children: runs,
  });
}

function tableToBlock(node: MdastTable): Table {
  // Single thin grey border on every edge + every interior grid
  // line. Without this docx tables render with no borders, which
  // is the visual gap that made md tables look like plain text in
  // the original export.
  const border = {
    style: BorderStyle.SINGLE,
    size: 4, // 1/2 pt — thin
    color: "999999",
  } as const;
  const cellBorders = {
    top: border,
    bottom: border,
    left: border,
    right: border,
  } as const;
  const cellMargins = {
    top: 80, // 4pt
    bottom: 80,
    left: 100,
    right: 100,
  } as const;

  const rows = node.children.map((row, rowIdx) => {
    const isHeader = rowIdx === 0;
    return new TableRow({
      tableHeader: isHeader, // repeat on page break + bold cells below
      children: row.children.map((cell) => {
        // mdast TableCell children are PhrasingContent (inline
        // nodes like text/strong/em) — NOT block-level nodes like
        // paragraphs. Convert them directly to runs and wrap in a
        // single Paragraph; a cell can hold at most one paragraph
        // for clean inline formatting. bold the header-row runs
        // so the table visually distinguishes headers without
        // requiring markdown `**...**` around each label.
        const runs = isHeader
          ? inlineToRuns(cell.children, { bold: true })
          : inlineToRuns(cell.children);
        return new TableCell({
          borders: cellBorders,
          margins: cellMargins,
          shading: isHeader
            ? { type: ShadingType.CLEAR, fill: "f0f0f0", color: "auto" }
            : undefined,
          // docx requires every cell to have at least one block.
          children: [new Paragraph({ children: runs })],
        });
      }),
    });
  });
  return new Table({
    rows,
    width: { size: 100, type: WidthType.PERCENTAGE },
    borders: {
      top: border,
      bottom: border,
      left: border,
      right: border,
      insideHorizontal: border,
      insideVertical: border,
    },
    // Tables already provide visual separation; the per-paragraph
    // spacing we apply to body blocks makes the table look detached
    // from surrounding paragraphs, so we don't need an extra blank
    // line above/below it.
    margins: { top: 120, bottom: 120 },
  });
}

function blockquoteToBlock(node: Blockquote): Paragraph[] {
  // Per spec 3.3 ("blockquote -> indented italic paragraph"),
  // the inline runs inside a blockquote inherit italics on top
  // of whatever their own markdown formatting specifies.
  const result: Paragraph[] = [];
  for (const child of node.children) {
    if (child.type === "paragraph") {
      result.push(
        new Paragraph({
          spacing: PARA_SPACING,
          children: inlineToRuns(child.children, { italics: true }),
          indent: { left: 720 },
        }),
      );
    } else {
      // Non-paragraph blocks inside a blockquote are rare; fall
      // back to the normal converter and drop any non-Paragraph
      // results (e.g. nested tables).
      for (const b of childToBlock(child)) {
        if (b instanceof Paragraph) result.push(b);
      }
    }
  }
  return result;
}

function imageToBlock(node: MdastImage): Paragraph {
  return new Paragraph({
    spacing: PARA_SPACING,
    children: [
      new TextRun({
        text: `[图片: ${node.alt || node.url || "无描述"}]`,
        italics: true,
      }),
    ],
  });
}

// ---------- inline-level dispatch ----------

function inlineToRuns(
  nodes: PhrasingContent[],
  extra: InheritOpts = {},
): Inline[] {
  return nodes.flatMap((n) => inlineToRun(n, extra));
}

function inlineToRun(node: PhrasingContent, extra: InheritOpts = {}): Inline[] {
  switch (node.type) {
    case "text":
      return [new TextRun({ ...extra, text: node.value })];
    case "strong":
      return node.children.flatMap((c) =>
        inlineToRun(c, { ...extra, bold: true }),
      );
    case "emphasis":
      return node.children.flatMap((c) =>
        inlineToRun(c, { ...extra, italics: true }),
      );
    case "inlineCode":
      return [
        new TextRun({ ...extra, text: node.value, font: "Consolas" }),
      ];
    case "link":
      return linkToHyperlink(node, extra);
    case "break":
      return [new TextRun({ ...extra, break: 1 })];
    case "image":
      return [
        new TextRun({
          ...extra,
          text: `[图片: ${node.alt || node.url || ""}]`,
          italics: true,
        }),
      ];
    default:
      return [];
  }
}

function linkToHyperlink(
  node: Link,
  extra: InheritOpts = {},
): ExternalHyperlink[] {
  // Inherit parent formatting on the link's own text runs (e.g.
  // **<a href="...">click</a>** stays bold). External hyperlinks
  // themselves can't carry run-level formatting in the docx API
  // — but their child TextRuns can.
  const childRuns = node.children
    .flatMap((c) => inlineToRun(c, extra))
    .filter((r): r is TextRun => r instanceof TextRun);
  return [
    new ExternalHyperlink({
      link: node.url,
      children: childRuns,
    }),
  ];
}

// ---------- helpers ----------

function headingLevel(depth: number): (typeof HeadingLevel)[keyof typeof HeadingLevel] {
  if (depth <= 1) return HeadingLevel.HEADING_1;
  if (depth === 2) return HeadingLevel.HEADING_2;
  return HeadingLevel.HEADING_3;
}

// Extract plain text from any block, used for headings and link
// fallbacks. Walks the tree shallowly — does not recurse into
// nested block types.
function plainText(node: { type: string; children?: any[]; value?: string }): string {
  if (node.type === "text") return node.value ?? "";
  if (Array.isArray(node.children)) {
    return node.children.map(plainText).join("");
  }
  if (typeof node.value === "string") return node.value;
  return "";
}
