"use client";

import { useEffect } from "react";

/**
 * Suppress ResizeObserver "empty children" warnings that cause excessive
 * __nextjs_original-stack-frame requests in development mode.
 *
 * These warnings come from antd ProLayout and trigger Next.js's error overlay
 * source map lookups, creating many unnecessary network requests.
 */
export function useSuppressResizeObserverWarning() {
  useEffect(() => {
    // Store original ResizeObserver
    const OriginalResizeObserver = window.ResizeObserver;

    // Patch ResizeObserver to filter out empty children warnings
    window.ResizeObserver = class PatchedResizeObserver extends OriginalResizeObserver {
      constructor(callback: ResizeObserverCallback) {
        const patchedCallback: ResizeObserverCallback = (
          entries: ResizeObserverEntry[],
          observer: ResizeObserver
        ) => {
          // Filter out entries where all observed elements have empty children
          const filteredEntries = entries.filter((entry) => {
            const target = entry.target as Element;
            // Only filter if the warning would be "children is empty"
            // Check if the target has no visible children
            if (target.childElementCount === 0) {
              // Check if target is likely a layout container (like those used by ProLayout)
              const className = target.className || "";
              const id = target.id || "";
              if (
                typeof className === "string" &&
                (className.includes("ant-design") ||
                  className.includes("pro") ||
                  id.includes("sider") ||
                  id.includes("layout"))
              ) {
                return false; // skip this entry
              }
            }
            return true;
          });

          // Only call original callback if there are valid entries
          if (filteredEntries.length > 0) {
            callback(filteredEntries, observer);
          }
        };

        super(patchedCallback);
      }
    };

    // Also patch console.error to suppress any ResizeObserver-related messages
    const originalError = console.error.bind(console);
    console.error = (...args: unknown[]) => {
      const message = args[0];
      if (
        typeof message === "string" &&
        (message.includes("ResizeObserver") ||
          message.includes("children") ||
          message.includes("empty") ||
          message.includes("__nextjs_original-stack-frame"))
      ) {
        return;
      }
      originalError(...args);
    };

    return () => {
      window.ResizeObserver = OriginalResizeObserver;
      console.error = originalError;
    };
  }, []);
}
