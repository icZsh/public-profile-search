import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const readWebFile = (path) =>
  readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("the limited-evaluation UI remains private and explains its URL-only boundary", async () => {
  const [layout, page] = await Promise.all([
    readWebFile("app/layout.tsx"),
    readWebFile("app/page.tsx"),
  ]);

  assert.match(layout, /index: false/);
  assert.match(layout, /follow: false/);
  assert.match(page, /public GitHub profile you control/i);
  assert.match(page, /No username discovery/i);
  assert.match(page, /local limited-evaluation prototype/i);
});

test("the search form supports staged GitHub verification and keeps a separate demo", async () => {
  const searchForm = await readWebFile("components/SearchForm.tsx");

  assert.match(searchForm, /type="url"/);
  assert.match(searchForm, /Verify profile/);
  assert.match(searchForm, /verify control/i);
  assert.match(searchForm, /Operator eligibility review/i);
  assert.match(searchForm, /Refresh approval/);
  assert.match(searchForm, /Build brief/);
  assert.match(searchForm, /Run synthetic demo/);
  assert.doesNotMatch(searchForm, /\breadOnly\b/);
  assert.doesNotMatch(
    searchForm,
    /<input[^>]+(?:id|name)=["'](?:username|user-?id)["']/i,
  );
});

test("the browser client uses eligibility APIs without exposing admin credentials", async () => {
  const api = await readWebFile("lib/api.ts");

  assert.match(api, /POST/);
  assert.match(api, /\/v1\/eligibility-verifications/);
  assert.match(api, /\/complete/);
  assert.match(api, /createSyntheticSearchJob/);
  assert.doesNotMatch(api, /PROTOTYPE_ADMIN|Admin-Token/i);
});

test("external evidence links use no-opener and no-referrer protections", async () => {
  const evidence = await readWebFile("components/EvidenceDrawer.tsx");

  assert.match(evidence, /noopener noreferrer/);
  assert.match(evidence, /referrerPolicy="no-referrer"/);
  assert.match(evidence, /View source/);
  assert.doesNotMatch(evidence, /Synthetic source/);
});
