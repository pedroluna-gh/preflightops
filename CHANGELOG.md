# Changelog

All notable changes to PreflightOps are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Deterministic Assessment Contract v1 and offline Trust Kernel with immutable
  models, strict validation, canonical serialization, reproducible IDs/hashes,
  independent risk/confidence scoring, and an explicit human-decision boundary.
- Additive risk-report-v1 adapter, golden/schema/adversarial compatibility tests,
  and documented privacy, migration, invariants, and rollback controls.

- Signed hierarchical Policy Bundle v2 with effective dates, ownership,
  mandatory non-reducible controls, deterministic context overlays, lineage,
  explicit failure modes, lint, diff, simulation, signing and rollback.
- Signed Waiver Contract v1 with policy/context scope, expiry, requester/approver
  separation, reason/evidence/compensating controls, and fail-closed verification.
- A governance decision record that keeps the technical recommendation,
  verified exception and external CAB/Change decision separate; waivers never
  lower the risk score or grant automatic approval.

- Evidence Contract v2 as an Ed25519-signed DSSE envelope carrying an in-toto
  Statement with repository, commit, workflow, policy and input provenance.
- Offline `evidence generate` / `evidence verify` commands, machine-readable
  fail-closed verification, deterministic redaction and a v1/v2 dual-output
  compatibility path.
- Tamper, policy-trust, input-digest, identity and replay regression tests plus
  public schemas and an enterprise key-lifecycle runbook.

- Enterprise product charter, authority boundary, RACI, threat model, data
  governance, Definition of Done, and release-management controls.
- CodeQL, dependency review, OpenSSF Scorecard, Dependabot, CODEOWNERS, and a
  security-focused pull-request template.
- Protected-tag release workflow that builds once, generates an SPDX SBOM and
  checksums, creates GitHub/Sigstore provenance, preserves the immutable bundle,
  and publishes those exact artifacts.
- Contract tests that reject mutable third-party Action references and protect
  the security/release workflow invariants.

### Changed

- Minimum supported Python is now 3.11; EOL Python 3.9 and near-EOL Python 3.10
  were removed from the package contract and compatibility matrix.
- Dependency auditing now resolves and scans the locked CLI and web dependency
  graph plus the complete test/build toolchain independently on Python 3.11,
  3.12 and 3.13 in CI and before release.
- Test and build tooling now require patched `pytest>=9.0.3` and
  `setuptools==83.0.0` baselines.
- ClusterFuzzLite now exercises URL, mapping and observability trust boundaries
  on internal pull requests, main and a bounded weekly schedule.
- The ClusterFuzzLite builder image is pinned by immutable digest and its runtime
  dependencies are installed from the production lock export with required hashes.
- CodeQL URL validation coverage now uses an exact output-line assertion instead
  of an ambiguous URL substring check.
- Every external GitHub Action reference is pinned to a full commit SHA with a
  human-readable release comment, and checkout credentials are not persisted.

## [0.4.2] - 2026-08-28

### Changed

- GitHub Marketplace metadata now describes the SRE pre-change, pre-CAB,
  ServiceNow/Jira, infrastructure, and observability evidence contract.
- Consumer examples now reference `v0.4.2`.
- The Marketplace README now includes sanitized visual evidence of the protected
  ServiceNow publication workflow, its explicit non-CAB writable boundary, and
  the repeated-run idempotency/deduplication verification.
- Screenshot maintenance guidance and missing v0.4.1 changelog comparison links
  were corrected.

## [0.4.1] - 2026-08-28

### Changed

- GitHub artifact uploads now use `actions/upload-artifact@v7`, removing the
  Node.js 20 deprecation warning and aligning maintained workflows with the
  Node.js 24 runner baseline.
- Consumer examples now reference the `v0.4.1` patch release.

## [0.4.0] - 2026-08-28

### Added

- Public `preflightops-demo` repository with a completed real pull request,
  generated bot comment, review artifacts, and captured visual evidence.
- Versioned ServiceNow field mappings limited to pre-change evidence fields and
  optional `u_` custom fields.
- Network-free ServiceNow payload preview and a manual, environment-protected
  evidence demo workflow.
- Bounded, secret-scrubbed JSON evidence attachments with semantic SHA-256
  deduplication and upload verification.
- OAuth bearer-token support alongside the existing test-only Basic Auth path.

### Changed

- ServiceNow destinations now require HTTPS, trusted hostnames, standard ports,
  and same-origin redirects.
- ServiceNow idempotency now prefers immutable manifest change ids, migrates
  legacy title-based correlations, rejects ambiguous lookups, avoids unchanged
  writes, and fails closed when an explicitly referenced Change is missing.
- ServiceNow create/update operations are read back and field-verified before a
  successful result is returned.
- The ServiceNow integration now uses the versioned v1 Table API endpoint and
  explicitly preserves ServiceNow workflow and human CAB authority.

## [0.3.0] - 2026-08-28

### Added

- Compact GitHub pull-request comments with a prominent risk badge, summary
  table, grouped findings, top remediation actions, and optional full-report link.
