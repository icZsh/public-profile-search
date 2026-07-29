# ADR 0001: Fake-provider-only prototype

Status: accepted for the initial local prototype; live-provider portion superseded by
[ADR 0002](./0002-github-limited-evaluation.md)

The first vertical slice uses two bundled synthetic provider responses, a fixed synthetic
eligibility reference, deterministic correlation, and deterministic reporting. No code
path performs a network fetch or calls an LLM.

This keeps architecture work testable without silently beginning real-person processing
before the Phase 0 and Phase 1 gates.

The synthetic path remains unchanged and is still the default test and benchmark
boundary. ADR 0002 authorizes one narrower live path for project-owner local evaluation;
it does not convert this initial decision into MVP or production approval.
