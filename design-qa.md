# Tracebrief UI revamp — design QA

**Source visual truth**

- Source archive: `/Users/isaaczhu/Downloads/Trace Brief UI Revamp.zip`
- Progress-location correction: `/var/folders/dr/t0d69zy53c5019wp84vrlcy00000gn/T/codex-clipboard-3f9ee241-b372-4915-9b8c-24f9e17ea11d.png`.
- Canonical flow: `Tracebrief Screens.dc.html` inside the archive (Search, Running, Checkpoint, Quick brief).
- Canonical Deep report: `Tracebrief Brief.dc.html` inside the archive.
- `Tracebrief Revamp.dc.html` was treated as exploratory report directions rather than four product routes.

**Rendered implementation**

- Local QA URL: `http://localhost:3418`
- Search: `/Users/isaaczhu/public-profile-search/qa-implementation-search.png`
- Running: `/Users/isaaczhu/public-profile-search/qa-implementation-running.png`
- Checkpoint: `/Users/isaaczhu/public-profile-search/qa-implementation-checkpoint.png`
- Quick: `/Users/isaaczhu/public-profile-search/qa-implementation-quick.png`
- Deep, segmented for readable review: `/Users/isaaczhu/public-profile-search/qa-implementation-deep-top.png`, `/Users/isaaczhu/public-profile-search/qa-implementation-deep-mid.png`, and `/Users/isaaczhu/public-profile-search/qa-implementation-deep-bottom.png`
- Responsive Deep: `/Users/isaaczhu/public-profile-search/qa-implementation-mobile.png`
- Corrected workflow status rings: `/Users/isaaczhu/public-profile-search/qa-implementation-progress-ring.png`

**Viewport, state, and normalization**

| State | Source pixels / CSS viewport | Implementation pixels / CSS viewport | Density and normalization |
| --- | --- | --- | --- |
| Search, Deep selected | 1180 × 955 / 1180 × 955 | 1180 × 955 / 1180 × 955 | Browser DPR 2; captured output normalized to 1× CSS pixels |
| Running, professional enrichment | 1180 × 1004 / 1180 × 1004 | 1180 × 1004 / 1180 × 1004 | 1× comparison |
| Checkpoint, awaiting anchor | 1180 × 701 / 1180 × 701 | 1180 × 701 / 1180 × 701 | 1× comparison |
| Quick, ready | 1180 × 1105 / 1180 × 1105 | 1180 × 1260 / 1180 × 1260 | Source padded with the canvas token for the taller realistic account rows; widths remain 1:1 |
| Deep, ready | 1280 × 2327 source capture | 1280 × 1258 top/mid/bottom viewport segments | Equal-width 1× focused comparisons; the supplied standalone source visibly clips its fixed desktop columns, while the implementation keeps them inside the viewport |
| Responsive Deep | No supplied mobile artboard | 720 × 900 / 720 × 900 | Inferred responsive behavior; no horizontal overflow |
| Workflow progress correction | 1464 × 600 source pixels / 732 × 300 normalized CSS region | 1530 × 380 browser capture with a 732 × 318 component region | Source is a 2× Retina crop normalized to 1×; the 732px implementation region is compared at 1× without scaling |

The fixture content differs from the mock names and source counts, so comparison judgments use the same product state and data density rather than treating fixture text as pixel-identical content.

**Full-view comparison evidence**

- Search: `/Users/isaaczhu/public-profile-search/qa-comparison-search.png`
- Running: `/Users/isaaczhu/public-profile-search/qa-comparison-running.png`
- Checkpoint: `/Users/isaaczhu/public-profile-search/qa-comparison-checkpoint.png`
- Quick: `/Users/isaaczhu/public-profile-search/qa-comparison-quick.png`
- Workflow progress correction: `/Users/isaaczhu/public-profile-search/qa-comparison-progress-ring.png`

These comparisons confirm the 56px editorial header, serif/sans hierarchy, 1180px desktop geometry, sharp 1px rules, warm canvas/paper surfaces, lime selection/status accent, two-column Running/Brief layouts, and state-specific content hierarchy.

**Focused comparison evidence**

- Deep header, verdict, competing identity, person rows, and evidence rail: `/Users/isaaczhu/public-profile-search/qa-comparison-deep-top.png`
- Deep account review, conclusion, limits, policy, and lower evidence rail: `/Users/isaaczhu/public-profile-search/qa-comparison-deep-bottom.png`
- Search selection and input treatment are readable in the full Search comparison; no additional crop was needed.
- Running phase rows and coverage are readable in the full Running comparison; no additional crop was needed.
- The corrected Running-row interaction is readable in the focused side-by-side comparison. It verifies the annotated location, right-aligned ring geometry, grey hollow waiting state, and clockwise determinate active arc. A later color-only follow-up aligned completion to the darker status accent.

**Findings**

