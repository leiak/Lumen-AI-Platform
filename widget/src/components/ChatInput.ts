/** <lumen-chat-input> — textarea + send button row.
 *
 *  A single-line textarea that grows as the user types and dispatches
 *  a `submit` CustomEvent (with no detail) when the user presses Enter
 *  (without Shift) or clicks the send button. The send button is
 *  disabled whenever the trimmed value is empty.
 *
 *  The parent component owns the controlled value — the input emits
 *  `input-change` (with `detail: string`) on every keystroke and a
 *  `submit` event when the user wants to send. This keeps the input
 *  stateless and trivially testable.
 *
 *  NOTE: This component is the extracted counterpart of the inline
 *  input row that currently lives in `LumenChat.ts`. It is shipped
 *  standalone in this task (per the plan's escape hatch) so a future
 *  refactor can adopt it without re-doing the extraction work.
 *  Adoption itself is out of scope here.
 */
import { LitElement, html, css } from "lit";
import { customElement, property } from "lit/decorators.js";

@customElement("lc-chat-input")
export class ChatInput extends LitElement {
  static styles = css`
    :host {
      display: block;
    }
    .row {
      display: flex;
      gap: var(--lc-spacing-sm);
      padding: var(--lc-spacing-sm);
      border-top: 1px solid var(--lc-border);
    }
    textarea {
      flex: 1;
      resize: none;
      border: none;
      outline: none;
      background: transparent;
      color: var(--lc-text-primary);
      font: inherit;
    }
    button {
      background: var(--lc-primary);
      color: var(--lc-primary-fg);
      border: none;
      padding: 0 var(--lc-spacing-md);
      border-radius: var(--lc-radius-sm);
      cursor: pointer;
    }
    button:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  `;

  @property({ type: String }) placeholder = "输入消息...";
  @property({ type: String }) value = "";

  render() {
    return html`
      <div class="row">
        <textarea
          rows="1"
          .value=${this.value}
          placeholder=${this.placeholder}
          @input=${(e: Event) => {
            this.value = (e.target as HTMLTextAreaElement).value;
            this.dispatchEvent(
              new CustomEvent("input-change", { detail: this.value })
            );
          }}
          @keydown=${(e: KeyboardEvent) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              this.dispatchEvent(new CustomEvent("submit"));
            }
          }}
        ></textarea>
        <button
          @click=${() => this.dispatchEvent(new CustomEvent("submit"))}
          ?disabled=${!this.value.trim()}
        >
          ➤
        </button>
      </div>
    `;
  }
}
