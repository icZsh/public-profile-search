import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const readWebFile = (path) =>
  readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("the discovery homepage remains private and presents one flexible search input", async () => {
  const [layout, page, api, nextConfig] = await Promise.all([
    readWebFile("app/layout.tsx"),
    readWebFile("app/page.tsx"),
    readWebFile("lib/api.ts"),
    readWebFile("next.config.ts"),
  ]);

  assert.match(layout, /index: false/);
  assert.match(layout, /follow: false/);
  assert.match(layout, /public digital footprint discovery/i);
  assert.match(page, /handle or public profile URL/i);
  assert.match(page, /infers platform context/i);
  assert.match(page, /FootprintSearchForm/);
  assert.match(page, /Candidate profiles and coverage appear progressively/i);
  assert.match(api, /NEXT_PUBLIC_API_BASE_URL \?\? "\/api"/);
  assert.match(nextConfig, /source: "\/api\/:path\*"/);
  assert.match(nextConfig, /destination: "http:\/\/127\.0\.0\.1:8800\/:path\*"/);
});

test("the legacy search form remains available for staged GitHub verification", async () => {
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

test("the footprint form submits a discriminated seed and opens the discovery route", async () => {
  const [searchForm, synthesisModels, revampStyles] = await Promise.all([
    readWebFile("components/FootprintSearchForm.tsx"),
    readWebFile("lib/synthesis-models.ts"),
    readWebFile("app/revamp.css"),
  ]);

  assert.match(searchForm, /name="identifier"/);
  assert.match(searchForm, /placeholder="Handle or public profile URL"/);
  assert.doesNotMatch(searchForm, /octaviyao/i);
  assert.match(searchForm, /kind: "profile_url"/);
  assert.match(searchForm, /profile_url: normalizedIdentifier/);
  assert.match(searchForm, /kind: "bare_handle"/);
  assert.match(searchForm, /identifier_type: "handle"/);
  assert.match(searchForm, /normalizedIdentifier\.replace\(\/\^@\+\/, ""\)/);
  assert.match(searchForm, /isHttpProfileUrl\(normalizedIdentifier\)/);
  assert.doesNotMatch(searchForm, /id="seed-platform"/);
  assert.doesNotMatch(searchForm, /kind: "platform_identifier"/);
  assert.match(searchForm, /useState<FootprintSearchMode>\("quick"\)/);
  assert.match(searchForm, /name="search_mode"/);
  assert.match(searchForm, /className="traceDeepModeToggle"/);
  assert.match(searchForm, /aria-pressed=\{searchMode === "deep"\}/);
  assert.match(searchForm, /setSearchMode\(\(current\) => current === "deep" \? "quick" : "deep"\)/);
  assert.doesNotMatch(searchForm, /type="radio"/);
  assert.match(searchForm, /search_mode: searchMode/);
  assert.match(searchForm, /useState<FootprintSynthesisModel>\(DEFAULT_SYNTHESIS_MODEL\)/);
  assert.match(
    searchForm,
    /\.\.\.\(searchMode === "deep"[\s\S]*\? \{ synthesis_model: synthesisModel \}[\s\S]*: \{\}\)/,
  );
  assert.match(searchForm, /name="synthesis_model"/);
  assert.match(searchForm, /<select/);
  assert.match(searchForm, /htmlFor="synthesis-model"/);
  assert.doesNotMatch(searchForm, /<input[^>]*name="synthesis_model"/);
  assert.match(searchForm, /className="traceInlineModelPicker"/);
  assert.doesNotMatch(searchForm, /selectedSynthesisOption/);
  assert.doesNotMatch(searchForm, /Prices and relative latency estimates can change/);
  assert.match(searchForm, /role="tooltip"/);
  assert.match(searchForm, /id="search-depth-tooltip"/);
  assert.match(searchForm, /MagnifyingGlassIcon/);
  assert.match(searchForm, /aria-label=\{busy \? "Starting the brief" : "Build the brief"\}/);
  assert.match(synthesisModels, /"openai\/gpt-5\.6-luna"/);
  assert.match(synthesisModels, /"openai\/gpt-5\.4-nano"/);
  assert.match(synthesisModels, /"openai\/gpt-5\.4-mini"/);
  assert.match(synthesisModels, /"openai\/gpt-oss-120b"/);
  assert.match(synthesisModels, /"deepseek\/deepseek-v4-flash-0731"/);
  assert.match(synthesisModels, /"qwen\/qwen3\.5-35b-a3b"/);
  assert.match(synthesisModels, /"z-ai\/glm-5\.2"/);
  assert.match(synthesisModels, /DEFAULT_SYNTHESIS_MODEL/);
  assert.match(synthesisModels, /Balanced value/);
  assert.match(synthesisModels, /Fast budget/);
  assert.match(synthesisModels, /Quality/);
  assert.doesNotMatch(synthesisModels, /badge:/);
  assert.doesNotMatch(searchForm, /option\.badge/);
  assert.match(
    synthesisModels,
    /inputPrice: "\$0\.10",[\s\S]*outputPrice: "\$0\.60"/,
  );
  assert.match(
    synthesisModels,
    /inputPrice: "\$0\.20",[\s\S]*outputPrice: "\$1\.25"/,
  );
  assert.match(
    synthesisModels,
    /inputPrice: "\$0\.75",[\s\S]*outputPrice: "\$4\.50"/,
  );
  assert.match(
    synthesisModels,
    /inputPrice: "\$0\.037",[\s\S]*outputPrice: "\$0\.17"/,
  );
  assert.match(
    synthesisModels,
    /inputPrice: "\$0\.08",[\s\S]*outputPrice: "\$0\.18"/,
  );
  assert.match(
    synthesisModels,
    /inputPrice: "\$0\.14",[\s\S]*outputPrice: "\$1\.00"/,
  );
  assert.match(
    synthesisModels,
    /inputPrice: "\$0\.76",[\s\S]*outputPrice: "\$2\.42"/,
  );
  assert.match(revampStyles, /\.traceInlineModelPicker/);
  assert.match(revampStyles, /\.traceInlineModelPicker select:focus-visible/);
  assert.match(revampStyles, /\.traceSearchModeTooltip/);
  assert.match(revampStyles, /\.traceSearchModeTooltipOpen/);
  assert.match(revampStyles, /\.traceSearchBusySpinner/);
  assert.match(revampStyles, /\.traceUnifiedSearch\s*\{[^}]*border-radius:\s*999px/);
  assert.match(revampStyles, /\.traceUnifiedSearch:focus-within/);
  assert.match(revampStyles, /\.traceDeepModeToggle\[aria-pressed="true"\]/);
  assert.match(revampStyles, /\.traceSearchSubmit\s*\{[^}]*width:\s*44px/);
  assert.doesNotMatch(revampStyles, /\.traceSearchActions/);
  assert.doesNotMatch(revampStyles, /\.traceSearchDepthSummary/);
  assert.doesNotMatch(revampStyles, /\.traceModelPicker/);
  assert.doesNotMatch(revampStyles, /\.traceModelOptions/);
  assert.match(
    revampStyles,
    /@media \(max-width: 720px\)[\s\S]*\.traceUnifiedSearchDeep\s*\{[^}]*minmax\(72px, 100px\)/,
  );
  assert.match(revampStyles, /@media \(max-width: 720px\)[\s\S]*\.traceInlineModelPicker select/);
  assert.match(searchForm, /focused account and people search/i);
  assert.match(searchForm, /broader account and professional search/i);
  assert.doesNotMatch(searchForm, /\b(?:20|56)(?:-site| sites?)/i);
  assert.doesNotMatch(searchForm, /<legend>Search depth<\/legend>/);
  assert.match(searchForm, /createFootprintJob/);
  assert.match(searchForm, /creationAttempt/);
  assert.match(searchForm, /payloadSignature/);
  assert.match(searchForm, /idempotencyKey/);
  assert.match(searchForm, /router\.push\(`\/footprint\/\$\{job\.job_id\}`\)/);
  assert.match(searchForm, /No account match is assumed to be the same person/i);
});

test("the browser client uses eligibility APIs without exposing admin credentials", async () => {
  const api = await readWebFile("lib/api.ts");

  assert.match(api, /POST/);
  assert.match(api, /\/v1\/eligibility-verifications/);
  assert.match(api, /\/complete/);
  assert.match(api, /createSyntheticSearchJob/);
  assert.doesNotMatch(api, /PROTOTYPE_ADMIN|Admin-Token/i);
});

test("client idempotency keys work on insecure local-network HTTP origins", async () => {
  const [api, searchForm, experience] = await Promise.all([
    readWebFile("lib/api.ts"),
    readWebFile("components/FootprintSearchForm.tsx"),
    readWebFile("components/FootprintJobExperience.tsx"),
  ]);

  assert.match(api, /export function createIdempotencyKey/);
  assert.match(api, /cryptoProvider\?\.randomUUID/);
  assert.match(api, /cryptoProvider\?\.getRandomValues/);
  assert.match(api, /bytes\[6\].*0x40/);
  assert.match(api, /bytes\[8\].*0x80/);
  assert.doesNotMatch(searchForm, /crypto\.randomUUID/);
  assert.doesNotMatch(experience, /crypto\.randomUUID/);
});

test("external evidence links use no-opener and no-referrer protections", async () => {
  const evidence = await readWebFile("components/EvidenceDrawer.tsx");

  assert.match(evidence, /noopener noreferrer/);
  assert.match(evidence, /referrerPolicy="no-referrer"/);
  assert.match(evidence, /View source/);
  assert.doesNotMatch(evidence, /Synthetic source/);
});

test("the footprint client polls candidates and renders the terminal evidence-linked brief", async () => {
  const [api, experience, candidates, brief, traceBrief, route, styles, revampStyles] = await Promise.all([
    readWebFile("lib/api.ts"),
    readWebFile("components/FootprintJobExperience.tsx"),
    readWebFile("components/CandidateResults.tsx"),
    readWebFile("components/FootprintBrief.tsx"),
    readWebFile("components/TraceFootprintBrief.tsx"),
    readWebFile("app/footprint/[jobId]/page.tsx"),
    readWebFile("app/globals.css"),
    readWebFile("app/revamp.css"),
  ]);

  assert.match(api, /\/v1\/footprint-jobs/);
  assert.match(api, /\/candidates/);
  assert.match(api, /createFootprintJob/);
  assert.match(api, /getFootprintJob/);
  assert.match(api, /cancelFootprintJob/);
  assert.match(api, /method: "POST"/);
  assert.match(api, /getFootprintCandidates/);
  assert.match(api, /selectFootprintAnchor/);
  assert.match(api, /getFootprintBrief/);
  assert.match(api, /getFootprintEvidence/);
  assert.match(api, /\/anchor/);
  assert.match(api, /\/cancel/);
  assert.match(api, /\/brief/);
  assert.match(api, /\/evidence/);
  assert.match(experience, /setTimeout\(refresh/);
  assert.match(experience, /getFootprintCandidates/);
  assert.match(experience, /getFootprintBrief/);
  assert.match(experience, /getFootprintEvidence/);
  assert.match(experience, /coverage\?\.completed/);
  assert.match(experience, /job\?\.search_mode === "deep"/);
  assert.match(experience, /Deep story/);
  assert.match(experience, /job\?\.deep_progress\?\.current_phase/);
  assert.match(experience, /job\.deep_progress\?\.phase_started_at/);
  assert.match(experience, /job\?\.deep_progress\?\.finished_at/);
  assert.match(experience, /job\.accepted_at/);
  assert.match(experience, /Account scan/);
  assert.match(experience, /Professional enrichment/);
  assert.match(experience, /Deep report generation/);
  assert.match(experience, /Finalizing/);
  assert.match(experience, /deepProgressStepState/);
  assert.match(experience, /deepProgressStep-paused/);
  assert.match(experience, /className="traceStepCompleteCheck"/);
  assert.match(experience, /Progress paused/);
  assert.match(experience, /Elapsed/);
  assert.doesNotMatch(experience, /deepStoryPreparing/);
  assert.match(experience, /Preparing Deep story/);
  assert.doesNotMatch(experience, /Operator view/i);
  assert.match(experience, /job\.seed\.kind === "profile_url"/);
  assert.match(experience, /job\.seed\.profile_url/);
  assert.doesNotMatch(experience, /job\.catalog\.profile/);
  assert.match(experience, /aria-live="polite"/);
  assert.match(experience, /aria-atomic="true"/);
  assert.match(experience, /reason\.status === 404/);
  assert.match(experience, /reason\.status === 409/);
  assert.match(experience, /"no_candidates"/);
  assert.match(experience, /"awaiting_anchor"/);
  assert.match(experience, /Choose a starting profile/);
  assert.match(experience, /selectFootprintAnchor/);
  assert.match(experience, /cancelFootprintJob/);
  assert.match(experience, /Stop search/);
  assert.match(experience, /onClick=\{stopSearch\}/);
  assert.match(experience, /Stopping…/);
  assert.match(experience, /job && !terminal/);
  assert.match(experience, /aria-busy=\{stopping\}/);
  assert.match(experience, /stopSearchError/);
  assert.match(experience, /terminalStatuses\.has\(current\.status\)\) setStopError\(""\)/);
  assert.match(experience, /setPollGeneration/);
  assert.match(experience, /\[jobId, pollGeneration\]/);
  assert.match(experience, /onSelectAnchor=\{chooseAnchor\}/);
  assert.match(experience, /footprint report is unavailable/);
  assert.match(experience, /setPollingStopped\(true\)/);
  assert.match(experience, /maxTransientRetries/);
  assert.match(experience, /Start another search/);
  assert.match(experience, /className="traceJobFooter"/);
  assert.match(experience, /startDeepRun\(model: FootprintSynthesisModel\)/);
  assert.match(experience, /synthesis_model: model/);
  assert.match(traceBrief, /<span>Story model<\/span>/);
  assert.match(traceBrief, /SYNTHESIS_MODEL_OPTIONS\.map/);
  assert.doesNotMatch(traceBrief, /option\.badge/);
  assert.match(traceBrief, /onRunDeep\?\.\(selectedModel\)/);
  assert.ok(
    experience.indexOf("<FootprintBrief") <
      experience.indexOf("<CandidateResults"),
  );
  assert.match(
    experience,
    /\{!brief && \(job \|\| !pollingStopped\) \? \(/,
  );
  assert.match(candidates, /Handle reuse alone/);
  assert.match(candidates, /Choose the known starting profile/);
  assert.match(candidates, /candidate\.anchor_eligible/);
  assert.match(candidates, /Use as starting profile/);
  assert.match(candidates, /Search stopped before any candidates were saved/);
  assert.match(candidates, /aria-busy=\{selectingCandidateId !== null\}/);
  assert.match(candidates, /role="alert"/);
  assert.match(candidates, /noopener noreferrer/);
  assert.match(candidates, /referrerPolicy="no-referrer"/);
  assert.match(brief, /overall_identity_status/);
  assert.match(brief, /What supports this association/);
  assert.match(brief, /What limits it/);
  assert.match(brief, /Evidence index/);
  assert.match(brief, /Identity snapshot/);
  assert.match(brief, /What you probably want to know/);
  assert.match(brief, /Probably based in/);
  assert.match(brief, /What they do/);
  assert.match(brief, /Public interests/);
  assert.match(brief, /Appears to like/);
  assert.match(brief, /Explicitly dislikes/);
  assert.match(brief, /No explicit public dislikes were found/);
  assert.match(brief, /Career and education timeline/);
  assert.match(brief, /No dated work or education history was supported/);
  assert.match(brief, /profile\.career_timeline/);
  assert.doesNotMatch(
    brief,
    /profile\.(?:platform_purposes|activity_patterns|footprint_risks)/,
  );
  assert.ok(
    brief.indexOf("<SubjectProfileSnapshot") <
      brief.indexOf('className="deepStoryLead"'),
  );
  assert.match(brief, /Key findings/);
  assert.match(brief, /Channel coverage/);
  assert.match(brief, /association_reasons/);
  assert.match(brief, /highlight\.source_ids/);
  assert.match(brief, /channel\.source_ids/);
  assert.match(brief, /step\.source_ids/);
  assert.match(brief, /Account synthesis/);
  assert.match(brief, /CitedTextContent/);
  assert.match(brief, /noopener noreferrer/);
  assert.match(brief, /referrerPolicy="no-referrer"/);
  assert.match(styles, /\.footprintBriefHeader h2[\s\S]*overflow-wrap: anywhere/);
  assert.match(styles, /\.narrativeSources a,[\s\S]*max-width: 100%/);
  assert.match(styles, /\.anchorCheckpoint/);
  assert.match(styles, /\.candidateAnchorButton:focus-visible/);
  assert.match(styles, /\.stopSearchButton:focus-visible/);
  assert.match(styles, /\.stopSearchButton:disabled/);
  assert.match(styles, /\.profileTimeline/);
  assert.match(styles, /\.deepProgressCard/);
  assert.match(styles, /\.deepProgressSteps/);
  assert.match(styles, /\.deepProgressStep-running/);
  assert.match(styles, /@keyframes deep-progress-sweep/);
  assert.match(
    revampStyles,
    /\.traceStepStatusRing-complete\s*\{[\s\S]*?box-shadow: none;/,
  );
  assert.match(
    revampStyles,
    /\.traceStepCompleteCheck\s*\{[\s\S]*?stroke: #fff;/,
  );
  assert.match(revampStyles, /\.traceQuickModelSelect:focus-visible/);
  assert.doesNotMatch(
    styles,
    /\.profile(?:Purpose|Activity|Risk|Mitigation)/,
  );
  assert.match(route, /FootprintJobExperience/);
});
