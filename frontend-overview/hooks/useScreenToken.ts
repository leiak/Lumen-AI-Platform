// 2026-06-06: screen endpoints are now public. This hook is a no-op kept as a
// stable export so existing call sites keep compiling. New code should not
// depend on a token; the dashboard renders anonymously for any visitor.
export function useScreenToken(): { ready: boolean; token: string | null } {
  return { ready: true, token: null };
}
