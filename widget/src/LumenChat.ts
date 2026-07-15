import { LitElement, html, unsafeCSS } from "lit";
import { customElement, property, state } from "lit/decorators.js";
import baseCss from "./styles/base.css";
import tokensCss from "./styles/tokens.css";
import { AuthStore, TokenExpiredError } from "./core/auth";
import { fetchToken, streamChat, uploadFile, listConversations } from "./core/api";
import { renderMarkdown } from "./core/markdown";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  conversation_id?: number;
  pending?: boolean;
  attachments?: { file_id: string; name: string; size: number; mime_type: string }[];
}

@customElement("lumen-chat")
export class LumenChat extends LitElement {
  static styles = [
    // CSS imported as `text` by esbuild → raw string at runtime.
    // unsafeCSS() wraps it as a CSSResult so Lit's style pipeline
    // doesn't try to re-parse it as a template literal.
    unsafeCSS(tokensCss),
    unsafeCSS(baseCss),
  ];

  // — Properties (HTML attributes) —
  @property({ type: String }) server = "";
  @property({ type: String, attribute: "app-key" }) appKey = "";
  @property({ type: Number, attribute: "agent-id" }) agentId: number | null = null;
  @property({ type: Number, attribute: "team-id" }) teamId: number | null = null;
  @property({ type: String }) theme: "light" | "dark" | "auto" = "auto";
  @property({ type: String }) title = "AI 助手";
  @property({ type: String }) placeholder = "输入消息...";
  @property({ type: String, attribute: "welcome-message" }) welcomeMessage = "";
  @property({ type: String }) height = "600px";
  @property({ type: String }) width = "400px";
  @property({ type: Boolean }) floating = false;
  @property({ type: Boolean, attribute: "enable-agent-switch" }) enableAgentSwitch = false;
  @property({ type: Boolean, attribute: "enable-conversations" }) enableConversations = false;
  @property({ type: Number, attribute: "conversation-id" }) conversationId: number | null = null;

  // — Internal state —
  @state() private messages: ChatMessage[] = [];
  @state() private input = "";
  @state() private auth = new AuthStore();
  @state() private allowedAgents: {
    id: number;
    name: string;
    type: "agent" | "team";
    knowledge_bases?: { id: number; name: string; status: string }[];
  }[] = [];
  @state() private activeAgentId: number | null = null;
  @state() private activeTeamId: number | null = null;
  @state() private conversations: any[] = [];
  @state() private error: string | null = null;
  @state() private attachments: { file_id: string; name: string; size: number; mime_type: string }[] = [];
  @state() private ready = false;

  private abortCtl: AbortController | null = null;

  async connectedCallback() {
    super.connectedCallback();
    if (this.welcomeMessage && this.messages.length === 0) {
      this.messages = [{ role: "assistant", content: this.welcomeMessage }];
    }
    await this._init();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this.abort();
  }

  private async _init() {
    try {
      // Fetch token (or re-use cached)
      if (!this.auth.token || this.auth.isExpiringSoon()) {
        const t = await fetchToken({ server: this.server, appKey: this.appKey, visitorId: this.auth.visitorId });
        this.auth.token = t.token;
        this.auth.expiresAt = Math.floor(Date.now() / 1000) + t.expires_in;
        this.allowedAgents = [
          ...t.allowed_agents.map((a: any) => ({
            id: a.id,
            name: a.name,
            type: "agent" as const,
            knowledge_bases: Array.isArray(a.knowledge_bases) ? a.knowledge_bases : [],
          })),
          ...t.allowed_teams.map((a: any) => ({
            id: a.id,
            name: a.name,
            type: "team" as const,
            knowledge_bases: [],
          })),
        ];
        this.dispatchEvent(new CustomEvent("lc-ready", { detail: { allowed_agents: t.allowed_agents, allowed_teams: t.allowed_teams } }));
      }
      // Decide default agent
      if (this.agentId) this.activeAgentId = this.agentId;
      else if (this.teamId) this.activeTeamId = this.teamId;
      else if (this.allowedAgents.length > 0) {
        const first = this.allowedAgents[0];
        if (first.type === "agent") this.activeAgentId = first.id;
        else this.activeTeamId = first.id;
      }
      this.ready = true;
      if (this.enableConversations) {
        this.conversations = await listConversations({ server: this.server, token: this.auth.token! });
      }
    } catch (e: any) {
      this.error = `初始化失败: ${e?.message ?? e}`;
    }
  }

  // — Public methods —
  send(text: string, files?: File[]): Promise<void> {
    this.input = text;
    if (files && files.length) {
      // upload each and accumulate chip
      return Promise.all(
        files.map((f) =>
          uploadFile({ server: this.server, token: this.auth.token!, file: f }).then(
            (r) => (this.attachments = [...this.attachments, { file_id: r.file_id, name: r.name, size: r.size, mime_type: r.mime_type }])
          )
        )
      ).then(() => this._send());
    }
    return this._send();
  }
  clear() {
    this.messages = this.welcomeMessage ? [{ role: "assistant", content: this.welcomeMessage }] : [];
  }
  cancel() {
    this.abort();
  }
  startNewConversation() {
    this.conversationId = null;
    this.clear();
  }
  switchAgent(idOrType: number, type: "agent" | "team" = "agent") {
    if (type === "agent") {
      this.activeAgentId = idOrType;
      this.activeTeamId = null;
    } else {
      this.activeTeamId = idOrType;
      this.activeAgentId = null;
    }
    this.dispatchEvent(new CustomEvent("lc-agent-change", { detail: { id: idOrType, type } }));
  }
  async refreshConversations() {
    this.conversations = await listConversations({ server: this.server, token: this.auth.token! });
  }

  private abort() {
    this.abortCtl?.abort();
    this.abortCtl = null;
  }

