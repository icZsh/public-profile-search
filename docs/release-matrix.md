# Release matrix

| Capability | Local prototype | Invite alpha | P1 / production candidate |
|---|---|---|---|
| Synthetic fixture URL | enabled | test-only | test-only |
| GitHub direct profile URL | project-owner limited evaluation only | disabled pending `approved_for_mvp` review | separate provider approval required |
| Public handle / supported profile URL footprint search | enabled for bounded local evaluation | disabled pending provider, product, and safety review | separate product/safety decision and provider approval required |
| Profile-control challenge | local GitHub bio challenge | production mechanism decision required | OAuth or approved challenge review required |
| Adult/public-professional scope decision | separate local operator CLI | production adjudication design required | audited policy/workflow required |
| Eligibility lifetime | 24-hour default | policy decision required | versioned policy required |
| Safe Fetch | fixed GitHub endpoint, application-level controls | infrastructure egress enforcement required | defense-in-depth gateway/egress required |
| Deterministic Fast Brief | enabled | required | required fallback |
| External LLM | optional Deep narrative with host-side source validation | separate approval | optional after data-policy approval |
| Deep evidence-linked brief / PDF | brief enabled; PDF absent | disabled | separate decision required |
| Owner-scoped search history | 30-day server-backed history under fixed prototype user ID | production authentication and retention review required | audited isolation, deletion, and retention required |
| Revalidated refresh | old results may prioritize fresh checks; no evidence or identity conclusions copied | disabled | policy and quality approval required |
| Sharing / public API | absent | disabled | separate decision required |
| Public deployment | prohibited | blocked | release gates required |

The live GitHub adapter is explicitly **not `approved_for_mvp`**. Its
`approved_for_limited_evaluation` label is a project-owner local authorization, not broad
provider/legal approval. It cannot be used to justify invite-alpha traffic, bulk live
benchmarks, third-party target processing, or production deployment.

Before any promotion, the project plan's provider, privacy, legal, abuse, auth,
infrastructure egress, retention, quota/cost, observability, incident, and independent
quality gates still apply.
