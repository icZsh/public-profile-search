"use client";

import type {
  EligibilityVerification,
  EligibilityVerificationStatus,
} from "@public-profile-search/generated-api-client";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import {
  completeEligibilityVerification,
  createEligibilityVerification,
  createSearchJob,
  createSyntheticSearchJob,
  getEligibilityVerification,
} from "@/lib/api";

const ACTIVE_VERIFICATION_KEY = "tracebrief.activeEligibilityVerification";

type BusyAction =
  | "creating"
  | "verifying"
  | "refreshing"
  | "building"
  | "demo"
  | null;

type VerificationPhase =
  | "pending"
  | "review"
  | "eligible"
  | "expired"
  | "unavailable";

interface StoredVerification {
  verificationId: string;
  profileUrl: string;
  challengeValue?: string;
}

function verificationPhase(
  status: EligibilityVerificationStatus,
): VerificationPhase {
  if (status === "verification_pending" || status === "pending_control") {
    return "pending";
  }
  if (
    status === "control_verified_review_pending" ||
    status === "review_pending"
  ) {
    return "review";
  }
  if (status === "eligible_verified_self" || status === "eligible") {
    return "eligible";
  }
  if (status === "expired") {
    return "expired";
  }
  return "unavailable";
}

function formatDate(value?: string | null): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return null;
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

function safeGitHubHref(value: string): string | null {
  try {
    const parsed = new URL(value);
    const pathParts = parsed.pathname.split("/").filter(Boolean);
    if (
      parsed.protocol !== "https:" ||
      parsed.hostname.toLowerCase() !== "github.com" ||
      parsed.port ||
      parsed.username ||
      parsed.password ||
      parsed.search ||
      parsed.hash ||
      pathParts.length !== 1
    ) {
      return null;
    }
    return parsed.toString();
  } catch {
    return null;
  }
}

