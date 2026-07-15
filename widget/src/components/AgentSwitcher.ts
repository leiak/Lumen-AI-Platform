/** <lc-agent-switcher> — dropdown for picking an agent or team.
 *
 *  Renders a native `<select>` element with one `<option>` per entry in
 *  the `options` array. The currently selected value is mirrored to the
 *  `value` property (an `id`) and the matching `AgentOption` is reported
 *  on every change via a bubbling `agent-change` CustomEvent. The event
 *  detail is `{ id, options }` where `options` is the matching entry
 *  (`undefined` if the id does not match any option, e.g. an external
 *  script reset the value).
 *
 *  Styling is driven by `--lc-border`, `--lc-radius-sm`, `--lc-bg-page`
 *  and `--lc-text-primary` design tokens so the switcher inherits theme
 *  colors automatically.
 *
 *  NOTE: This component is the extracted counterpart of the inline
 *  agent picker that currently lives in `LumenChat.ts`. It is shipped
 *  standalone in this task (per the plan's escape hatch) so a future
 *  refactor can adopt it without re-doing the extraction work.
 *  Adoption itself is out of scope here.
 */
import { LitElement, html, css } from "lit";
import { customElement, property } from "lit/decorators.js";

export interface AgentOption {
  id: number;
  name: string;
  type: "agent" | "team";
}

export interface AgentChangeDetail {
  id: number | null;
  options: AgentOption | undefined;
}

@customElement("lc-agent-switcher")
export class AgentSwitcher extends LitElement {
  static styles = css`
    :host {
      display: inline-block;
    }
    select {
      padding: 4px 8px;
      border: 1px solid var(--lc-border);
      border-radius: var(--lc-radius-sm);
      background: var(--lc-bg-page);
      color: var(--lc-text-primary);
      font: inherit;
    }
  `;

  @property({ type: Array }) options: AgentOption[] = [];
  @property({ type: Number }) value: number | null = null;

  private handleChange = (e: Event) => {
    const target = e.target as HTMLSelectElement;
    this.value = Number(target.value);
    const detail: AgentChangeDetail = {
      id: this.value,
      options: this.options.find((o) => o.id === this.value),
    };
    this.dispatchEvent(
      new CustomEvent<AgentChangeDetail>("agent-change", { detail })
    );
  };

  render() {
    return html`
      <select @change=${this.handleChange}>
        ${this.options.map(
          (o) => html`<option value=${o.id} ?selected=${o.id === this.value}>${o.name}</option>`
        )}
      </select>
    `;
  }
}
