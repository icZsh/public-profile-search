import type { EvidenceItem } from "@public-profile-search/generated-api-client";

function safeSourceHref(value: string): string | null {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" ? parsed.toString() : null;
  } catch {
    return null;
  }
}

export function EvidenceDrawer({ items }: { items: EvidenceItem[] }) {
  return (
    <section className="evidenceCard">
      <div className="sectionHeading">
        <div>
          <div className="eyebrow">Accepted observations</div>
          <h2>Evidence trail</h2>
        </div>
        <span>{items.length} sources</span>
      </div>
      <div className="evidenceList">
        {items.map((item, index) => {
          const sourceHref = safeSourceHref(item.url);
          return (
            <article key={item.evidence_id}>
              <span className="sourceIndex">0{index + 1}</span>
              <div>
                <h3>{item.title}</h3>
                <p>{item.excerpt}</p>
                <div className="sourceMeta">
                  <span>{item.source_type.replaceAll("_", " ")}</span>
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
                    <span>Source link unavailable</span>
                  )}
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
