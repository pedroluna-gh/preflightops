# Changelog

All notable changes to PreflightOps are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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

- Package development version advanced to 0.2.0 for the additive public CLI,
  Python, Action, schema, and report contracts.
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

[Unreleased]: https://github.com/pedroluna-gh/preflightops/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/pedroluna-gh/preflightops/compare/v0.1.1...v0.1.2
[0.1.0]: https://github.com/pedroluna-gh/preflightops/releases/tag/v0.1.0
