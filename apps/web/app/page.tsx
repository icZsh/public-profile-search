import { FootprintSearchForm } from "@/components/FootprintSearchForm";
import { FootprintHistoryDrawer } from "@/components/FootprintHistoryDrawer";
import Link from "next/link";

export default function HomePage() {
  return (
    <main className="traceApp traceHome">
      <nav className="traceTopbar" aria-label="Primary navigation">
        <FootprintHistoryDrawer />
        <Link className="traceBrand" href="/">
          tracebrief<span className="brandMark">/</span>
        </Link>
      </nav>

      <section className="traceSearchIntro">
        <div className="traceKicker">One identifier, one brief</div>
        <h1>
          What does the public
          <br />
          record say about
          <br />
          this handle?
        </h1>
        <p className="traceSearchLead">
          Enter a handle or public profile URL. Every answer arrives with the source
          it came from and the reason it stops where it does.
        </p>
        <FootprintSearchForm />

        <section
          className="tracePrinciples"
          id="methodology"
          aria-label="Discovery principles"
        >
          <article>
            <h2>Candidates, not claims</h2>
            <p>
              Tracebrief infers platform context from public profile URLs. A shared
              handle is a lead, never proof of one person.
            </p>
          </article>
          <article>
            <h2>Every answer cited</h2>
            <p>
              Candidate profiles and coverage appear progressively. Each final answer
              keeps the source that produced it.
            </p>
          </article>
          <article>
            <h2>Limits stated</h2>
            <p>
              The brief says what would change its conclusion and what it must not be
              used for.
            </p>
          </article>
        </section>
      </section>
    </main>
  );
}