  private async _send(): Promise<void> {
    if (!this.input.trim() || !this.auth.token) return;
    const userText = this.input.trim();
    this.input = "";
    const userMsg: ChatMessage = { role: "user", content: userText, attachments: [...this.attachments] };
    this.messages = [...this.messages, userMsg];
    this.attachments = [];
    const assistantMsg: ChatMessage = { role: "assistant", content: "", pending: true };
    this.messages = [...this.messages, assistantMsg];

    this.abortCtl = new AbortController();
    try {
      const gen = streamChat({
        server: this.server,
        token: this.auth.token,
        body: {
          message: userText,
          agent_id: this.activeAgentId,
          team_id: this.activeTeamId,
          conversation_id: this.conversationId,
          attachments: userMsg.attachments,
        },
        signal: this.abortCtl.signal,
      });
      for await (const ev of gen) {
        if (ev.conversation_id) this.conversationId = ev.conversation_id;
        if (ev.content !== undefined) {
          this.messages = this.messages.map((m, i) =>
            i === this.messages.length - 1 ? { ...m, content: m.content + ev.content, pending: false } : m
          );
        }
        if (ev.done) {
          this.messages = this.messages.map((m, i) =>
            i === this.messages.length - 1 ? { ...m, pending: false } : m
          );
          this.dispatchEvent(
            new CustomEvent("lc-message", {
              detail: { role: "assistant", content: this.messages[this.messages.length - 1].content, conversation_id: this.conversationId },
            })
          );
        }
      }
    } catch (e: any) {
      if (e instanceof TokenExpiredError) {
        this.auth.clear();
        await this._init();
        return this._send(); // retry once
      }
      this.error = e?.message ?? String(e);
      this.dispatchEvent(new CustomEvent("lc-error", { detail: { message: this.error } }));
    } finally {
      this.abortCtl = null;
    }
  }

  private _onKey(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      this._send();
    }
  }

  render() {
    if (!this.ready) {
      return html`<div
        class="lc-container"
        style="--lc-height:${this.height};--lc-width:${this.width}"
      >
        <div class="lc-messages">
          ${this.error ? html`<p style="color:var(--lc-error-color)">${this.error}</p>` : "加载中…"}
        </div>
      </div>`;
    }
    return html`
      <div
        class="lc-container"
        style="--lc-height:${this.height};--lc-width:${this.width}"
      >
        <div class="lc-header">
          <h1>${this.title}</h1>
          ${this._renderKbBadge()}
          ${this.enableAgentSwitch && this.allowedAgents.length
            ? html`<select
                @change=${(e: Event) => this.switchAgent(Number((e.target as HTMLSelectElement).value))}
              >
                ${this.allowedAgents.map(
                  (a) => html`<option value=${a.id} ?selected=${a.id === (this.activeAgentId ?? this.activeTeamId)}>${a.name}</option>`
                )}
              </select>`
            : ""}
          ${!this.floating
            ? html`<button
                @click=${() => {
                  this.dispatchEvent(new CustomEvent("lc-close"));
                  // 隐藏而非 remove():保留 DOM/state/token,
                  // demo 页可监听 lc-close 后在右下角显示浮动按钮恢复展开。
                  this.style.display = "none";
                }}
              >
                ×
              </button>`
            : ""}
        </div>
        <div class="lc-messages">${this.messages.map((m) => this._renderMessage(m))}</div>
        <div class="lc-input-row">
          <textarea
            rows="1"
            .value=${this.input}
            placeholder=${this.placeholder}
            @input=${(e: Event) => (this.input = (e.target as HTMLTextAreaElement).value)}
            @keydown=${this._onKey}
          ></textarea>
          <button @click=${() => this._send()} ?disabled=${!this.input.trim()}>➤</button>
        </div>
      </div>
    `;
  }

  private _renderKbBadge() {
    // Resolve the currently active agent (may be a team, in which case we
    // hide the badge — teams don't carry KBs in the same way).
    const activeId = this.activeAgentId ?? this.activeTeamId;
    const active = this.allowedAgents.find((a) => a.id === activeId);
    if (!active || active.type !== "agent") return "";
    const kbs = active.knowledge_bases ?? [];
    const tooltip =
      kbs.length > 0
        ? `使用知识库: ${kbs.map((k) => k.name).join(", ")}`
        : "未配置知识库";
    // M21: small book icon + native title tooltip in the header. We avoid
    // pulling in AntD / @ant-design/icons because the widget bundle has
    // strict size limits (see widget/scripts/check-bundle-size.mjs).
    return html`<span
      class="lc-kb-badge"
      data-testid="lc-kb-badge"
      data-kb-count=${kbs.length}
      title=${tooltip}
      aria-label=${tooltip}
    >📚</span>`;
  }

  private _renderMessage(m: ChatMessage) {
    const isUser = m.role === "user";
    const html2 = isUser ? m.content : renderMarkdown(m.content);
    return html`
      <div style="display:flex; justify-content:${isUser ? "flex-end" : "flex-start"}">
        <div
          style="max-width:75%; padding:var(--lc-spacing-sm) var(--lc-spacing-md); border-radius:var(--lc-radius-md);
                    background:${isUser ? "var(--lc-bg-bubble-user)" : "var(--lc-bg-bubble-assistant)"};
                    color:${isUser ? "var(--lc-text-on-primary)" : "var(--lc-text-primary)"}"
        >
          ${m.attachments?.length
            ? html`<div>${m.attachments.map((a) => html`<span>📎 ${a.name}</span>`)}</div>`
            : ""}
          <div .innerHTML=${html2}></div>
          ${m.pending ? html`<span>···</span>` : ""}
        </div>
      </div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "lumen-chat": LumenChat;
  }
}
