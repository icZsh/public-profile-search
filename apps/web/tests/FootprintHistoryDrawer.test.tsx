import type {
  FootprintHistoryGroup,
  FootprintHistoryRun,
  FootprintJob,
} from "@public-profile-search/generated-api-client";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  clearFootprintHistory: vi.fn(),
  createIdempotencyKey: vi.fn(),
  deleteFootprintJob: vi.fn(),
  getFootprintHistory: vi.fn(),
  getFootprintHistoryRuns: vi.fn(),
  refreshFootprintJob: vi.fn(),
}));
const pushMock = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", () => apiMocks);
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));
vi.mock("next/link", () => ({
  default: (props: ComponentProps<"a">) => <a {...props} />,
}));

import { FootprintHistoryDrawer } from "@/components/FootprintHistoryDrawer";

const readyRun: FootprintHistoryRun = {
  job_id: "11111111-1111-4111-8111-111111111111",
  status: "ready",
  search_mode: "quick",
  synthesis_model: null,
  accepted_at: "2026-08-14T18:30:00Z",
  finished_at: "2026-08-14T18:31:00Z",
  expires_at: "2026-09-13T18:30:00Z",
  candidate_count: 3,
  result_available: true,
  refresh_of_job_id: null,
};

const deepRun: FootprintHistoryRun = {
  ...readyRun,
  job_id: "22222222-2222-4222-8222-222222222222",
  status: "ready_partial",
  search_mode: "deep",
  synthesis_model: "openai/gpt-5.6-luna",
  accepted_at: "2026-08-13T18:30:00Z",
  candidate_count: 6,
};

const historyGroup: FootprintHistoryGroup = {
  representative_job_id: readyRun.job_id,
  seed: {
    kind: "platform_identifier",
    platform: "github",
    identifier: "octavia",
  },
  latest_run: readyRun,
  run_count: 2,
};

const refreshedJob = {
  job_id: "33333333-3333-4333-8333-333333333333",
} as FootprintJob;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

async function openLoadedDrawer() {
  const user = userEvent.setup();
  render(<FootprintHistoryDrawer />);
  await user.click(screen.getByRole("button", { name: /history/i }));
  await screen.findByText("github · @octavia");
  return user;
}

