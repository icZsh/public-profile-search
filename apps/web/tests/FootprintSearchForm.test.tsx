import type { FootprintJob } from "@public-profile-search/generated-api-client";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  createFootprintJob: vi.fn(),
  createIdempotencyKey: vi.fn(),
}));
const pushMock = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", () => apiMocks);
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

import { FootprintSearchForm } from "@/components/FootprintSearchForm";

const createdJob = {
  job_id: "11111111-1111-4111-8111-111111111111",
} as FootprintJob;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

describe("FootprintSearchForm", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  beforeEach(() => {
    apiMocks.createIdempotencyKey.mockReturnValue("search-create-key");
    apiMocks.createFootprintJob.mockResolvedValue(createdJob);
    pushMock.mockReset();
  });

  it("defaults to Quick and submits the focused search with Enter", async () => {
    const user = userEvent.setup();
    render(<FootprintSearchForm />);

    const deepToggle = screen.getByRole("button", { name: "Deep search mode" });
    const searchButton = screen.getByRole("button", { name: "Build the brief" });
    const tooltip = screen.getByRole("tooltip", { hidden: true });
    expect(deepToggle).toHaveAttribute("aria-pressed", "false");
    expect(deepToggle).toHaveAttribute("aria-describedby", "search-depth-tooltip");
    expect(tooltip).toHaveAttribute("aria-hidden", "true");
    expect(tooltip).toHaveTextContent(
      "QuickFocused account and people search with cited answers.",
    );
    expect(deepToggle.closest(".traceDeepModeControl")?.nextElementSibling).toBe(
      searchButton,
    );
    expect(searchButton).toHaveTextContent("");
    expect(searchButton.querySelector("svg")).not.toBeNull();
    expect(screen.queryByRole("combobox", { name: /story model/i })).not.toBeInTheDocument();

    await user.type(
      screen.getByRole("textbox", { name: "Handle or public profile URL" }),
      "@alice{Enter}",
    );

    await waitFor(() => expect(apiMocks.createFootprintJob).toHaveBeenCalledTimes(1));
    const [payload, idempotencyKey] = apiMocks.createFootprintJob.mock.calls[0];
    expect(payload).toMatchObject({
      seed: {
        kind: "bare_handle",
        identifier_type: "handle",
        identifier: "alice",
      },
      search_mode: "quick",
      locale: "en-US",
      history_policy: "prefer_existing",
    });
    expect(payload).not.toHaveProperty("synthesis_model");
    expect(idempotencyKey).toBe("search-create-key");
    expect(pushMock).toHaveBeenCalledWith(`/footprint/${createdJob.job_id}`);
  });

  it("uses the inline Deep control without submitting and sends the selected model", async () => {
    const user = userEvent.setup();
    render(<FootprintSearchForm />);

    const deepToggle = screen.getByRole("button", { name: "Deep search mode" });
    await user.click(deepToggle);

    expect(apiMocks.createFootprintJob).not.toHaveBeenCalled();
    expect(deepToggle).toHaveAttribute("aria-pressed", "true");

    const model = screen.getByRole("combobox", { name: /story model/i });
    const modelControl = model.closest(".traceInlineModelPicker");
    const deepControl = deepToggle.closest(".traceDeepModeControl");
    const searchButton = screen.getByRole("button", { name: "Build the brief" });
    expect(model.closest(".traceUnifiedSearch")).not.toBeNull();
    expect(modelControl?.nextElementSibling).toBe(deepControl);
    expect(deepControl?.nextElementSibling).toBe(searchButton);
    await user.selectOptions(model, "openai/gpt-5.4-mini");
    await user.type(
      screen.getByRole("textbox", { name: "Handle or public profile URL" }),
      "https://github.com/alice",
    );
    await user.click(screen.getByRole("button", { name: "Build the brief" }));

    await waitFor(() => expect(apiMocks.createFootprintJob).toHaveBeenCalledTimes(1));
    expect(apiMocks.createFootprintJob.mock.calls[0][0]).toMatchObject({
      seed: {
        kind: "profile_url",
        profile_url: "https://github.com/alice",
      },
      search_mode: "deep",
      synthesis_model: "openai/gpt-5.4-mini",
    });
  });

  it("switches back to Quick and omits the remembered Deep model", async () => {
    const user = userEvent.setup();
    render(<FootprintSearchForm />);

    const deepToggle = screen.getByRole("button", { name: "Deep search mode" });
    await user.click(deepToggle);
    await user.selectOptions(
      screen.getByRole("combobox", { name: /story model/i }),
      "z-ai/glm-5.2",
    );
    await user.click(deepToggle);

    expect(deepToggle).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByRole("combobox", { name: /story model/i })).not.toBeInTheDocument();

    await user.type(
      screen.getByRole("textbox", { name: "Handle or public profile URL" }),
      "alice",
    );
    await user.click(screen.getByRole("button", { name: "Build the brief" }));

    await waitFor(() => expect(apiMocks.createFootprintJob).toHaveBeenCalledTimes(1));
    const payload = apiMocks.createFootprintJob.mock.calls[0][0];
    expect(payload.search_mode).toBe("quick");
    expect(payload).not.toHaveProperty("synthesis_model");
  });

  it("keeps the mode comparison hoverable and lets Escape dismiss keyboard focus", async () => {
    vi.useFakeTimers();
    render(<FootprintSearchForm />);

    const deepToggle = screen.getByRole("button", { name: "Deep search mode" });
    const control = deepToggle.closest(".traceDeepModeControl");
    const tooltip = screen.getByRole("tooltip", { hidden: true });
    expect(control).not.toBeNull();

    fireEvent.pointerEnter(control!, { pointerType: "mouse" });
    expect(tooltip).toHaveAttribute("aria-hidden", "false");

    fireEvent.pointerLeave(control!, {
      pointerType: "mouse",
      relatedTarget: tooltip,
    });
    await act(async () => vi.advanceTimersByTimeAsync(200));
    expect(tooltip).toHaveAttribute("aria-hidden", "false");

    fireEvent.pointerLeave(control!, {
      pointerType: "mouse",
      relatedTarget: document.body,
    });
    await act(async () => vi.advanceTimersByTimeAsync(200));
    expect(tooltip).toHaveAttribute("aria-hidden", "true");

    act(() => deepToggle.focus());
    expect(tooltip).toHaveAttribute("aria-hidden", "false");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(tooltip).toHaveAttribute("aria-hidden", "true");
    expect(deepToggle).toHaveFocus();
  });

  it("does not latch the mode comparison after pointer activation", async () => {
    vi.useFakeTimers();
    render(<FootprintSearchForm />);

    const deepToggle = screen.getByRole("button", { name: "Deep search mode" });
    const control = deepToggle.closest(".traceDeepModeControl");
    const tooltip = screen.getByRole("tooltip", { hidden: true });
    expect(control).not.toBeNull();

    fireEvent.pointerEnter(control!, { pointerType: "mouse" });
    fireEvent.pointerDown(deepToggle, { pointerType: "mouse" });
    act(() => deepToggle.focus());
    fireEvent.pointerLeave(control!, {
      pointerType: "mouse",
      relatedTarget: document.body,
    });
    await act(async () => vi.advanceTimersByTimeAsync(200));
    expect(tooltip).toHaveAttribute("aria-hidden", "true");
    expect(deepToggle).toHaveFocus();

    fireEvent.blur(deepToggle);
    fireEvent.pointerEnter(control!, { pointerType: "touch" });
    fireEvent.pointerDown(deepToggle, { pointerType: "touch" });
    act(() => deepToggle.focus());
    expect(tooltip).toHaveAttribute("aria-hidden", "true");
  });

  it("disables every search control while one creation is in flight", async () => {
    const request = deferred<FootprintJob>();
    apiMocks.createFootprintJob.mockReturnValueOnce(request.promise);
    const user = userEvent.setup();
    render(<FootprintSearchForm />);

    const input = screen.getByRole("textbox", { name: "Handle or public profile URL" });
    const deepToggle = screen.getByRole("button", { name: "Deep search mode" });
    await user.type(input, "alice");
    await user.click(screen.getByRole("button", { name: "Build the brief" }));

    expect(input).toBeDisabled();
    expect(deepToggle).toBeDisabled();
    const startingButton = screen.getByRole("button", { name: "Starting the brief" });
    expect(startingButton).toBeDisabled();
    expect(startingButton.querySelector(".traceSearchBusySpinner")).not.toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("Starting the brief.");
    expect(apiMocks.createFootprintJob).toHaveBeenCalledTimes(1);

    request.resolve(createdJob);
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith(`/footprint/${createdJob.job_id}`));
  });
});
