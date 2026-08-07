import type {
  EvidenceItem,
  FootprintBrief as FootprintBriefType,
  FootprintCitedText,
  FootprintDeepProfileAnswer,
  FootprintDeepProfileTrait,
  FootprintDeepSubjectProfile,
  FootprintDeepTimelineEntry,
} from "@public-profile-search/generated-api-client";

function words(value: string): string {
  return value.replaceAll("_", " ");
}

function safeSourceHref(value: string): string | null {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" ? parsed.toString() : null;
  } catch {
    return null;
  }
}

function SourceLinks({
  sourceIds,
  evidenceById,
  label = "Sources",
}: {
  sourceIds: string[];
  evidenceById: Map<string, EvidenceItem>;
  label?: string;
}) {
  const sources = [...new Set(sourceIds)]
    .map((sourceId) => evidenceById.get(sourceId))
    .filter((item): item is EvidenceItem => Boolean(item));
  if (!sources.length) return null;

  return (
    <div className="narrativeSources" aria-label={label}>
      {sources.map((item) => {
        const sourceHref = safeSourceHref(item.url);
        return sourceHref ? (
          <a
            href={sourceHref}
            key={item.evidence_id}
            rel="noopener noreferrer"
            referrerPolicy="no-referrer"
            target="_blank"
          >
            {item.title} ↗
          </a>
        ) : (
          <span key={item.evidence_id}>{item.title}</span>
        );
      })}
    </div>
  );
}

function CitedTextContent({
  item,
  evidenceById,
  label,
}: {
  item: FootprintCitedText;
  evidenceById: Map<string, EvidenceItem>;
  label: string;
}) {
  return (
    <>
      <span>{item.text}</span>
      <SourceLinks
        sourceIds={item.source_ids}
        evidenceById={evidenceById}
        label={label}
      />
    </>
  );
}

function ProfileAnswerCard({
  label,
  emptyLabel,
  answer,
  evidenceById,
}: {
  label: string;
  emptyLabel: string;
  answer: FootprintDeepProfileAnswer;
  evidenceById: Map<string, EvidenceItem>;
}) {
  return (
    <article className={answer.value ? "" : "profileAnswerUnknown"}>
      <span>{label}</span>
      <strong>{answer.value ?? emptyLabel}</strong>
      <small>
        {answer.value && answer.confidence
          ? `${words(answer.confidence)} confidence · ${words(answer.basis)}`
          : "Not enough public evidence"}
      </small>
      <p>{answer.explanation}</p>
      <SourceLinks
        sourceIds={answer.source_ids}
        evidenceById={evidenceById}
        label={`${label} sources`}
      />
    </article>
  );
}

function ProfileTraitGroup({
  title,
  emptyText,
  items,
  evidenceById,
}: {
  title: string;
  emptyText: string;
  items: FootprintDeepProfileTrait[];
  evidenceById: Map<string, EvidenceItem>;
}) {
  return (
    <article>
      <h4>{title}</h4>
      {items.length ? (
        <ul>
          {items.map((item) => (
            <li key={item.label}>
              <strong>{item.label}</strong>
              <small>
                {words(item.confidence)} confidence · {words(item.basis)}
              </small>
              <p>{item.explanation}</p>
              <SourceLinks
                sourceIds={item.source_ids}
                evidenceById={evidenceById}
                label={`${title}: ${item.label} sources`}
              />
            </li>
          ))}
        </ul>
      ) : (
        <p className="profileEmptyState">{emptyText}</p>
      )}
    </article>
  );
}

function TimelineSection({
  items,
  evidenceById,
}: {
  items: FootprintDeepTimelineEntry[];
  evidenceById: Map<string, EvidenceItem>;
}) {
  return (
    <section className="profileExtension" aria-labelledby="profile-timeline-title">
      <div className="profileExtensionHeading">
        <div>
          <div className="eyebrow">Public chronology</div>
          <h4 id="profile-timeline-title">Career and education timeline</h4>
        </div>
        <span>{items.length} supported item(s)</span>
      </div>
      {items.length ? (
        <ol className="profileTimeline">
          {items.map((item, index) => (
            <li key={`${item.entry_type}-${item.title}-${item.organization ?? index}`}>
              <div className="profileItemTopline">
                <span>{words(item.entry_type)}</span>
                <small>
                  {words(item.currentness)} · {words(item.confidence)} confidence ·{" "}
                  {words(item.basis)}
                </small>
              </div>
              <strong>{item.title}</strong>
              {item.organization || item.timeframe ? (
                <p className="profileItemContext">
                  {[item.organization, item.timeframe].filter(Boolean).join(" · ")}
                </p>
              ) : null}
              <p>{item.explanation}</p>
              <SourceLinks
                sourceIds={item.source_ids}
                evidenceById={evidenceById}
                label={`Timeline: ${item.title} sources`}
              />
            </li>
          ))}
        </ol>
      ) : (
        <p className="profileExtensionEmpty">
          No dated work or education history was supported by the collected evidence.
        </p>
      )}
    </section>
  );
}

