import axios from "axios";
import type { LoginRequest, LoginResponse, ApiResponse } from "@/types/api";

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:11335/api/v1",
  timeout: 120000,
});

// Add interceptor for auth token
api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("access_token");
    console.log("[Auth] Request to:", config.url, "Token:", token ? "present" : "MISSING");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    } else {
      console.log("[Auth] No token found in localStorage for:", config.url);
    }
  }
  return config;
});

// Response interceptor for 401 handling
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && typeof window !== "undefined") {
      localStorage.removeItem("access_token");
      localStorage.removeItem("user");
      window.location.href = "/login";
    }
    return Promise.reject(error);
  }
);

// Auth API
export const authApi = {
  login: (data: LoginRequest) => {
    const params = new URLSearchParams();
    params.append('username', data.username);
    params.append('password', data.password);
    return api.post<ApiResponse<LoginResponse>>("/auth/login", params);
  },
  getMe: () => api.get("/auth/me"),
};

export default api;
