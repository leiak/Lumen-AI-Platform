import "@testing-library/jest-dom/vitest";

// jsdom does not implement window.matchMedia; AntD's responsive observer
// (used by Modal, Grid, etc.) needs it. Stub with a no-op implementation
// so component trees mount in unit tests.
if (typeof window !== "undefined" && !window.matchMedia) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

// jsdom's getComputedStyle throws for some elements. AntD's rc-motion /
// rc-trigger use it for layout measurements during mount; without a working
// stub the Modal footer never renders in tests.
if (
  typeof window !== "undefined" &&
  typeof window.getComputedStyle === "function"
) {
  const originalGetComputedStyle = window.getComputedStyle.bind(window);
  window.getComputedStyle = ((elt: Element, pseudoElt?: string | null) => {
    try {
      return originalGetComputedStyle(elt, pseudoElt);
    } catch {
      // Return a minimal stand-in so callers reading e.g. `display` still work.
      return {
        getPropertyValue: () => "",
        display: "block",
        visibility: "visible",
        opacity: "1",
      } as unknown as CSSStyleDeclaration;
    }
  }) as typeof window.getComputedStyle;
}

// jsdom does not implement scrollTo / scrollIntoView; AntD's rc-virtual-list
// and rc-trigger call them during mount. Without stubs, mounting can throw
// or silently skip rendering children.
if (typeof Element !== "undefined") {
  if (!Element.prototype.scrollTo) {
    Element.prototype.scrollTo = function () {};
  }
  if (!Element.prototype.scrollIntoView) {
    Element.prototype.scrollIntoView = function () {};
  }
}

// jsdom's Element.animate is a no-op stub. AntD's rc-motion / rc-trigger
// rely on Web Animations API being present; without `animate`, motion
// components may render with no children.
if (typeof Element !== "undefined" && typeof Element.prototype.animate !== "function") {
  Element.prototype.animate = function () {
    return {
      play: () => {},
      pause: () => {},
      cancel: () => {},
      finish: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
    } as unknown as Animation;
  };
}

// jsdom prints "Error: Not implemented: window.getComputedStyle(elt, pseudoElt)"
// for pseudo-elements. These are not real errors but noise that can confuse
// test reporters; silence them.
const _origConsoleError = console.error;
console.error = (...args: unknown[]) => {
  const first = args[0];
  if (typeof first === "string" && first.includes("Not implemented: window.getComputedStyle")) {
    return;
  }
  _origConsoleError.apply(console, args as []);
};
