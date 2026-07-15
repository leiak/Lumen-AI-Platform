/** <lumen-chat-bubble> — single message bubble (user / assistant).
 *
 *  Renders user messages as plain text (already trusted, posted by the
 *  end-user) and assistant messages as markdown via `renderMarkdown`.
 *  Alignment and background color differ by role; bubble padding and
 *  radius are driven by `--lc-spacing-*` / `--lc-radius-*` design tokens
 *  so the component inherits theme colors automatically.
 *
 *  NOTE: This component is the extracted counterpart of the inline
 *  bubble rendering that currently lives in `LumenChat.ts`. It is shipped
 *  standalone in this task (per the plan's escape hatch) so a future
 *  refactor can adopt it without re-doing the extraction work.
 *  Adoption itself is out of scope here.
 */
import { LitElement, html, css } from "lit";
import { customElement, property } from "lit/decorators.js";
import { renderMarkdown } from "../core/markdown";

@customElement("lc-chat-bubble")
export class ChatBubble extends LitElement {
  static styles = css`
    :host {
      display: block;
    }
    .bubble {
      padding: var(--lc-spacing-sm) var(--lc-spacing-md);
      border-radius: var(--lc-radius-md);
    }
    .user {
      background: var(--lc-bg-bubble-user);
      color: var(--lc-text-on-primary);
    }
    .assistant {
      background: var(--lc-bg-bubble-assistant);
      color: var(--lc-text-primary);
    }
    .wrap-user {
      display: flex;
      justify-content: flex-end;
    }
    .wrap-assistant {
      display: flex;
      justify-content: flex-start;
    }
  `;

  @property({ type: String }) role: "user" | "assistant" = "assistant";
  @property({ type: String }) content = "";

  render() {
    const inner =
      this.role === "user" ? this.content : renderMarkdown(this.content);
    return html`
      <div class="wrap-${this.role}">
        <div class="bubble ${this.role}">
          <div .innerHTML=${inner}></div>
        </div>
      </div>
    `;
  }
}
