"use client";
import { ConfigProvider, theme } from "antd";
import "./globals.css";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <ConfigProvider
          theme={{
            algorithm: theme.darkAlgorithm,
            token: { colorPrimary: "#1677ff", colorBgBase: "#0a0e1a", borderRadius: 4 },
          }}
        >
          {children}
        </ConfigProvider>
      </body>
    </html>
  );
}
