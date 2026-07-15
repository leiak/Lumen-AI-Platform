"use client";
import { create } from "zustand";
import type { ScreenRange } from "@/services/screen";

export interface ScreenStore {
  range: ScreenRange;
  intervalMs: number;        // 0 = 关闭
  paused: boolean;
  setRange: (r: ScreenRange) => void;
  setInterval: (ms: number) => void;
  togglePaused: () => void;
}

export const useScreenStore = create<ScreenStore>((set) => ({
  range: "24h",
  intervalMs: 10000,
  paused: false,
  setRange: (r) => set({ range: r }),
  setInterval: (ms) => set({ intervalMs: ms }),
  togglePaused: () => set((s) => ({ paused: !s.paused })),
}));
