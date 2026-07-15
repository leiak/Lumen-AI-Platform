import { describe, expect, it } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useUndoable } from "@/app/dashboard/workflow/designer/hooks/useUndoable";

describe("useUndoable (M30d)", () => {
  it("starts with the initial value and no undo/redo available", () => {
    const { result } = renderHook(() => useUndoable<string[]>(["a", "b"]));
    expect(result.current.state).toEqual(["a", "b"]);
    expect(result.current.canUndo).toBe(false);
    expect(result.current.canRedo).toBe(false);
  });

  it("push() records a history entry that can be undone", () => {
    const { result } = renderHook(() => useUndoable<string[]>(["a"]));

    act(() => result.current.push(["a", "b"]));
    expect(result.current.state).toEqual(["a", "b"]);

    act(() => result.current.push(["a", "b", "c"]));
    expect(result.current.state).toEqual(["a", "b", "c"]);
    expect(result.current.canUndo).toBe(true);

    act(() => result.current.undo());
    expect(result.current.state).toEqual(["a", "b"]);
    expect(result.current.canRedo).toBe(true);
  });

  it("redo() replays the most-recent undone state", () => {
    const { result } = renderHook(() => useUndoable<number>(0));
    act(() => result.current.push(1));
    act(() => result.current.push(2));
    expect(result.current.state).toBe(2);

    act(() => result.current.undo());
    expect(result.current.state).toBe(1);
    act(() => result.current.undo());
    expect(result.current.state).toBe(0);
    expect(result.current.canUndo).toBe(false);

    act(() => result.current.redo());
    expect(result.current.state).toBe(1);
    act(() => result.current.redo());
    expect(result.current.state).toBe(2);
    expect(result.current.canRedo).toBe(false);
  });

  it("a new push after undo invalidates the redo stack", () => {
    const { result } = renderHook(() => useUndoable<string>("a"));
    act(() => result.current.push("b"));
    act(() => result.current.undo());
    expect(result.current.canRedo).toBe(true);

    act(() => result.current.push("c"));
    expect(result.current.state).toBe("c");
    // Pushing a new value clears the future stack.
    expect(result.current.canRedo).toBe(false);
  });

  it("set() updates state without recording history (transient updates)", () => {
    const { result } = renderHook(() => useUndoable<string>("a"));
    act(() => result.current.set("b"));
    expect(result.current.state).toBe("b");
    // set() should NOT have pushed — so undo is a no-op.
    expect(result.current.canUndo).toBe(false);
  });

  it("reset() clears history and sets a fresh starting point", () => {
    const { result } = renderHook(() => useUndoable<number>(0));
    act(() => result.current.push(1));
    act(() => result.current.push(2));
    expect(result.current.canUndo).toBe(true);

    act(() => result.current.reset(99));
    expect(result.current.state).toBe(99);
    expect(result.current.canUndo).toBe(false);
    expect(result.current.canRedo).toBe(false);
  });
});