- Metadata-only GitHub PR changed-file discovery with pagination, scanner-scope
  classification, and safe automatic loading of structured Terraform plans and
  Kubernetes manifests.
- Dependency-free static HTML reports for CAB reviewers and non-technical
  stakeholders.
- Structured `terraform show -json` parsing with per-resource lifecycle,
  provider-type, public-exposure, and replacement-versus-destroy evidence.
- Multi-document Kubernetes object parsing with per-container probe and
  requests/limits validation.
- Versioned policy packs and customizable rule weights/thresholds for SaaS,
  fintech, ecommerce, healthcare, critical platforms, and startups.
- Secrets-free monitor inventory validation for Datadog, Grafana, Prometheus,
  Zabbix, and GCP Cloud Monitoring evidence.
- Versioned policy-pack and monitor-inventory JSON schemas.
- Contract Set v1 with JSON Schemas for the service catalog, change request,
  JSON risk report, and ticket template.
- Public contract inventory, compatibility policy, and versioning ADR.
- `preflightops --version` and version metadata in Markdown/JSON reports.
- Reproducible uv lockfile, documented quality gates, cross-platform/Python
  compatibility matrix, dependency audit, and packaging/action contract checks.
- A manual adoption workflow backed by the repository's real LOW, HIGH, and
  CRITICAL examples.

### Changed

- Package version advanced to 0.3.0 for the additive structured evidence, reporting,
  changed-file, Python, CLI, Action, and JSON report contracts.
- Package metadata, Python API, CLI, and reports now use one version source.
- Documentation now distinguishes the source repository's manual smoke workflow
  from consumer pull-request integrations and accurately describes opt-in API
  calls.
- GitHub workflows now use read-only permissions, explicit runner images,
  bounded timeouts, controlled tool versions, and lock-derived dependency cache.

## [0.1.2] - 2026-06-08

  Maintenance release focused on repo hygiene, documentation, and consistency of
  the GitHub Action references. The risk engine (scoring, rules, and scanners) is
  unchanged from 0.1.0.

  ### Changed

  - All example Action references now point to `pedroluna-gh/preflightops@v0.1.2`
    (README, `docs/GITHUB_ACTION.md`, and the landing site), removing stale
    references to earlier versions.
  - Reworded the README usage guidance around technical pre-CAB reviews: aligning
    on risk, rollback readiness, monitoring coverage, and implementation evidence
    before formal approval.
  - Clarified the ITSM integration scope in `docs/RISK_MODEL.md`: PreflightOps
    can generate ServiceNow/Jira-ready change summaries and optionally push them
    when explicitly enabled. It does not yet provide full ITSM workflow
    orchestration, advanced field mapping, enterprise approval-state modeling, or
    deep ServiceNow/Jira workflow customization.

  ### Maintenance

  - Bumped the `preflightops` package version to `0.1.2`.
  - Tightened Python `.gitignore` hygiene (`__pycache__/`, `*.pyc`,
    `.pytest_cache/`, `*.egg-info/`) and removed generated artifacts that were
    committed by mistake.

  ## [0.1.0] - 2026-06-07

Initial public release.

### Added

- **Risk engine** that turns a service catalog and a change request into a
  `0–100` risk score, a risk level (`LOW` / `MEDIUM` / `HIGH` / `CRITICAL`),
  a plain-English recommendation, the triggered rules, and a list of missing
  operational controls.
- **Service-control and change-type rules**: production change, critical
  service, missing owner / runbook / business impact, missing or vague rollback
  plan, incomplete monitoring plan, missing validation plan, and database /
  security / network / infrastructure change types.
- **Terraform scanner** for risky keywords (IAM, security groups, firewalls,
  databases, KMS, DNS, public IP exposure, and `destroy` / `delete` actions).
- **Kubernetes scanner** for risky signals (Ingress, Secret, NetworkPolicy,
  StatefulSet, LoadBalancer exposure, `replicas: 0`, and Deployments missing
  readiness / liveness probes).
- **Markdown and JSON reports** with a per-source score breakdown.
- **Streamlit web app** with built-in LOW / HIGH / CRITICAL example loaders.
- **`preflightops` CLI** that exits `1` on CRITICAL risk and `2` on input errors.
- **Composite GitHub Action** (`action.yml`) and a ready-to-use PR risk-gate
  workflow that comments the report on pull requests and uploads it as an artifact.
- **Documentation**: README, risk model, input schema, GitHub Action guide,
  roadmap, screenshots guide, plus `CONTRIBUTING.md` and `SECURITY.md`.
- **pytest suite** covering the engine, validators, scanners, reports, CLI,
  web app, and the documented example scenarios.

[Unreleased]: https://github.com/pedroluna-gh/preflightops/compare/v0.4.2...HEAD
[0.4.2]: https://github.com/pedroluna-gh/preflightops/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/pedroluna-gh/preflightops/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/pedroluna-gh/preflightops/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/pedroluna-gh/preflightops/compare/v0.1.2...v0.3.0
[0.1.2]: https://github.com/pedroluna-gh/preflightops/compare/v0.1.1...v0.1.2
[0.1.0]: https://github.com/pedroluna-gh/preflightops/releases/tag/v0.1.0

