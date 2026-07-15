import axios from "axios";

const api = axios.create({
  baseURL: "/api/v1",
  timeout: 8000,
});

// 2026-06-06: the screen dashboard is public. Keep the request interceptor
// (harmless — if a user has a stale token in localStorage we just attach it)
// but drop the 401 redirect, since the dashboard never returns 401 anymore
// and any future 401 should be surfaced to the caller, not silently bounced
// back to the main console login.
api.interceptors.request.use((config) => {
  const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
  if (token) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export default api;
