import type { Metadata } from "next";
import { AntdRegistry } from "@ant-design/nextjs-registry";
import { QueryProvider } from "@/components/QueryProvider";
import { ResizeObserverSuppressor } from "@/components/ResizeObserverSuppressor";
import "./globals.css";

export const metadata: Metadata = {
  title: "Lumen AI Platform",
  description: "Lumen AI Platform with LangChain",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <ResizeObserverSuppressor />
      </head>
      <body>
        <QueryProvider>
          <AntdRegistry>{children}</AntdRegistry>
        </QueryProvider>
      </body>
    </html>
  );
}
