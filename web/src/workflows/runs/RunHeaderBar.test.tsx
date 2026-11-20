import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RunSpend } from "../api/generated/coralApi";
import { CONTRACT_DETAIL_GATE_PASS1 } from "../fixtures/runViewContract";
import { RunHeaderBar, spendText, type RunHeaderBarProps } from "./RunHeaderBar";

const DETAIL = CONTRACT_DETAIL_GATE_PASS1;
const SPEND = DETAIL.spend!;
const CREATED = DETAIL.created_at;

function renderBar(props: Partial<RunHeaderBarProps> = {}) {
  return render(
    <RunHeaderBar
      title="Ship the bridge"
      status="running"
      pauseReason={null}
      openGates={[]}
      provisional={false}
      createdAt={CREATED}
      finishedAt={null}
      spend={SPEND}
      notice={null}
      {...props}
    />,
  );
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime((CREATED + 125) * 1000);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("spendText", () => {
  const spend = (changes: Partial<RunSpend>): RunSpend => ({ ...SPEND, ...changes });

  it("shows the estimate in dollars", () => {
    // WHY: the run's spend is shown as the anchor's badge shows it.
    expect(spendText(SPEND)).toBe("$0.84");
  });

  it("says 'at least' while some models are unpriced", () => {
    // WHY: unpriced models make the figure a lower bound.
    expect(spendText(spend({ unpriced_models: ["local-model"] }))).toBe("at least $0.84");
  });

  it("shows tokens when no session was priced", () => {
    // WHY: with no price there is still usage to show.
    expect(spendText(spend({ usd: null }))).toBe("194.4K tokens");
  });

  it("shows a dash while spend is unknown", () => {
    // WHY: a run whose spend was not read yet shows nothing made up.
    expect(spendText(null)).toBe("—");
    expect(spendText(undefined)).toBe("—");
  });
});

describe("RunHeaderBar", () => {
  it("shows the title, status, elapsed time and spend, never a cap", () => {
    // WHY: where the run is and what it cost, at a glance.
    renderBar();
    expect(screen.getByRole("heading", { level: 1, name: "Ship the bridge" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Running");
    expect(screen.getByTestId("run-elapsed")).toHaveTextContent("Elapsed 2m 5s");
    expect(screen.getByTestId("run-spend")).toHaveTextContent("Spend so far (estimate) $0.84");
    expect(document.body).not.toHaveTextContent(/cap|limit|budget/i);
  });

  it("ticks the seconds it shows, and stops ticking once the run ends", () => {
    // WHY: elapsed time shows seconds, so a coarser clock would read as frozen or wrong.
    const { rerender } = renderBar();
    act(() => {
      vi.advanceTimersByTime(1_000);
    });
    expect(screen.getByTestId("run-elapsed")).toHaveTextContent("Elapsed 2m 6s");
    expect(vi.getTimerCount()).toBe(1);
    rerender(
      <RunHeaderBar
        title="Ship the bridge"
        status="completed"
        pauseReason={null}
        openGates={[]}
        provisional={false}
        createdAt={CREATED}
        finishedAt={CREATED + 130}
        spend={SPEND}
        notice={null}
      />,
    );
    expect(vi.getTimerCount()).toBe(0);
    expect(screen.getByTestId("run-elapsed")).toHaveTextContent("Elapsed 2m 10s");
  });

  it("says Needs you while a gate is open", () => {
    // WHY: an open gate is waiting on the owner.
    renderBar({ openGates: ["approve_change||a4:1:1"] });
    expect(screen.getByRole("status")).toHaveTextContent("Needs you");
  });

  it("keeps counting while the run works, and stops when it finishes", () => {
    // WHY: elapsed time is the run's own, from its start to its end.
    const { rerender } = renderBar();
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(screen.getByTestId("run-elapsed")).toHaveTextContent("Elapsed 3m 5s");
    rerender(
      <RunHeaderBar
        title="Ship the bridge"
        status="completed"
        pauseReason={null}
        openGates={[]}
        provisional={false}
        createdAt={CREATED}
        finishedAt={CREATED + 480}
        spend={SPEND}
        notice={null}
      />,
    );
    expect(screen.getByTestId("run-elapsed")).toHaveTextContent("Elapsed 8m");
  });

  it("keeps counting through a pause", () => {
    // WHY: elapsed is wall time since the start; a pause does not stop the run's clock.
    renderBar({ status: "paused", pauseReason: "user" });
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(screen.getByRole("status")).toHaveTextContent("Paused: by you");
    expect(screen.getByTestId("run-elapsed")).toHaveTextContent("Elapsed 3m 5s");
  });

  it("marks the detail's status as provisional until the stream speaks", () => {
    // WHY: the detail can be older than the run; its status is shown, not trusted.
    renderBar({ provisional: true });
    expect(screen.getByTestId("run-status-pill")).toHaveAttribute("data-provisional", "true");
    expect(screen.getByRole("status")).toHaveTextContent("Running (not live yet)");
  });

  it("announces the connection notice in the status region, with the actions beside it", () => {
    // WHY: a screen reader hears that live updates stopped, as a sighted person sees it.
    renderBar({ notice: "Reconnecting…", actions: <button type="button">Pause</button> });
    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
    expect(screen.getByRole("status")).toHaveTextContent("Reconnecting…");
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
  });

  it("shows dashes while the detail has not loaded", () => {
    // WHY: before the detail, there is no start time or spend to show.
    renderBar({ createdAt: null, spend: undefined });
    expect(screen.getByTestId("run-elapsed")).toHaveTextContent("Elapsed —");
    expect(screen.getByTestId("run-spend")).toHaveTextContent("Spend so far (estimate) —");
  });
});
