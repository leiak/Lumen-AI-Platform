// Must run before any JS modules load to suppress ResizeObserver warnings
// that would otherwise trigger Next.js error overlay source map requests.
//
// This patches the raw console object before any library (including React and Next.js)
// gets a chance to wrap it.
(function () {
  var suppressedPatterns = ['ResizeObserver', 'is empty', '__nextjs_original-stack-frame', 'hydration'];

  // Store the raw console methods BEFORE any library wraps them
  var rawConsoleError = console.error.bind(console);
  var rawConsoleWarn = console.warn.bind(console);

  function shouldSuppress(args) {
    var msg = args[0];
    if (typeof msg !== 'string') return false;
    for (var i = 0; i < suppressedPatterns.length; i++) {
      if (msg.indexOf(suppressedPatterns[i]) !== -1) return true;
    }
    return false;
  }

  // Patch console.error
  console.error = function () {
    if (shouldSuppress(arguments)) return;
    rawConsoleError.apply(console, arguments);
  };

  // Also patch console.warn to catch warnings before they become console.error
  console.warn = function () {
    if (shouldSuppress(arguments)) return;
    rawConsoleWarn.apply(console, arguments);
  };

  // Patch window.onerror for unhandled errors
  var originalOnerror = window.onerror;
  window.onerror = function (msg, src, line, col, err) {
    if (typeof msg === 'string') {
      for (var i = 0; i < suppressedPatterns.length; i++) {
        if (msg.indexOf(suppressedPatterns[i]) !== -1) return true;
      }
    }
    if (originalOnerror) return originalOnerror(msg, src, line, col, err);
    return false;
  };

  // Patch the ErrorUtils global that React uses for error handling
  if (typeof window !== 'undefined' && window.ErrorUtils) {
    var originalErrorUtils = window.ErrorUtils;
    window.ErrorUtils = {
      reportError: function (err) {
        var msg = typeof err === 'string' ? err : err?.message;
        if (typeof msg === 'string') {
          for (var i = 0; i < suppressedPatterns.length; i++) {
            if (msg.indexOf(suppressedPatterns[i]) !== -1) return;
          }
        }
        originalErrorUtils.reportError(err);
      },
      reportUnhandledError: function (err) {
        var msg = typeof err === 'string' ? err : err?.message;
        if (typeof msg === 'string') {
          for (var i = 0; i < suppressedPatterns.length; i++) {
            if (msg.indexOf(suppressedPatterns[i]) !== -1) return;
          }
        }
        originalErrorUtils.reportUnhandledError(err);
      },
    };
  }
})();
