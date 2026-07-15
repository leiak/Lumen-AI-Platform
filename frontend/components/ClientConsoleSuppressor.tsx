"use client";

import { useSuppressResizeObserverWarning } from "@/hooks/useSuppressResizeObserverWarning";

export function ClientConsoleSuppressor() {
  useSuppressResizeObserverWarning();
  return null;
}