function SubjectProfileSnapshot({
  profile,
  showTimeline,
  evidenceById,
}: {
  profile: FootprintDeepSubjectProfile;
  showTimeline: boolean;
  evidenceById: Map<string, EvidenceItem>;
}) {
  return (
    <section className="subjectProfileSnapshot" aria-labelledby="subject-profile-title">
      <div className="briefSectionHeading">
        <div>
          <div className="eyebrow">Person profile</div>
          <h3 id="subject-profile-title">What you probably want to know</h3>
        </div>
        <span>Evidence-qualified answers</span>
      </div>

      <div className="profileAnswerGrid">
        <ProfileAnswerCard
          label="Who this appears to be"
          emptyLabel="Identity unresolved"
          answer={profile.identity}
          evidenceById={evidenceById}
        />
        <ProfileAnswerCard
          label="Probably based in"
          emptyLabel="Location unknown"
          answer={profile.location}
          evidenceById={evidenceById}
        />
        <ProfileAnswerCard
          label="What they do"
          emptyLabel="Occupation unknown"
          answer={profile.occupation}
          evidenceById={evidenceById}
        />
        <ProfileAnswerCard
          label="Education"
          emptyLabel="Education unknown"
          answer={profile.education}
          evidenceById={evidenceById}
        />
      </div>

      {showTimeline ? (
        <TimelineSection
          items={profile.career_timeline ?? []}
          evidenceById={evidenceById}
        />
      ) : null}

      <div className="profilePreferenceGrid">
        <ProfileTraitGroup
          title="Public interests"
          emptyText="No reliable public interests were identified."
          items={profile.interests}
          evidenceById={evidenceById}
        />
        <ProfileTraitGroup
          title="Appears to like"
          emptyText="No reliable public likes were identified."
          items={profile.likes}
          evidenceById={evidenceById}
        />
        <ProfileTraitGroup
          title="Explicitly dislikes"
          emptyText="No explicit public dislikes were found."
          items={profile.dislikes}
          evidenceById={evidenceById}
        />
      </div>

      {profile.unknowns.length ? (
        <div className="profileUnknowns">
          <strong>What remains unknown</strong>
          <ul>
            {profile.unknowns.map((item) => (
              <li key={item.topic}>
                <span>{words(item.topic)}</span>
                <p>{item.explanation}</p>
                <SourceLinks
                  sourceIds={item.source_ids}
                  evidenceById={evidenceById}
                  label={`${item.topic} uncertainty sources`}
                />
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

export function FootprintBrief({
  brief,
  evidence,
}: {
  brief: FootprintBriefType;
  evidence: EvidenceItem[];
}) {
  const narrativeSections = brief.narrative_sections ?? [];
  const evidenceById = new Map(
    evidence.map((item) => [item.evidence_id, item]),
  );
  const story = brief.deep_story ?? null;
  const accountInsightById = new Map(
    (story?.account_insights ?? []).map((item) => [item.account_id, item]),
  );
  const sourceUses = new Map<string, Set<string>>();
  function recordSourceUse(label: string, sourceIds: string[]) {
    sourceIds.forEach((sourceId) => {
      const uses = sourceUses.get(sourceId) ?? new Set<string>();
      uses.add(label);
      sourceUses.set(sourceId, uses);
    });
  }
  if (story) {
    recordSourceUse("Conclusion", story.conclusion_source_ids);
    recordSourceUse("Story overview", story.overview_source_ids);
    if (story.subject_profile) {
      const profile = story.subject_profile;
      recordSourceUse("Profile identity", profile.identity.source_ids);
      recordSourceUse("Profile location", profile.location.source_ids);
      recordSourceUse("Profile occupation", profile.occupation.source_ids);
      recordSourceUse("Profile education", profile.education.source_ids);
      [...profile.interests, ...profile.likes, ...profile.dislikes].forEach((item) =>
        recordSourceUse(`Profile preference: ${item.label}`, item.source_ids),
      );
      profile.unknowns.forEach((item) =>
        recordSourceUse(`Profile unknown: ${item.topic}`, item.source_ids),
      );
      (profile.career_timeline ?? []).forEach((item) =>
        recordSourceUse(`Timeline: ${item.title}`, item.source_ids),
      );
    }
    story.identity_facts.forEach((fact) =>
      recordSourceUse(`Identity: ${fact.label}`, fact.source_ids),
    );
    story.account_insights.forEach((insight) => {
      recordSourceUse("Account synthesis", insight.source_ids);
      insight.public_facts.forEach((fact) =>
        recordSourceUse("Account public fact", fact.source_ids),
      );
      insight.association_reasons.forEach((reason) =>
        recordSourceUse("Account association", reason.source_ids),
      );
    });
    story.curated_claims.forEach((claim) => {
      recordSourceUse(`Finding: ${claim.label}`, [
        ...claim.source_ids,
        ...claim.contradicting_source_ids,
      ]);
      claim.supporting_evidence.forEach((item) =>
        recordSourceUse(`Finding support: ${claim.label}`, item.source_ids),
      );
      claim.limiting_evidence.forEach((item) =>
        recordSourceUse(`Finding boundary: ${claim.label}`, item.source_ids),
      );
    });
    story.excluded_candidates.forEach((candidate) =>
      recordSourceUse(`Excluded: ${candidate.label}`, candidate.source_ids),
    );
    story.channel_coverage.forEach((channel) =>
      recordSourceUse(`Coverage: ${channel.channel}`, channel.source_ids),
    );
    story.next_verification_steps.forEach((step) =>
      recordSourceUse("Reassessment condition", step.source_ids),
    );
  }
  narrativeSections.forEach((section) => {
    recordSourceUse(section.title, section.source_ids);
    section.highlights.forEach((highlight) =>
      recordSourceUse(`${section.title} highlight`, highlight.source_ids),
    );
  });

  return (
    <section className="footprintBrief" aria-labelledby="footprint-brief-title">
      <header className="footprintBriefHeader">
        <div>
          <div className="eyebrow">
            {story ? "Deep footprint story" : `${words(brief.report_type)} brief`} ·
            evidence linked
          </div>
          <h2 id="footprint-brief-title">{brief.subject}</h2>
        </div>
        <span
          className={`identityStatus identityStatus-${brief.overall_identity_status}`}
        >
          Person identity {words(brief.overall_identity_status)}
        </span>
      </header>

      <p className="footprintBriefSummary">{brief.summary}</p>
      {story ? (
        <SourceLinks
          sourceIds={story.conclusion_source_ids}
          evidenceById={evidenceById}
          label="Conclusion sources"
        />
      ) : null}

      {brief.synthesis ? (
        <div
          className={`synthesisNotice synthesisNotice-${brief.synthesis.status}`}
          aria-label="Report synthesis method"
        >
          <strong>
            {brief.synthesis.mode === "llm_grounded"
              ? "Source-grounded Deep story"
              : brief.synthesis.status === "fallback"
                ? "Deep story unavailable · Quick-grade fallback"
                : "Quick evidence report"}
          </strong>
          <span>
            {brief.synthesis.mode === "llm_grounded"
              ? `Written from the cited evidence${
                  brief.synthesis.model ? ` with ${brief.synthesis.model}` : ""
                }${
                  brief.synthesis.provider
                    ? ` via ${brief.synthesis.provider === "openrouter" ? "OpenRouter" : "OpenAI"}`
                    : ""
                }; identity decisions remain rule-based.`
              : brief.synthesis.status === "fallback"
                ? "Adaptive retrieval completed, but the LLM story engine was unavailable or rejected validation. This is a partial, deterministic evidence report."
                : "Adaptive retrieval was assembled into a concise report with deterministic, evidence-linked rules."}
          </span>
        </div>
      ) : null}

      {story?.subject_profile ? (
        <SubjectProfileSnapshot
          profile={story.subject_profile}
          showTimeline={story.version === "deep-story-v4"}
          evidenceById={evidenceById}
        />
      ) : null}

      {story ? (
        <section className="deepStoryLead" aria-labelledby="deep-story-overview">
          <div>
            <div className="eyebrow">Public story</div>
            <h3 id="deep-story-overview">The evidence-backed portrait</h3>
            <p>{story.overview}</p>
            <SourceLinks
              sourceIds={story.overview_source_ids}
              evidenceById={evidenceById}
              label="Story overview sources"
            />
          </div>
          <aside>
            <span>{words(story.overall_confidence)} confidence</span>
            {!story.subject_profile && story.likely_public_identity ? (
              <dl>
                <dt>Likely public identity</dt>
                <dd>{story.likely_public_identity}</dd>
              </dl>
            ) : null}
            {!story.subject_profile && story.broad_location ? (
              <dl>
                <dt>Broad location</dt>
                <dd>{story.broad_location}</dd>
              </dl>
            ) : null}
            <dl>
              <dt>Main boundary</dt>
              <dd>{story.major_boundary}</dd>
            </dl>
          </aside>
        </section>
      ) : null}

      {story?.identity_facts.length ? (
        <section className="deepIdentitySnapshot" aria-labelledby="identity-snapshot-title">
          <div className="briefSectionHeading">
            <div>
              <div className="eyebrow">
                {story.subject_profile ? "Supporting identity facts" : "Identity snapshot"}
              </div>
              <h3 id="identity-snapshot-title">
                {story.subject_profile
                  ? "Why the profile answers are qualified"
                  : "What the evidence says at a glance"}
              </h3>
            </div>
            <span>{story.identity_facts.length} selected fact(s)</span>
          </div>
          <div className="deepIdentityGrid">
            {story.identity_facts.map((fact) => (
              <article key={fact.label}>
                <span>{fact.label}</span>
                <strong>{fact.value}</strong>
                <small>
                  {words(fact.status)} · {words(fact.confidence)} confidence
                </small>
                {fact.qualification ? <p>{fact.qualification}</p> : null}
                <SourceLinks
                  sourceIds={fact.source_ids}
                  evidenceById={evidenceById}
                  label={`${fact.label} sources`}
                />
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {narrativeSections.length ? (
        <div className="footprintNarrative" aria-label="Deep research narrative">
          {narrativeSections.map((section) => (
              <article key={section.key}>
                <div className="eyebrow">Story chapter</div>
                <h3>{section.title}</h3>
                <p>{section.body}</p>
                {section.highlights?.length ? (
                  <ul className="storyHighlights citedTextList">
                    {section.highlights.map((highlight, index) => (
                      <li key={`${section.key}-highlight-${index}`}>
                        <CitedTextContent
                          item={highlight}
                          evidenceById={evidenceById}
                          label={`${section.title} highlight ${index + 1} sources`}
                        />
                      </li>
                    ))}
                  </ul>
                ) : null}
                <SourceLinks
                  sourceIds={section.source_ids}
                  evidenceById={evidenceById}
                  label={`${section.title} sources`}
                />
              </article>
            ))}
        </div>
      ) : null}

      <div className="identityReasonGrid">
        <div>
          <h3>What supports this association</h3>
          {brief.identity_reasons.supporting.length ? (
            <ul>
              {brief.identity_reasons.supporting.map((reason, index) => (
                <li key={`${reason}-${index}`}>{reason}</li>
              ))}
            </ul>
          ) : (
            <p>No supporting identity signal was strong enough to promote.</p>
          )}
        </div>
        <div>
          <h3>What limits it</h3>
          {brief.identity_reasons.limiting.length ? (
            <ul>
              {brief.identity_reasons.limiting.map((reason, index) => (
                <li key={`${reason}-${index}`}>{reason}</li>
              ))}
            </ul>
          ) : (
            <p>No material contradiction was recorded.</p>
          )}
        </div>
      </div>

      <div className="briefSectionHeading">
        <div>
          <div className="eyebrow">Account cluster</div>
          <h3>Profiles assessed in this brief</h3>
        </div>
        <span>{brief.accounts.length} account(s)</span>
      </div>
      <div className="briefAccountList">
        {brief.accounts.map((account) => {
          const profileHref = safeSourceHref(account.profile_url);
          const insight = accountInsightById.get(account.candidate_id);
          return (
            <article key={account.candidate_id}>
              <div className="briefAccountTopline">
                <strong>
                  {account.platform} · @{account.handle}
                </strong>
                <span>{words(account.identity_status)}</span>
              </div>
              {account.display_name ? <h4>{account.display_name}</h4> : null}
              <div className="briefAccountMeta">
                <span>{words(account.existence_status)}</span>
                <span>{words(account.confidence)} confidence</span>
                <span>{account.source_ids.length} source(s)</span>
              </div>
              {account.reasons.length ? (
                <ul>
                  {account.reasons.map((reason, index) => (
                    <li key={`${reason}-${index}`}>{reason}</li>
                  ))}
                </ul>
              ) : null}
              {insight ? (
                <div className="deepAccountInsight">
                  <span>Story synthesis</span>
                  <p>{insight.rationale}</p>
                  <SourceLinks
                    sourceIds={insight.source_ids}
                    evidenceById={evidenceById}
                    label={`${account.platform} @${account.handle} synthesis sources`}
                  />
                  {insight.public_facts.length ? (
                    <ul className="citedTextList">
                      {insight.public_facts.map((fact, index) => (
                        <li key={`${account.candidate_id}-fact-${index}`}>
                          <CitedTextContent
                            item={fact}
                            evidenceById={evidenceById}
                            label={`${account.platform} @${account.handle} public fact ${index + 1} sources`}
                          />
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  {insight.association_reasons.length ? (
                    <>
                      <strong className="deepInsightLabel">Association signals</strong>
                      <ul className="citedTextList">
                        {insight.association_reasons.map((reason, index) => (
                          <li key={`${account.candidate_id}-association-${index}`}>
                            <CitedTextContent
                              item={reason}
                              evidenceById={evidenceById}
                              label={`${account.platform} @${account.handle} association signal ${index + 1} sources`}
                            />
                          </li>
                        ))}
                      </ul>
                    </>
                  ) : null}
                </div>
              ) : null}
              {profileHref ? (
                <a
                  href={profileHref}
                  rel="noopener noreferrer"
                  referrerPolicy="no-referrer"
                  target="_blank"
                >
                  Open public profile ↗
                </a>
              ) : null}
            </article>
          );
        })}
      </div>

      {story?.curated_claims.length ? (
        <>
          <div className="briefSectionHeading">
            <div>
              <div className="eyebrow">Key findings</div>
              <h3>The claims that shape the story</h3>
            </div>
            <span>{story.curated_claims.length} selected claim(s)</span>
          </div>
          <div className="deepCuratedClaims">
            {story.curated_claims.map((claim) => (
              <article key={claim.claim_id}>
                <div>
                  <span>{claim.label}</span>
                  <small>{words(claim.status)}</small>
                </div>
                <strong>{claim.value}</strong>
                {claim.qualification ? <p>{claim.qualification}</p> : null}
                {claim.supporting_evidence.length ? (
                  <ul className="citedTextList">
                    {claim.supporting_evidence.map((item, index) => (
                      <li key={`${claim.claim_id}-support-${index}`}>
                        <CitedTextContent
                          item={item}
                          evidenceById={evidenceById}
                          label={`${claim.label} supporting evidence ${index + 1} sources`}
                        />
                      </li>
                    ))}
                  </ul>
                ) : null}
                {claim.limiting_evidence.length ? (
                  <div className="claimBoundary">
                    <span>Boundary</span>
                    <ul className="citedTextList">
                      {claim.limiting_evidence.map((item, index) => (
                        <li key={`${claim.claim_id}-limit-${index}`}>
                          <CitedTextContent
                            item={item}
                            evidenceById={evidenceById}
                            label={`${claim.label} limiting evidence ${index + 1} sources`}
                          />
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                <SourceLinks
                  sourceIds={[...claim.source_ids, ...claim.contradicting_source_ids]}
                  evidenceById={evidenceById}
                  label={`${claim.label} sources`}
                />
              </article>
            ))}
          </div>
        </>
      ) : null}

      <div className="briefSectionHeading">
        <div>
          <div className="eyebrow">
            {story ? "Host-validated evidence record" : "Qualified findings"}
          </div>
          <h3>
            {story ? "Structured facts behind the story" : "What the public evidence supports"}
          </h3>
        </div>
        <span>{brief.claims.length} claim(s)</span>
      </div>
      {brief.claims.length ? (
        <div className="footprintClaims">
          {brief.claims.map((claim) => (
            <article key={claim.claim_id}>
              <span>{claim.label}</span>
              <strong>{claim.value}</strong>
              {claim.qualification ? <p>{claim.qualification}</p> : null}
              <small>
                {words(claim.confidence)} confidence · {claim.source_ids.length} source(s)
              </small>
            </article>
          ))}
        </div>
      ) : (
        <p className="briefEmptyFinding">
          No descriptive claim met the report&apos;s evidence threshold.
        </p>
      )}

      {story?.excluded_candidates.length ? (
        <>
          <div className="briefSectionHeading">
            <div>
              <div className="eyebrow">Isolated candidates</div>
              <h3>What was kept outside the main cluster</h3>
            </div>
            <span>{story.excluded_candidates.length} candidate(s)</span>
          </div>
          <div className="deepExcludedList">
            {story.excluded_candidates.map((candidate, index) => (
              <article key={`${candidate.label}-${index}`}>
                <div>
                  <strong>{candidate.label}</strong>
                  <span>{words(candidate.disposition)}</span>
                </div>
                <p>{candidate.reason}</p>
                <SourceLinks
                  sourceIds={candidate.source_ids}
                  evidenceById={evidenceById}
                  label={`${candidate.label} exclusion sources`}
                />
              </article>
            ))}
          </div>
        </>
      ) : null}

      {story?.channel_coverage.length ? (
        <section className="deepCoverage" aria-labelledby="channel-coverage-title">
          <div className="briefSectionHeading">
            <div>
              <div className="eyebrow">Channel coverage</div>
              <h3 id="channel-coverage-title">Where this snapshot found evidence</h3>
            </div>
            <span>{story.channel_coverage.length} channel(s)</span>
          </div>
          <div className="deepCoverageTable">
            {story.channel_coverage.map((channel) => (
              <article key={channel.channel}>
                <strong>{channel.channel}</strong>
                <span>{words(channel.status)}</span>
                <div>
                  <p>{channel.detail}</p>
                  <SourceLinks
                    sourceIds={channel.source_ids}
                    evidenceById={evidenceById}
                    label={`${channel.channel} coverage sources`}
                  />
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {story?.next_verification_steps.length ? (
        <section className="deepNextSteps" aria-labelledby="next-verification-title">
          <div className="eyebrow">Reassessment conditions</div>
          <h3 id="next-verification-title">What could strengthen or change this story</h3>
          <ol>
            {story.next_verification_steps.map((step, index) => (
              <li key={`verification-step-${index}`}>
                <CitedTextContent
                  item={step}
                  evidenceById={evidenceById}
                  label={`Reassessment condition ${index + 1} sources`}
                />
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      <div className="footprintBriefFooter">
        <div>
          <h3>Limitations</h3>
          {brief.limitations.length ? (
            <ul>
              {brief.limitations.map((limitation, index) => (
                <li key={`${limitation}-${index}`}>{limitation}</li>
              ))}
            </ul>
          ) : (
            <p>No additional limitation was recorded.</p>
          )}
        </div>
        <details>
          <summary>Evidence index ({evidence.length})</summary>
          {evidence.length ? (
            <ul className="footprintSourceList">
              {evidence.map((item) => {
                const sourceHref = safeSourceHref(item.url);
                const uses = [...(sourceUses.get(item.evidence_id) ?? [])];
                return (
                  <li key={item.evidence_id}>
                    <span>
                      <strong>{item.title}</strong>
                      <small className="sourceProvenance">
                        {item.publisher} · {words(item.trust_class)} ·{" "}
                        {words(item.source_type)}
                      </small>
                      {item.excerpt ? <small>{item.excerpt}</small> : null}
                      {uses.length ? (
                        <small className="sourceUses">
                          Supports: {uses.slice(0, 4).join(" · ")}
                        </small>
                      ) : null}
                    </span>
                    {sourceHref ? (
                      <a
                        href={sourceHref}
                        rel="noopener noreferrer"
                        referrerPolicy="no-referrer"
                        target="_blank"
                      >
                        View source ↗
                      </a>
                    ) : (
                      <small>Source link unavailable</small>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : (
            <p>The report has no displayable source excerpt.</p>
          )}
        </details>
      </div>
    </section>
  );
}