describe("FootprintHistoryDrawer", () => {
  beforeEach(() => {
    apiMocks.createIdempotencyKey.mockReturnValue("history-refresh-key");
    apiMocks.getFootprintHistory.mockResolvedValue({
      items: [historyGroup],
      next_cursor: null,
    });
    apiMocks.getFootprintHistoryRuns.mockResolvedValue({
      items: [readyRun, deepRun],
      next_cursor: null,
    });
    apiMocks.refreshFootprintJob.mockResolvedValue(refreshedJob);
    apiMocks.deleteFootprintJob.mockResolvedValue(undefined);
    apiMocks.clearFootprintHistory.mockResolvedValue({
      deleted_count: 0,
      has_more: false,
    });
    pushMock.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("opens a nonmodal hover peek without stealing focus", async () => {
    vi.useFakeTimers();
    render(<FootprintHistoryDrawer />);
    const trigger = screen.getByRole("button", { name: /history/i });
    trigger.focus();

    fireEvent.pointerEnter(trigger, { pointerType: "mouse" });
    await act(async () => vi.advanceTimersByTimeAsync(159));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await act(async () => vi.advanceTimersByTimeAsync(1));
    const peek = screen.getByRole("dialog", { name: "History" });
    expect(peek).not.toHaveAttribute("aria-modal");
    expect(trigger).toHaveFocus();

    fireEvent.pointerEnter(peek, { pointerType: "mouse" });
    fireEvent.pointerLeave(peek, { pointerType: "mouse" });
    await act(async () => vi.advanceTimersByTimeAsync(219));
    expect(screen.getByRole("dialog", { name: "History" })).toBeInTheDocument();
    await act(async () => vi.advanceTimersByTimeAsync(1));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("does not open when the pointer leaves before the hover intent delay", async () => {
    vi.useFakeTimers();
    render(<FootprintHistoryDrawer />);
    const trigger = screen.getByRole("button", { name: /history/i });

    fireEvent.pointerEnter(trigger, { pointerType: "mouse" });
    await act(async () => vi.advanceTimersByTimeAsync(80));
    fireEvent.pointerLeave(trigger, { pointerType: "mouse" });
    await act(async () => vi.advanceTimersByTimeAsync(300));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(apiMocks.getFootprintHistory).not.toHaveBeenCalled();
  });

  it("opens as a modal, focuses search, closes on Escape, and restores focus", async () => {
    const user = userEvent.setup();
    render(<FootprintHistoryDrawer />);
    const trigger = screen.getByRole("button", { name: /history/i });

    await user.click(trigger);

    expect(screen.getByRole("dialog", { name: "History" })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("searchbox", { name: "Find a past handle" })).toHaveFocus();
    });
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("closes when the user clicks the backdrop", async () => {
    const user = userEvent.setup();
    render(<FootprintHistoryDrawer />);
    await user.click(screen.getByRole("button", { name: /history/i }));
    const dialog = screen.getByRole("dialog", { name: "History" });

    fireEvent.mouseDown(dialog.parentElement as HTMLElement);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("loads grouped history, searches handles, and expands freshly loaded runs", async () => {
    const runsRequest = deferred<{
      items: FootprintHistoryRun[];
      next_cursor: string | null;
    }>();
    apiMocks.getFootprintHistoryRuns.mockReturnValueOnce(runsRequest.promise);
    const user = await openLoadedDrawer();

    await user.clear(screen.getByRole("searchbox", { name: "Find a past handle" }));
    await user.type(
      screen.getByRole("searchbox", { name: "Find a past handle" }),
      "oct",
    );
    await waitFor(() => {
      expect(apiMocks.getFootprintHistory).toHaveBeenCalledWith(
        expect.objectContaining({ q: "oct", limit: 10 }),
      );
    });

    await user.click(screen.getByRole("button", { name: /github · @octavia/i }));
    expect(screen.getByText("Loading runs…")).toBeInTheDocument();
    expect(apiMocks.getFootprintHistoryRuns).toHaveBeenCalledWith(
      readyRun.job_id,
      { cursor: undefined, limit: 10 },
    );

    await act(async () => {
      runsRequest.resolve({ items: [readyRun, deepRun], next_cursor: null });
    });

    expect((await screen.findAllByText(/Result saved/)).length).toBe(2);
    expect(screen.getByText("Deep · gpt-5.6-luna")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "View" })[0]).toHaveAttribute(
      "href",
      `/footprint/${readyRun.job_id}`,
    );
  });

  it("refreshes a selected run with a stable idempotency key and routes to it", async () => {
    const user = await openLoadedDrawer();
    await user.click(screen.getByRole("button", { name: /github · @octavia/i }));
    const refreshButtons = await screen.findAllByRole("button", { name: "Refresh" });

    await user.click(refreshButtons[0]);

    await waitFor(() => {
      expect(apiMocks.refreshFootprintJob).toHaveBeenCalledWith(
        readyRun.job_id,
        "history-refresh-key",
      );
      expect(pushMock).toHaveBeenCalledWith(`/footprint/${refreshedJob.job_id}`);
    });
  });

  it("requires confirmation before delete and clears terminal history in batches", async () => {
    const user = await openLoadedDrawer();
    await user.click(screen.getByRole("button", { name: /github · @octavia/i }));
    await screen.findAllByRole("button", { name: "Delete" });
    const confirmMock = vi.spyOn(window, "confirm");
    confirmMock.mockReturnValueOnce(false);

    await user.click(screen.getAllByRole("button", { name: "Delete" })[0]);
    expect(apiMocks.deleteFootprintJob).not.toHaveBeenCalled();

    confirmMock.mockReturnValueOnce(true);
    apiMocks.clearFootprintHistory
      .mockResolvedValueOnce({ deleted_count: 50, has_more: true })
      .mockResolvedValueOnce({ deleted_count: 2, has_more: false });
    await user.click(screen.getByRole("button", { name: "Clear all" }));

    await waitFor(() => {
      expect(apiMocks.clearFootprintHistory).toHaveBeenCalledTimes(2);
      expect(screen.getByText(/52 completed searches were permanently deleted/i)).toBeInTheDocument();
    });
    expect(confirmMock).toHaveBeenLastCalledWith(
      expect.stringContaining("Running searches will remain"),
    );
  });
});
