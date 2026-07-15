import { describe, it, expect, beforeEach } from "vitest";
import { AuthStore, TokenExpiredError } from "../src/core/auth";

describe("AuthStore", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("persists visitor_id across instances", () => {
    const a = new AuthStore({ storagePrefix: "lc-test-" });
    const id1 = a.visitorId;
    const b = new AuthStore({ storagePrefix: "lc-test-" });
    expect(b.visitorId).toBe(id1);
  });

  it("stores and retrieves token", () => {
    const a = new AuthStore({ storagePrefix: "lc-test-" });
    a.token = "abc";
    const b = new AuthStore({ storagePrefix: "lc-test-" });
    expect(b.token).toBe("abc");
  });

  it("clear() removes token but keeps visitor_id", () => {
    const a = new AuthStore({ storagePrefix: "lc-test-" });
    a.token = "abc";
    const id = a.visitorId;
    a.clear();
    const b = new AuthStore({ storagePrefix: "lc-test-" });
    expect(b.visitorId).toBe(id);
    expect(b.token).toBeNull();
  });
});

describe("TokenExpiredError", () => {
  it("is throwable and catchable", () => {
    expect(() => { throw new TokenExpiredError(); }).toThrow(TokenExpiredError);
  });
});

describe("AuthStore.isExpiringSoon", () => {
  it("returns true when no expiry set", () => {
    const a = new AuthStore({ storagePrefix: "lc-test-exp-" });
    expect(a.isExpiringSoon()).toBe(true);
  });
  it("returns true when within skew window", () => {
    const a = new AuthStore({ storagePrefix: "lc-test-exp2-" });
    a.expiresAt = Math.floor(Date.now() / 1000) + 5;
    expect(a.isExpiringSoon(30)).toBe(true);
  });
  it("returns false when far in the future", () => {
    const a = new AuthStore({ storagePrefix: "lc-test-exp3-" });
    a.expiresAt = Math.floor(Date.now() / 1000) + 3600;
    expect(a.isExpiringSoon(30)).toBe(false);
  });
});
