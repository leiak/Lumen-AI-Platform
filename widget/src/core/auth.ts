/** Visitor ID persistence + JWT token cache. localStorage-backed.

Mirrors the auth state the backend expects: a stable visitor UUID
per browser (so reload re-attaches to the same history) and a
short-lived JWT (30 min TTL; we re-issue transparently on 401).
*/

import { uuid } from "../utils";

export const TOKEN_EXPIRED = "TOKEN_EXPIRED";

export class TokenExpiredError extends Error {
  constructor() {
    super("external token expired");
    this.name = "TokenExpiredError";
  }
}

interface Config {
  storagePrefix?: string;
}

const DEFAULT_PREFIX = "lc-widget-";

export class AuthStore {
  private readonly prefix: string;

  constructor(cfg: Config = {}) {
    this.prefix = cfg.storagePrefix ?? DEFAULT_PREFIX;
    if (!localStorage.getItem(this.prefix + "visitor-id")) {
      localStorage.setItem(this.prefix + "visitor-id", uuid());
    }
  }

  get visitorId(): string {
    return localStorage.getItem(this.prefix + "visitor-id")!;
  }

  get token(): string | null {
    return localStorage.getItem(this.prefix + "token");
  }
  set token(v: string | null) {
    if (v == null) localStorage.removeItem(this.prefix + "token");
    else localStorage.setItem(this.prefix + "token", v);
  }

  get expiresAt(): number | null {
    const v = localStorage.getItem(this.prefix + "token-exp");
    return v ? Number(v) : null;
  }
  set expiresAt(v: number | null) {
    if (v == null) localStorage.removeItem(this.prefix + "token-exp");
    else localStorage.setItem(this.prefix + "token-exp", String(v));
  }

  clear(): void {
    this.token = null;
    this.expiresAt = null;
  }

  isExpiringSoon(skewSec = 30): boolean {
    const e = this.expiresAt;
    if (!e) return true;
    return Date.now() / 1000 > e - skewSec;
  }
}
