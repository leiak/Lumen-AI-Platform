/** <lc-conversation-list> — sidebar list of past conversations.
 *
 *  Renders a "new conversation" button at the top and one item per
 *  entry in the `conversations` array. The active item (matched by
 *  `activeId`) gets an `.active` class with a stronger font weight and
 *  the assistant bubble background. Clicking the new-conversation
 *  button emits a `new-conversation` CustomEvent; clicking an item
 *  emits a `select-conversation` CustomEvent with the matching `Conv`
 *  in the `detail`.
 *
 *  Spacing and colors are driven by `--lc-spacing-sm/md`, `--lc-border`,
 *  `--lc-bg-bubble-assistant` and `--lc-header-bg` design tokens so the
 *  list inherits theme colors automatically.
 *
 *  NOTE: This component is the extracted counterpart of the inline
 *  conversation list that currently lives in `LumenChat.ts`. It is
 *  shipped standalone in this task (per the plan's escape hatch) so a
 *  future refactor can adopt it without re-doing the extraction work.
 *  Adoption itself is out of scope here.
 */
import { LitElement, html, css } from "lit";
import { customElement, property } from "lit/decorators.js";

export interface Conv {
  id: number;
  title: string;
}

@customElement("lc-conversation-list")
export class ConversationList extends LitElement {
  static styles = css`
    :host {
      display: block;
      width: 200px;
      border-right: 1px solid var(--lc-border);
      background: var(--lc-header-bg);
      overflow-y: auto;
    }
    .item {
      padding: var(--lc-spacing-sm) var(--lc-spacing-md);
      cursor: pointer;
      border-bottom: 1px solid var(--lc-border);
    }
    .item:hover {
      background: var(--lc-bg-bubble-assistant);
    }
    .item.active {
      background: var(--lc-bg-bubble-assistant);
      font-weight: 600;
    }
    .new {
      width: calc(100% - var(--lc-spacing-md) * 2);
      margin: var(--lc-spacing-sm);
    }
  `;

  @property({ type: Array }) conversations: Conv[] = [];
  @property({ type: Number }) activeId: number | null = null;

  private handleNew = () => {
    this.dispatchEvent(new CustomEvent("new-conversation"));
  };

  private handleSelect = (c: Conv) => {
    this.dispatchEvent(new CustomEvent<Conv>("select-conversation", { detail: c }));
  };

  render() {
    return html`
      <button class="new" @click=${this.handleNew}>+ 新对话</button>
      ${this.conversations.map(
        (c) => html`
          <div
            class="item ${c.id === this.activeId ? "active" : ""}"
            @click=${() => this.handleSelect(c)}
          >
            ${c.title}
          </div>
        `
      )}
    `;
  }
}
