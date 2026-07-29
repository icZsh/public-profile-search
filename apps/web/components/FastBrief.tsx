import type { FastBrief as FastBriefType } from "@public-profile-search/generated-api-client";

export function FastBrief({ brief }: { brief: FastBriefType }) {
  return (
    <section className="briefCard">
      <div className="briefHeader">
        <div>
          <div className="eyebrow">Fast Brief / deterministic</div>
          <h1>{brief.subject}</h1>
        </div>
        <span className="confidenceBadge">Evidence linked</span>
      </div>
      <p className="summary">{brief.summary}</p>
      <div className="claims">
        {brief.claims.map((claim) => (
          <article key={claim.claim_id}>
            <div>
              <span>{claim.label}</span>
              <strong>{claim.value}</strong>
            </div>
            <small>{claim.confidence.replace("_", " ")} confidence</small>
          </article>
        ))}
      </div>
      <div className="limitations">
        <h2>Limits of this brief</h2>
        <ul>
          {brief.limitations.map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
        </ul>
      </div>
    </section>
  );
}

