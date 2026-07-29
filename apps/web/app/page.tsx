import { SearchForm } from "@/components/SearchForm";
import Link from "next/link";

export default function HomePage() {
  return (
    <main className="shell">
      <nav className="topbar" aria-label="Primary navigation">
        <Link className="brand" href="/">
          tracebrief<span className="brandMark">/</span>
        </Link>
        <span className="prototypePill">Local limited-evaluation prototype</span>
      </nav>

      <section className="hero">
        <div className="eyebrow">Evidence before assertion</div>
        <h1>
          See what a public profile
          <br />
          <span>actually supports.</span>
        </h1>
        <p className="heroCopy">
          Verify a public GitHub profile you control, complete local eligibility
          approval, and build a deterministic brief with inspectable sources. A
          synthetic demo remains available without real profile data.
        </p>
        <SearchForm />
      </section>

      <section className="principles" aria-label="Prototype principles">
        <article>
          <span>01</span>
          <h2>Direct URL only</h2>
          <p>GitHub is the only live allowlisted provider. No username discovery.</p>
        </article>
        <article>
          <span>02</span>
          <h2>Eligibility gated</h2>
          <p>Profile control and explicit operator approval are both required.</p>
        </article>
        <article>
          <span>03</span>
          <h2>Traceable</h2>
          <p>Every displayed claim resolves to accepted evidence and lineage.</p>
        </article>
      </section>
    </main>
  );
}
