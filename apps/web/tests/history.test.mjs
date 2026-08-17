import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const readWebFile = (path) =>
  readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("the footprint API client exposes owner-scoped history, refresh, and deletion calls", async () => {
  const api = await readWebFile("lib/api.ts");

  assert.match(api, /FootprintHistoryGroupPage/);
  assert.match(api, /FootprintHistoryRunPage/);
  assert.match(api, /ClearFootprintHistoryResponse/);
  assert.match(api, /export async function getFootprintHistory\(/);
  assert.match(api, /if \(q\) params\.set\("q", q\)/);
  assert.match(api, /params\.set\("cursor", cursor\)/);
  assert.match(api, /params\.set\("limit", String\(limit\)\)/);
  assert.match(api, /cache: "no-store"/);
  assert.match(api, /\/history/);
  assert.match(api, /export async function refreshFootprintJob/);
  assert.match(api, /\/refresh/);
  assert.match(api, /"Idempotency-Key": idempotencyKey/);
  assert.match(api, /export async function deleteFootprintJob/);
  assert.match(api, /export async function clearFootprintHistory/);
  assert.match(api, /method: "DELETE"/);
  assert.match(api, /limit = 50/);
});

test("the homepage puts history before the brand and removes operator view", async () => {
  const [page, form, resultRoute, experience] = await Promise.all([
    readWebFile("app/page.tsx"),
    readWebFile("components/FootprintSearchForm.tsx"),
    readWebFile("app/footprint/[jobId]/page.tsx"),
    readWebFile("components/FootprintJobExperience.tsx"),
  ]);

  assert.match(page, /FootprintHistoryDrawer/);
  assert.match(page, /<FootprintHistoryDrawer \/>/);
  assert.ok(
    page.indexOf("<FootprintHistoryDrawer />") <
      page.indexOf('className="traceBrand"'),
  );
  assert.doesNotMatch(page, /Operator view/i);
  assert.doesNotMatch(experience, /Operator view/i);
  assert.match(form, /history_policy: "prefer_existing"/);
  assert.doesNotMatch(resultRoute, /FootprintHistoryDrawer/);
});

test("history drawer supports grouped navigation, accessible dismissal, and safe mutations", async () => {
  const history = await readWebFile("components/FootprintHistoryDrawer.tsx");

  assert.match(history, /aria-expanded=\{open\}/);
  assert.match(history, /aria-haspopup="dialog"/);
  assert.match(history, /ClockCounterClockwiseIcon/);
  assert.match(history, /className="traceHistoryTriggerIcon"/);
  assert.match(history, /aria-controls="footprint-history-drawer"/);
  assert.match(history, /role="dialog"/);
  assert.match(history, /aria-modal=\{drawerMode === "modal"/);
  assert.match(history, /scheduleHoverOpen/);
  assert.match(history, /drawerModeRef\.current = "peek"/);
  assert.match(history, /event\.key === "Escape"/);
  assert.match(history, /event\.key !== "Tab"/);
  assert.match(history, /restoreFocusRef/);
  assert.match(history, /event\.target === event\.currentTarget/);
  assert.match(history, /searchInputRef\.current\?\.focus/);
  assert.match(history, /getFootprintHistoryRuns/);
  assert.match(history, /aria-expanded=\{expanded\}/);
  assert.match(history, /Load more searches/);
  assert.match(history, /Show older runs/);
  assert.match(history, /EyeIcon/);
  assert.match(history, /ArrowClockwiseIcon/);
  assert.match(history, /TrashIcon/);
  assert.match(history, /aria-label="View"/);
  assert.match(history, /aria-label="Refresh"/);
  assert.match(history, /aria-label="Delete"/);
  assert.match(history, /data-tooltip="View"/);
  assert.match(history, /data-tooltip="Refresh"/);
  assert.match(history, /data-tooltip="Delete"/);
  assert.match(history, /terminalStatuses\.has\(run\.status\)/);
  assert.match(history, /Permanently delete this completed search/);
  assert.match(history, /Running searches will remain/);
  assert.match(history, /clearFootprintHistory\(50\)/);
  assert.match(history, /while|for \(let batch/);
  assert.match(history, /role="status" aria-live="polite"/);
  assert.match(history, /No matching searches/);
  assert.match(history, /Try again/);
});

test("saved result pages show their timestamp and start a revalidated run", async () => {
  const [experience, styles] = await Promise.all([
    readWebFile("components/FootprintJobExperience.tsx"),
    readWebFile("app/revamp.css"),
  ]);

  assert.match(experience, /className="traceSavedSearchMeta"/);
  assert.match(experience, /Searched <time dateTime=\{job\.accepted_at\}/);
  assert.match(experience, /Available until <time dateTime=\{job\.expires_at\}/);
  assert.match(experience, /refreshFootprintJob/);
  assert.match(experience, /Refresh with same settings/);
  assert.match(experience, /createIdempotencyKey\(\)/);
  assert.match(experience, /aria-busy=\{refreshingSavedSearch\}/);
  assert.match(styles, /\.traceSavedSearchMeta/);
  assert.doesNotMatch(
    styles,
    /\.traceHistoryTrigger\s*\{[^}]*position:\s*fixed/,
  );
  assert.match(styles, /\.traceHistoryTrigger\s*\{[^}]*border:\s*0/);
  assert.match(styles, /\.traceHistoryTriggerIcon/);
  assert.match(styles, /\.traceHistoryDrawer\s*\{[\s\S]*width: min\(372px/);
  assert.match(styles, /@media \(max-width: 720px\)[\s\S]*\.traceHistoryDrawer/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)[\s\S]*\.traceHistoryDrawer/);
});
