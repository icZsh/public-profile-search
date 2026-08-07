import { FootprintSearchForm } from "@/components/FootprintSearchForm";
import Link from "next/link";

export default function HomePage() {
  return (
    <main className="shell">
      <nav className="topbar" aria-label="Primary navigation">
        <Link className="brand" href="/">
          tracebrief<span className="brandMark">/</span>
        </Link>
        <span className="prototypePill">Local discovery prototype</span>
      </nav>

      <section className="hero">
        <div className="eyebrow">One identifier, many possible accounts</div>
        <h1>
          Map a person&apos;s public
          <br />
          <span>digital footprint.</span>
        </h1>
        <p className="heroCopy">
          Paste a handle or public profile URL. Tracebrief infers platform context
          when it can, searches for public account candidates, and keeps uncertain
          matches visibly unresolved.
        </p>
        <FootprintSearchForm />
      </section>

      <section className="principles" aria-label="Discovery principles">
        <article>
          <span>01</span>
          <h2>Start anywhere</h2>
          <p>
            Profile URLs carry their platform context; bare handles search across
            the catalog.
          </p>
        </article>
        <article>
          <span>02</span>
          <h2>Watch it unfold</h2>
          <p>Candidate profiles and coverage appear progressively as sites respond.</p>
        </article>
        <article>
          <span>03</span>
          <h2>Evidence, not certainty</h2>
          <p>Every lead keeps its discovery evidence without implying shared identity.</p>
        </article>
      </section>
    </main>
  );
}
