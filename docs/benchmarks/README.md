# Benchmarks

`scripts/benchmark.py` remains fixture-only and writes no source payloads. Its output
validates that the no-network benchmark boundary is intact; it does not measure GitHub
latency, quota, useful-brief yield, or real-world provider quality.

The GitHub adapter's `approved_for_limited_evaluation` status authorizes only an
interactive, project-owner local self-audit. It does **not** authorize automated live
benchmarking, bulk profiles, third-party targets, or a representative dataset.

Any future live benchmark requires a separate written scope covering provider/legal and
privacy authorization, participant consent or approved public-professional cohort,
volume and concurrency, quota/cost, retention/deletion, independent scoring, and the
provider kill switch. Until then:

- CI and local regression tests must use recorded minimal fixtures or mocked Safe Fetch;
- `scripts/benchmark.py --live` must continue to fail; and
- fixture results must not be reported as evidence that the live provider meets latency,
  yield, precision, or production-readiness gates.
