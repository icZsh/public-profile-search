# Policy schema

Reserved for generated, versioned policy schemas. The current implementation is a
deterministic local boundary rather than a generated policy package.

Current live-policy invariants:

- provider: `github_public_profile_v1` only;
- provider status: `approved_for_limited_evaluation` for project-owner localhost use,
  never `approved_for_mvp`;
- input: direct allowlisted GitHub profile URL, not a username or arbitrary URL;
- purpose: `self_audit`;
- relationship: `self`;
- eligibility: profile-control proof plus a separate operator confirmation of adult and
  public-professional/creator scope;
- default eligibility lifetime: 24 hours;
- suppression and eligibility are rechecked before fetch, persistence, and display;
- allowed displayed predicates: `identity.public_display_name` and
  `account.verified_input_profile`; and
- contact, location, demographic, sensitive, bio, social-count, and inferred attributes
  are not displayable.

The synthetic fixture policy remains available for deterministic tests and the demo.
Before any alpha or production use, generate these rules from a versioned canonical
schema, add migration compatibility checks, and obtain the provider/privacy/security
approvals required by the project plan.
