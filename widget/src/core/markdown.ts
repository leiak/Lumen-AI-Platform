/** Markdown entry point.
 *
 *  Imports the markdown-it engine + a 6-language highlight.js bundle
 *  synchronously so the call site (`renderMarkdown`) is one line and
 *  Lit's render path stays synchronous. Bundle budget is 200KB; the
 *  current cost is ~225KB which is over budget but accepted by the
 *  size guard in Task 32 (which raises the budget to 256KB).
 *
 *  Tree-shaking note: highlight.js's `lib/core` is a thin facade —
 *  it does not pull all languages, only the ones we register. The
 *  6 language definitions add roughly 80KB. The remaining cost is
 *  markdown-it's parser + linkify + typographer plugins. If a
 *  future task needs to slim this further, the standard pattern is
 *  a dynamic `import()` inside LumenChat._renderMessage and a fallback
 *  to plain text for the first paint. */

import MarkdownIt from "markdown-it";
import hljs from "highlight.js/lib/core";
import ts from "highlight.js/lib/languages/typescript";
import js from "highlight.js/lib/languages/javascript";
import py from "highlight.js/lib/languages/python";
import json from "highlight.js/lib/languages/json";
import sql from "highlight.js/lib/languages/sql";
import bash from "highlight.js/lib/languages/bash";

hljs.registerLanguage("typescript", ts);
hljs.registerLanguage("javascript", js);
hljs.registerLanguage("python", py);
hljs.registerLanguage("json", json);
hljs.registerLanguage("sql", sql);
hljs.registerLanguage("bash", bash);

const md = new MarkdownIt({
  html: false,  // XSS guard — never render raw HTML from assistant output
  linkify: true,
  typographer: true,
  highlight(str: string, lang: string): string {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return `<pre class="hljs"><code>${hljs.highlight(str, { language: lang }).value}</code></pre>`;
      } catch {}
    }
    return `<pre class="hljs"><code>${md.utils.escapeHtml(str)}</code></pre>`;
  },
});

export function renderMarkdown(src: string): string {
  return md.render(src);
}
