# Release matrix

| Capability | Local prototype | Invite alpha | P1 / production candidate |
|---|---|---|---|
| Synthetic fixture URL | enabled | test-only | test-only |
| GitHub direct profile URL | project-owner limited evaluation only | disabled pending `approved_for_mvp` review | separate provider approval required |
| Username-only search | absent | absent | separate product/safety decision required |
| Profile-control challenge | local GitHub bio challenge | production mechanism decision required | OAuth or approved challenge review required |
| Adult/public-professional scope decision | separate local operator CLI | production adjudication design required | audited policy/workflow required |
| Eligibility lifetime | 24-hour default | policy decision required | versioned policy required |
| Safe Fetch | fixed GitHub endpoint, application-level controls | infrastructure egress enforcement required | defense-in-depth gateway/egress required |
| Deterministic Fast Brief | enabled | required | required fallback |
| External LLM | absent | separate approval | optional after data-policy approval |
| Deep Report / PDF | absent | absent | separate decision required |
| Sharing / public API | absent | disabled | separate decision required |
| Public deployment | prohibited | blocked | release gates required |

The live GitHub adapter is explicitly **not `approved_for_mvp`**. Its
`approved_for_limited_evaluation` label is a project-owner local authorization, not broad
provider/legal approval. It cannot be used to justify invite-alpha traffic, bulk live
benchmarks, third-party target processing, or production deployment.

Before any promotion, the project plan's provider, privacy, legal, abuse, auth,
infrastructure egress, retention, quota/cost, observability, incident, and independent
quality gates still apply.
