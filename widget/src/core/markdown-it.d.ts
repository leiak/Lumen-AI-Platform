/** Minimal type stub for markdown-it.
 *  The runtime package (v14.x) ships no .d.ts; this stub covers the
 *  surface we actually use in widget/src/core/markdown.ts.
 *  Kept local to the widget so we don't pollute the global @types tree. */
declare module "markdown-it" {
  interface Options {
    html?: boolean;
    linkify?: boolean;
    typographer?: boolean;
    highlight?: (str: string, lang: string) => string;
  }
  interface Utils {
    escapeHtml: (str: string) => string;
  }
  class MarkdownIt {
    constructor(options?: Options);
    render(src: string): string;
    utils: Utils;
  }
  export default MarkdownIt;
}
