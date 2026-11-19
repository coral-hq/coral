import { cleanup, render, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useInboxKinds } from "@/lib/inboxKinds";
import { CoralRuntime } from "./CoralRuntime";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("renders nothing, sends no request and registers no Inbox kind until the workflow Inbox lands", () => {
  const fetchSpy = vi.spyOn(globalThis, "fetch");
  const { container } = render(<CoralRuntime />);
  expect(container).toBeEmptyDOMElement();
  expect(fetchSpy).not.toHaveBeenCalled();
  const { result } = renderHook(() => useInboxKinds());
  expect(result.current).toEqual([]);
});