function readStoredVerification(): StoredVerification | null {
  try {
    const raw = window.sessionStorage.getItem(ACTIVE_VERIFICATION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredVerification>;
    if (
      typeof parsed.verificationId !== "string" ||
      typeof parsed.profileUrl !== "string"
    ) {
      return null;
    }
    return {
      verificationId: parsed.verificationId,
      profileUrl: parsed.profileUrl,
      challengeValue:
        typeof parsed.challengeValue === "string"
          ? parsed.challengeValue
          : undefined,
    };
  } catch {
    return null;
  }
}

function storeVerification(
  verification: EligibilityVerification,
  challengeValue?: string,
) {
  try {
    const stored: StoredVerification = {
      verificationId: verification.verification_id,
      profileUrl: verification.canonical_profile_url,
      ...(challengeValue ? { challengeValue } : {}),
    };
    window.sessionStorage.setItem(
      ACTIVE_VERIFICATION_KEY,
      JSON.stringify(stored),
    );
  } catch {
    // The flow still works when private browsing blocks session storage.
  }
}

function clearStoredVerification() {
  try {
    window.sessionStorage.removeItem(ACTIVE_VERIFICATION_KEY);
  } catch {
    // There may be nothing to clear when storage is unavailable.
  }
}

function errorMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

export function SearchForm() {
  const router = useRouter();
  const [profileUrl, setProfileUrl] = useState("");
  const [verification, setVerification] =
    useState<EligibilityVerification | null>(null);
  const [challengeValue, setChallengeValue] = useState("");
  const [busy, setBusy] = useState<BusyAction>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const stored = readStoredVerification();
    if (!stored) return;

    let active = true;
    getEligibilityVerification(stored.verificationId)
      .then((current) => {
        if (!active) return;
        setVerification(current);
        setProfileUrl(current.canonical_profile_url || stored.profileUrl);
        setChallengeValue(stored.challengeValue ?? "");
      })
      .catch(() => {
        clearStoredVerification();
      });

    return () => {
      active = false;
    };
  }, []);

  async function startVerification(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;

    setBusy("creating");
    setError("");
    setCopied(false);
    try {
      const current = await createEligibilityVerification(profileUrl.trim());
      const nextChallenge = current.challenge_value ?? "";
      setVerification(current);
      setProfileUrl(current.canonical_profile_url);
      setChallengeValue(nextChallenge);
      storeVerification(current, nextChallenge);
    } catch (reason) {
      setError(
        errorMessage(reason, "The profile verification could not be started."),
      );
    } finally {
      setBusy(null);
    }
  }

  async function verifyControl() {
    if (!verification || busy) return;

    setBusy("verifying");
    setError("");
    try {
      const current = await completeEligibilityVerification(
        verification.verification_id,
      );
      const phase = verificationPhase(current.status);
      const retainedChallenge =
        phase === "pending" ? challengeValue : undefined;
      setVerification(current);
      if (phase !== "pending") setChallengeValue("");
      storeVerification(current, retainedChallenge);
    } catch (reason) {
      setError(
        errorMessage(reason, "GitHub control could not be verified right now."),
      );
    } finally {
      setBusy(null);
    }
  }

  async function refreshApproval() {
    if (!verification || busy) return;

    setBusy("refreshing");
    setError("");
    try {
      const current = await getEligibilityVerification(
        verification.verification_id,
      );
      setVerification(current);
      storeVerification(
        current,
        verificationPhase(current.status) === "pending"
          ? challengeValue
          : undefined,
      );
    } catch (reason) {
      setError(
        errorMessage(reason, "The eligibility status could not be refreshed."),
      );
    } finally {
      setBusy(null);
    }
  }

  async function buildBrief() {
    if (
      !verification ||
      verificationPhase(verification.status) !== "eligible" ||
      busy
    ) {
      return;
    }
    if (!verification.eligibility_reference_id) {
      setError(
        "Approval is missing its eligibility reference. Refresh approval and try again.",
      );
      return;
    }

    setBusy("building");
    setError("");
    try {
      const job = await createSearchJob({
        profile_url: verification.canonical_profile_url,
        purpose: verification.purpose,
        target_relationship: "self",
        eligibility_reference_id: verification.eligibility_reference_id,
        attestation_policy_version: verification.policy_version,
        locale: "en",
      });
      clearStoredVerification();
      router.push(`/search/${job.job_id}`);
    } catch (reason) {
      setError(errorMessage(reason, "The brief could not be started."));
      setBusy(null);
    }
  }

  async function runSyntheticDemo() {
    if (busy) return;

    setBusy("demo");
    setError("");
    try {
      const job = await createSyntheticSearchJob();
      router.push(`/search/${job.job_id}`);
    } catch (reason) {
      setError(errorMessage(reason, "The synthetic demo could not be started."));
      setBusy(null);
    }
  }

  function startOver() {
    clearStoredVerification();
    setVerification(null);
    setChallengeValue("");
    setProfileUrl("");
    setError("");
    setCopied(false);
  }

  async function copyChallenge() {
    if (!challengeValue) return;
    try {
      await navigator.clipboard.writeText(challengeValue);
      setCopied(true);
    } catch {
      setError("Copy was blocked. Select the challenge text and copy it manually.");
    }
  }

  const phase = verification
    ? verificationPhase(verification.status)
    : null;
  const githubHref = verification
    ? safeGitHubHref(verification.canonical_profile_url)
    : null;
  const challengeExpiry = formatDate(verification?.challenge_expires_at);
  const reviewExpiry = formatDate(verification?.review_expires_at);
  const eligibilityExpiry = formatDate(
    verification?.eligibility_expires_at,
  );

  return (
    <form className="searchCard" onSubmit={startVerification}>
      <div className="formHeading">
        <div>
          <label htmlFor="profile-url">Your public GitHub profile URL</label>
          <p id="profile-help">
            Enter a full profile URL you control. Username-only search is not available.
          </p>
        </div>
        <span className="providerBadge">GitHub allowlist</span>
      </div>

      <div className="inputRow">
        <input
          id="profile-url"
          type="url"
          value={profileUrl}
          onChange={(event) => setProfileUrl(event.target.value)}
          placeholder="https://github.com/your-username"
          autoComplete="url"
          spellCheck={false}
          maxLength={256}
          required
          disabled={Boolean(verification) || Boolean(busy)}
          aria-describedby="profile-help"
        />
        {!verification ? (
          <button type="submit" disabled={Boolean(busy)}>
            {busy === "creating" ? "Creating…" : "Verify profile"}
          </button>
        ) : (
          <button className="secondaryButton" type="button" onClick={startOver}>
            Use another URL
          </button>
        )}
      </div>

      {!verification ? (
        <div className="formMeta">
          <span>
            <i className="statusDot" /> Direct URL only
          </span>
          <span>Proof of control required</span>
          <span>Operator eligibility approval required</span>
        </div>
      ) : null}

      {verification && phase === "pending" ? (
        <section className="verificationPanel" aria-live="polite">
          <div className="stepHeading">
            <span className="stepNumber">1</span>
            <div>
              <p className="stepLabel">Prove profile control</p>
              <h2>Add this temporary challenge to your GitHub bio.</h2>
            </div>
          </div>
          {challengeValue ? (
            <div className="challengeRow">
              <code>{challengeValue}</code>
              <button
                className="copyButton"
                type="button"
                onClick={copyChallenge}
              >
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
          ) : (
            <p className="panelNotice">
              The challenge is no longer available in this tab. Start over if you
              have not already added it to your bio.
            </p>
          )}
          <ol className="verificationSteps">
            <li>Open your public GitHub profile and edit the bio.</li>
            <li>Paste the challenge exactly, then save the profile.</li>
            <li>Return here and verify control. You can remove it afterward.</li>
          </ol>
          {verification.message ? (
            <p className="panelNotice">{verification.message}</p>
          ) : null}
          <div className="panelMeta">
            {githubHref ? (
              <a
                href={githubHref}
                target="_blank"
                rel="noopener noreferrer"
                referrerPolicy="no-referrer"
              >
                Open GitHub profile ↗
              </a>
            ) : null}
            {challengeExpiry ? <span>Expires {challengeExpiry}</span> : null}
            <span>
              {verification.attempts_remaining} verification attempts remaining
            </span>
          </div>
          <button
            className="panelPrimaryButton"
            type="button"
            onClick={verifyControl}
            disabled={Boolean(busy)}
          >
            {busy === "verifying"
              ? "Checking GitHub…"
              : "I updated my bio — verify control"}
          </button>
        </section>
      ) : null}

      {verification && phase === "review" ? (
        <section className="verificationPanel successPanel" aria-live="polite">
          <div className="stepHeading">
            <span className="stepNumber">✓</span>
            <div>
              <p className="stepLabel">Control confirmed</p>
              <h2>Operator eligibility review is still required.</h2>
            </div>
          </div>
          <p>
            Control proof does not establish adult eligibility or approved public
            context. You can remove the challenge from your GitHub bio now.
          </p>
          <div className="operatorBlock">
            <span>Local operator command</span>
            <code>
              uv run python scripts/approve_eligibility.py{" "}
              {verification.verification_id}
            </code>
          </div>
          <div className="panelMeta">
            <span>Verification {verification.verification_id}</span>
            {reviewExpiry ? <span>Review by {reviewExpiry}</span> : null}
          </div>
          <button
            className="panelPrimaryButton"
            type="button"
            onClick={refreshApproval}
            disabled={Boolean(busy)}
          >
            {busy === "refreshing" ? "Refreshing…" : "Refresh approval"}
          </button>
        </section>
      ) : null}

      {verification && phase === "eligible" ? (
        <section className="verificationPanel successPanel" aria-live="polite">
          <div className="stepHeading">
            <span className="stepNumber">✓</span>
            <div>
              <p className="stepLabel">Eligible self-audit</p>
              <h2>Your approved profile is ready for a brief.</h2>
            </div>
          </div>
          <p>
            Tracebrief will collect only allowlisted public profile fields and
            freeze the accepted evidence behind the result.
          </p>
          {eligibilityExpiry ? (
            <p className="panelNotice">Approval expires {eligibilityExpiry}.</p>
          ) : null}
          <button
            className="panelPrimaryButton"
            type="button"
            onClick={buildBrief}
            disabled={Boolean(busy)}
          >
            {busy === "building" ? "Starting…" : "Build brief"}
          </button>
        </section>
      ) : null}

      {verification && (phase === "expired" || phase === "unavailable") ? (
        <section className="verificationPanel unavailablePanel" aria-live="polite">
          <div className="stepHeading">
            <span className="stepNumber">!</span>
            <div>
              <p className="stepLabel">Verification unavailable</p>
              <h2>This profile cannot continue through the current flow.</h2>
            </div>
          </div>
          <p>
            {verification.message ||
              "Start a new verification if this challenge expired."}
          </p>
          <button
            className="panelPrimaryButton"
            type="button"
            onClick={startOver}
          >
            Start over
          </button>
        </section>
      ) : null}

      {error ? (
        <p className="formError" role="alert">
          {error}
        </p>
      ) : null}

      <div className="demoDivider">
        <span>or</span>
      </div>
      <div className="demoRow">
        <div>
          <strong>Run without real profile data</strong>
          <p>Use the bundled synthetic fixture with no external network request.</p>
        </div>
        <button
          className="demoButton"
          type="button"
          onClick={runSyntheticDemo}
          disabled={Boolean(busy)}
        >
          {busy === "demo" ? "Starting demo…" : "Run synthetic demo"}
        </button>
      </div>
    </form>
  );
}