- No actionable P0, P1, or P2 visual finding remains.
- Fonts and typography: Georgia/Times display and report text plus Inter/system sans UI text reproduce the supplied editorial hierarchy, scale, weights, tracking, and wrapping.
- Spacing and layout rhythm: desktop frames, report/sidebar tracks, section rules, candidate rows, and checkpoint cards align with the source. Quick is intentionally taller because real account reasons, secure profile links, and the honest view-only review notice are retained.
- Colors and visual tokens: ink, muted greens, paper/canvas, divider, lime accent, and danger policy colors match the supplied palette. Decorative gradients and rounded-card styling are absent from the revamp scope.
- Image quality and assets: the source contains no photographic, illustrated, logo-image, or custom icon assets that require reproduction. The circular meter is a live vector progress control driven by API progress, not a substitute for a supplied image asset.
- Copy and content: source framing is preserved, while dynamic copy stays truthful to current API behavior. Unsupported persisted review and checkpoint-skip mutations are not presented as working backend actions.
- Responsiveness: Search, Running, Checkpoint, Quick, and Deep all measured `scrollWidth === innerWidth` at 720px. The source Deep HTML's desktop clipping was not preserved.
- Accessibility and interaction states: form labels/radios, focus indicators, semantic progress, live status, evidence buttons, secure external links, reduced-motion rules, and print export remain available.
- Corrected workflow state: left-side numbers and visible Running/Waiting/Complete labels are removed. Each row now uses one 28px status ring on the right; the screen-reader-only status remains. At 0% and while waiting, the ring is a medium-grey outline with a transparent center. Known account-scan progress draws clockwise; phases without a numeric fraction use a continuous indeterminate arc. Completion transitions to the solid `#8eaf24` status circle in 380ms, matching “Building the brief,” while numeric progress retargets smoothly over 720ms. Reduced Motion removes both transitions and continuous rotation.
- Motion rationale: Apple’s current progress-indicator guidance prefers determinate progress when measurable, specifies that circular progress fills clockwise, and uses spinning circular activity for indeterminate work. Apple’s motion guidance calls for brief, precise, purposeful feedback and reduced automatic motion when Reduce Motion is enabled.

**Comparison history**

1. Initial comparison found a P1 Running mismatch: inherited `.deepProgressSteps` styles produced a dark block instead of the source's light editorial phase rows. Fixed by scoping transparent list/row backgrounds and removing the inherited frame in `revamp.css`. Post-fix evidence: `qa-comparison-running.png`.
2. Initial comparison found a P2 Checkpoint mismatch: inherited `.anchorCheckpoint` shadow created an unintended lime L-frame and the 52px title wrapped. Fixed with `box-shadow: none` and a 46px desktop headline. Post-fix evidence: `qa-comparison-checkpoint.png`.
3. Initial comparison found a P2 report geometry mismatch: the flexible source rail consumed too much width, and the Quick rail included Deep-only focus detail. Fixed with a 396px desktop evidence rail, responsive collapse below 1000px, and a compact Quick source index. Post-fix evidence: `qa-comparison-quick.png` and `qa-comparison-deep-top.png`.
4. Initial comparison found a P2 extra-region mismatch: a legacy “Search another identifier” footer appeared below every supplied artboard. It was removed; navigation and Re-run remain in the header. Post-fix evidence: all final comparisons.
5. Interaction QA found a P2 local-state bug: Exclude → Undo restored an initially verified account to open. Added per-account pre-exclusion restoration. Retest changed counts from `2 verified · 1 open · 0 set aside` to `1 verified · 1 open · 1 set aside` on Exclude and back to the original counts on Undo.
6. User annotation identified a P1 target mismatch: the first pass changed the sidebar Coverage bar instead of the per-stage horizontal indicator. The sidebar meter was restored. The stage bar was removed and replaced with a right-aligned circular state system. Post-fix evidence: `qa-comparison-progress-ring.png`.
7. Follow-up interaction direction removed redundant left-side numbers and visible state words, and specified grey/hollow → active clockwise arc → solid completion. The corrected implementation preserves the same row copy and layout hierarchy, retains accessible hidden state text, and has no horizontal overflow in the focused component. Post-fix evidence: `qa-comparison-progress-ring.png`.
8. A final color-only follow-up changed the completed circle from lime to the same dark olive status token (`#8eaf24`) used by “Building the brief.”

**Primary interactions and diagnostics**

- Quick/Deep radio selection updates the selected card and submitted mode.
- Operator view disclosure opens and exposes current job/catalog timing context.
- Checkpoint choices remain wired to the existing anchor API.
- Stop remains wired to the existing cancellation API.
- Local Verify/Exclude/Undo review state works and is explicitly labeled view-only.
- Citation controls move focus to the matching evidence source; source 2 was verified in the focused panel.
- Quick-to-Deep creates a new Deep job through the existing creation contract.
- Export invokes browser print/export.
- Search, all four job states, and responsive checks produced no browser console errors.
- The refreshed production app at port 3417 produced no browser warnings or errors after the status-ring build. The focused state comparison was browser-rendered in the in-app browser; CSS timing/state inspection confirmed the 28px ring, 720ms progress interpolation, 380ms completion transition, and removal of visible status labels.

**Follow-up polish**

- P3: pointer automation leaves the accessible radio focus outline visible in the Search comparison; this is a valid focus state and does not affect the normal selected-card treatment.
- P3: a future backend could replace the explicitly local account review controls with persisted mutations and add a true “continue without choosing” checkpoint action.
- P3: a live scan was not created solely for QA, so the final grey-to-status-color transition was inspected from browser-rendered states and computed motion values rather than recorded as a video.

**Implementation checklist**

- [x] Match Search, Running, Checkpoint, Quick, and selected Deep visual targets.
- [x] Preserve polling, retry, cancellation, anchor selection, and report-loading behavior.
- [x] Verify desktop and 720px responsive layouts.
- [x] Verify core interactions and console output.
- [x] Replace the annotated per-stage bar with the grey hollow → clockwise arc → dark status-color completion ring and remove redundant row numbers/state words.
- [x] Pass TypeScript, lint, web tests, production build, and `git diff --check`.

final result: passed
