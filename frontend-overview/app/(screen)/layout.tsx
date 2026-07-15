"use client";
import { ReactNode } from "react";
import { RangeSelector } from "@/components/overview/RangeSelector";

// 2026-06-06: screen endpoints are public, so the layout renders immediately
// with no token gate. Header stays the same (title + range/interval/pause).
export default function ScreenLayout({ children }: { children: ReactNode }) {
  return (
    <div>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center",
                       padding: "12px 16px", borderBottom: "1px solid rgba(0,217,255,0.2)" }}>
        <span style={{ color: "#00d9ff", fontSize: 18, fontWeight: 600, letterSpacing: 2 }}>Lumen AI Platform 运营大屏</span>
        <RangeSelector />
      </header>
      <main>{children}</main>
    </div>
  );
}
