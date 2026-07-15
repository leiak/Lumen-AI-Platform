// Prevents ResizeObserver "empty children" warnings from triggering
// Next.js development overlay and __nextjs_original-stack-frame requests.
//
// This script MUST run before React initializes. Place in <head> as inline script.
(function () {
  // Patch console.error BEFORE any library loads
  const originalError = console.error.bind(console);
  const suppressedPatterns = [
    /ResizeObserver/i,
    /children.*empty/i,
    /is empty/i,
    /__nextjs_original-stack-frame/i,
    /Warning.*ResizeObserver/i,
  ];

  console.error = function (...args) {
    const message = args[0];
    if (typeof message === "string") {
      for (const pattern of suppressedPatterns) {
        if (pattern.test(message)) {
          return;
        }
      }
    }
    originalError(...args);
  };

  // Also patch window.onerror to prevent ResizeObserver errors from propagating
  const originalOnerror = window.onerror;
  window.onerror = function (message, source, lineno, colno, error) {
    if (typeof message === "string" && /ResizeObserver/i.test(message)) {
      return true; // suppress
    }
    if (originalOnerror) {
      return originalOnerror(message, source, lineno, colno, error);
    }
    return false;
  };
})();
