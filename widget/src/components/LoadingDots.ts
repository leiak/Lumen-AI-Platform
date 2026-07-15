/** <lc-loading-dots> — 3-dot blinking loading indicator.
 *
 *  A tiny self-contained component used in the chat input area to
 *  indicate that the assistant is generating a response. The three
 *  dots blink in sequence via CSS keyframes (no JS animation loop)
 *  so the cost is essentially one DOM render + a CSS animation.
 *
 *  Color is inherited from `currentColor`, so the parent can place
 *  the indicator in any text context and it picks up the surrounding
 *  foreground automatically.
 *
 *  NOTE: This component is the extracted counterpart of the inline
 *  pending indicator that currently lives in `LumenChat.ts`. It is
 *  shipped standalone in this task (per the plan's escape hatch) so
 *  a future refactor can adopt it without re-doing the extraction
 *  work. Adoption itself is out of scope here.
 */
import { LitElement, html, css } from "lit";
import { customElement } from "lit/decorators.js";

@customElement("lc-loading-dots")
export class LoadingDots extends LitElement {
  static styles = css`
    :host {
      display: inline-flex;
      gap: 3px;
      padding: 2px 4px;
    }
    span {
      width: 6px;
      height: 6px;
      background: currentColor;
      border-radius: 50%;
      animation: blink 1.2s infinite;
    }
    span:nth-child(2) {
      animation-delay: 0.2s;
    }
    span:nth-child(3) {
      animation-delay: 0.4s;
    }
    @keyframes blink {
      0%,
      80%,
      100% {
        opacity: 0.2;
      }
      40% {
        opacity: 1;
      }
    }
  `;

  render() {
    return html`<span></span><span></span><span></span>`;
  }
}
